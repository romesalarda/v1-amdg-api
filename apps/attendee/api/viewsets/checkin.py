from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from django.db.models.functions import TruncDate
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from apps.attendee.models import (
    Attendee, AttendeeAction,
    AttendeeCheckIn, CheckInAction, CheckInMethod, CheckInScanResult,
)

from apps.bookings.models import Ticket
from apps.events.models.venue import EventVenue, EventVenueRoom


from apps.attendee.api.serializers import (
    CheckInCreateSerializer, CheckInResponseSerializer,
    CheckInBroadcastSerializer,
)
from apps.attendee.services.pre_removal import AttendeePreRemovalSummaryService
from uuid import UUID

from apps.attendee.api.permissions import IsEventStaffOrReadOnly
from apps.common.pagination import StandardPagination

from apps.bookings.models import AttendeeAlternativeSigninIdentifier
from apps.attendee.models import EventAttendance

@extend_schema_view(
    list=extend_schema(
        summary="List Check-In Records",
        description=(
            "Retrieve paginated check-in/check-out audit records. "
            "Filter by event, attendee, method, scan_result, action, and date range."
        ),
        parameters=[
            OpenApiParameter('event', OpenApiTypes.UUID, description='Filter by event ID'),
            OpenApiParameter('attendee', OpenApiTypes.UUID, description='Filter by attendee UUID'),
            OpenApiParameter('method', OpenApiTypes.STR, description='Filter by method (QR_CODE, MANUAL, ADMIN)'),
            OpenApiParameter('scan_result', OpenApiTypes.STR, description='Filter by scan result'),
            OpenApiParameter('action', OpenApiTypes.STR, description='Filter by action (CHECK_IN, CHECK_OUT)'),
        ],
        tags=['Check-In'],
    ),
    create=extend_schema(
        summary="Record a Check-In / Check-Out",
        description=(
            "Creates an AttendeeCheckIn audit record, updates EventAttendance state, "
            "and broadcasts the result over the event's WebSocket check-in channel."
        ),
        tags=['Check-In'],
        responses={201: CheckInResponseSerializer},
    ),
    retrieve=extend_schema(
        summary="Get Check-In Record",
        tags=['Check-In'],
        parameters=[
            OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH, description='Check-in record UUID'),
        ],
    ),
)
class CheckInViewSet(viewsets.GenericViewSet):
    """
    ViewSet for AttendeeCheckIn.

    Supports:
    - POST (create): Record a check-in/out, broadcast over WS
    - GET (list): Paginated history with filters
    - GET (retrieve): Single record detail
    """

    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['performed_at']
    ordering = ['-performed_at']

    def get_queryset(self):
        qs = AttendeeCheckIn.objects.select_related(
            'attendee', 'attendee__area_from',
            'ticket', 'ticket__ticket_type',
            'venue', 'venue_room',
            'performed_by',
        )
        event_id = self.request.query_params.get('event')
        if event_id:
            try:
                event_uuid = UUID(event_id)
                qs = qs.filter(attendee__event__event_id=event_uuid)
            except ValueError:
                qs = qs.filter(attendee__event__url_safe_title=event_id)

        attendee_id = self.request.query_params.get('attendee')
        if attendee_id:
            qs = qs.filter(attendee__attendee_id=attendee_id)
        method = self.request.query_params.get('method')
        if method:
            qs = qs.filter(method=method)
        scan_result = self.request.query_params.get('scan_result')
        if scan_result:
            qs = qs.filter(scan_result=scan_result)
        action = self.request.query_params.get('action')
        if action:
            qs = qs.filter(action=action)
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return CheckInCreateSerializer
        return CheckInResponseSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = CheckInResponseSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = CheckInResponseSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = get_object_or_404(AttendeeCheckIn, check_in_id=kwargs.get('pk'))
        serializer = CheckInResponseSerializer(instance)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):

        input_serializer = CheckInCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        # ── Resolve attendee / ticket ─────────────────────────────────────
        ticket = None
        attendee = None

        if data.get('ticket_code'):
            ticket = Ticket.objects.select_related(
                'attendee', 'attendee__area_from', 'ticket_type'
            ).filter(Q(ticket_code=data['ticket_code']) | Q(attendee_alternative_signins__identifier=data['ticket_code'])).first()

            if ticket:
                attendee = ticket.attendee

        if not attendee and data.get('attendee_display_id'):
            attendee = Attendee.objects.select_related('area_from').filter(
                attendee_display_id=data['attendee_display_id']
            ).first()

        if not attendee:
            return Response(
                {'detail': 'Attendee not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Resolve venue (optional) ──────────────────────────────────────
        venue = None
        venue_room = None
        if data.get('venue_id'):
            venue = EventVenue.objects.filter(event_venue_id=data['venue_id']).first()
        if data.get('venue_room_id'):
            venue_room = EventVenueRoom.objects.filter(pk=data['venue_room_id']).first()

        # ── Determine scan_result ─────────────────────────────────────────
        action = data.get('action', CheckInAction.CHECK_IN)
        scan_result = CheckInScanResult.SUCCESS

        from apps.attendee.models import AttendeeStatus
        if attendee.status == AttendeeStatus.CANCELLED:
            scan_result = CheckInScanResult.CANCELLED_ATTENDEE
        elif ticket and ticket.status == 'CANCELLED':
            scan_result = CheckInScanResult.CANCELLED_TICKET
        elif action == CheckInAction.CHECK_IN:
            if attendee.is_checked_in:
                scan_result = CheckInScanResult.ALREADY_CHECKED_IN
        elif action == CheckInAction.CHECK_OUT:
            if not attendee.is_checked_in:
                scan_result = CheckInScanResult.ALREADY_CHECKED_OUT

        has_outstanding = attendee.has_outstanding_payments

        # ── Update EventAttendance state (successful scans only) ──────────
        if scan_result == CheckInScanResult.SUCCESS and attendee.event:
            if action == CheckInAction.CHECK_IN:
                attendee.mark_checked_in(
                    event=attendee.event,
                    checked_in_by=request.user,
                )
            elif action == CheckInAction.CHECK_OUT:
                attendee.mark_checked_out(
                    event=attendee.event,
                    checked_out_by=request.user,
                )

        # ── Compute event day ─────────────────────────────────────────────
        # Day 1 = event start calendar date (in event timezone)
        # Negative  = check-in before event window
        # >N        = check-in after event window
        event_day = None
        if attendee.event_id and attendee.event:
            try:
                import pytz
                from datetime import timezone as dt_timezone
                event = attendee.event
                event_tz = pytz.timezone(str(event.timezone)) if hasattr(event, 'timezone') and event.timezone else pytz.UTC
                now_local = timezone.now().astimezone(event_tz)
                start_local = event.start_datetime.astimezone(event_tz)
                delta = (now_local.date() - start_local.date()).days
                event_day = delta + 1  # Day 1 = event start date
            except Exception:
                event_day = None

        if scan_result == CheckInScanResult.SUCCESS:
            attendee.status = AttendeeStatus.CHECKED_IN if action == CheckInAction.CHECK_IN else AttendeeStatus.CHECKED_OUT
            attendee.save(update_fields=['status', 'updated_at'])

        elif action == CheckInAction.CHECK_IN and scan_result != CheckInScanResult.SUCCESS:
            # For failed check-in attempts, we may still want to update the status to reflect the attempt
            if scan_result in [CheckInScanResult.CANCELLED_ATTENDEE, CheckInScanResult.CANCELLED_TICKET]:
                attendee.status = AttendeeStatus.CANCELLED
                attendee.save(update_fields=['status', 'updated_at'])

        elif action == CheckInAction.CHECK_OUT and scan_result != CheckInScanResult.SUCCESS:
            # For failed check-out attempts, we may still want to update the status to reflect the attempt
            if scan_result == CheckInScanResult.ALREADY_CHECKED_OUT:
                attendee.status = AttendeeStatus.CHECKED_OUT
                attendee.save(update_fields=['status', 'updated_at'])

        # ── Create audit record ───────────────────────────────────────────
        check_in = AttendeeCheckIn.objects.create(
            attendee=attendee,
            ticket=ticket,
            action=action,
            method=data.get('method', CheckInMethod.MANUAL),
            scan_result=scan_result,
            venue=venue,
            venue_room=venue_room,
            performed_by=request.user,
            attendee_status_snapshot=attendee.status,
            has_outstanding_payments=has_outstanding,
            notes=data.get('notes', ''),
            device_info=data.get('device_info'),
            event_day=event_day,
        )

        # ── Broadcast over WS channel layer ──────────────────────────────
        if attendee.event_id:
            broadcast_data = CheckInBroadcastSerializer(check_in).data
            broadcast_data['type'] = 'checkin.occurred'
            channel_layer = get_channel_layer()
            if channel_layer:
                event_uuid = attendee.event.event_id
                # Broadcast to check-in log consumers
                async_to_sync(channel_layer.group_send)(
                    f"event_{event_uuid}_checkin",
                    {'type': 'checkin_event', 'data': broadcast_data},
                )
                # Broadcast to attendee roster consumers so they can push live updates
                async_to_sync(channel_layer.group_send)(
                    f"event_{event_uuid}_attendees",
                    {'type': 'roster_checkin_event', 'data': broadcast_data},
                )

        response_serializer = CheckInResponseSerializer(check_in)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='log-dates',
            permission_classes=[IsEventStaffOrReadOnly])
    def log_dates(self, request, *args, **kwargs):
        """
        Return a paginated list of distinct calendar dates on which check-in
        logs exist for a given event, ordered most-recent first.

        Query params:
          event (UUID)  — required
        """
        event_id = request.query_params.get('event')
        if not event_id:
            return Response(
                {'detail': 'event query parameter is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            UUID(str(event_id))
        except (ValueError, AttributeError):
            return Response(
                {'detail': 'Invalid event UUID.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


        dates_qs = (
            AttendeeCheckIn.objects
            .filter(attendee__event__event_id=event_id)
            .annotate(log_date=TruncDate('performed_at'))
            .values_list('log_date', flat=True)
            .distinct()
            .order_by('-log_date')
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(dates_qs, request)
        if page is not None:
            # Convert date objects to ISO strings
            results = [d.isoformat() if d else None for d in page]
            return paginator.get_paginated_response(results)

        results = [d.isoformat() if d else None for d in dates_qs]
        return Response(results)

    @action(detail=False, methods=['delete'], url_path='bulk-delete-logs',
            permission_classes=[IsEventStaffOrReadOnly])
    def bulk_delete_logs(self, request, *args, **kwargs):
        """
        Delete AttendeeCheckIn audit records for a specific event.

        Deletion scope (mutually exclusive priority):
          1. date       — single calendar date
          2. date_from / date_to — inclusive date range (either or both can be set)
          3. neither    — delete ALL logs for the event

        Request body:
          event     (UUID)  — required
          date      (date)  — optional; single date, takes precedence
          date_from (date)  — optional; start of range (inclusive)
          date_to   (date)  — optional; end of range (inclusive)
        """
        from apps.attendee.api.serializers import BulkDeleteCheckInsSerializer

        serializer = BulkDeleteCheckInsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        qs = AttendeeCheckIn.objects.filter(
            attendee__event__event_id=data['event']
        )
        if data.get('date'):
            qs = qs.filter(performed_at__date=data['date'])
        else:
            if data.get('date_from'):
                qs = qs.filter(performed_at__date__gte=data['date_from'])
            if data.get('date_to'):
                qs = qs.filter(performed_at__date__lte=data['date_to'])

        count, _ = qs.delete()
        return Response({'deleted': count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='bulk-status',
            permission_classes=[IsEventStaffOrReadOnly])
    def bulk_status_update(self, request, *args, **kwargs):
        """
        Mass check-in or check-out all (or specific) attendees in an event.

        Creates an AttendeeCheckIn audit record for every affected attendee,
        updates EventAttendance state, and broadcasts a bulk notification over
        both the check-in and roster WS channel groups.

        Request body:
          event        (UUID)        — required
          action       (CHECK_IN | CHECK_OUT) — required
          attendee_ids (list[UUID])  — optional; empty = all non-cancelled attendees
        """
        from apps.attendee.api.serializers import BulkAttendeeStatusUpdateSerializer
        from apps.attendee.models import AttendeeStatus, AttendeeActionChoices
        from apps.events.models import Event
        import pytz

        serializer = BulkAttendeeStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            event = Event.objects.get(event_id=data['event'])
        except Event.DoesNotExist:
            return Response({'detail': 'Event not found.'}, status=status.HTTP_404_NOT_FOUND)

        bulk_action = data['action']
        attendee_qs = (
            Attendee.objects
            .filter(event=event, deleted_at__isnull=True)
            .exclude(status=AttendeeStatus.CANCELLED)
            .select_related('area_from')
        )
        if data.get('attendee_ids'):
            attendee_qs = attendee_qs.filter(attendee_id__in=data['attendee_ids'])

        attendees = list(attendee_qs)
        if not attendees:
            return Response({'updated': 0}, status=status.HTTP_200_OK)

        new_status = (
            AttendeeStatus.CHECKED_IN
            if bulk_action == CheckInAction.CHECK_IN
            else AttendeeStatus.CHECKED_OUT
        )
        action_choice = (
            AttendeeActionChoices.CHECKED_IN
            if bulk_action == CheckInAction.CHECK_IN
            else AttendeeActionChoices.CHECKED_OUT
        )

        # Compute event day
        event_day = None
        try:
            event_tz = (
                pytz.timezone(str(event.timezone))
                if hasattr(event, 'timezone') and event.timezone
                else pytz.UTC
            )
            now_local = timezone.now().astimezone(event_tz)
            start_local = event.start_datetime.astimezone(event_tz)
            delta = (now_local.date() - start_local.date()).days
            event_day = delta + 1
        except Exception:
            event_day = None

        # Bulk create audit records
        AttendeeCheckIn.objects.bulk_create([
            AttendeeCheckIn(
                attendee=att,
                action=bulk_action,
                method=CheckInMethod.ADMIN,
                scan_result=CheckInScanResult.SUCCESS,
                performed_by=request.user,
                attendee_status_snapshot=new_status,
                has_outstanding_payments=att.has_outstanding_payments,
                event_day=event_day,
            )
            for att in attendees
        ])

        # Bulk update attendee statuses
        for att in attendees:
            att.status = new_status
        Attendee.objects.bulk_update(attendees, ['status', 'updated_at'])

        # Upsert EventAttendance records
        for att in attendees:
            if bulk_action == CheckInAction.CHECK_IN:
                EventAttendance.objects.update_or_create(
                    event=event,
                    attendee=att,
                    defaults={'check_in_by': request.user},
                    check_in_time=timezone.now()
                )
            else:
                EventAttendance.objects.filter(event=event, attendee=att).update(
                    check_out_by=request.user,
                    check_out_time=timezone.now()
                )

        # Bulk create action log entries
        AttendeeAction.objects.bulk_create([
            AttendeeAction(
                action=action_choice,
                attendee=att,
                performed_by=request.user,
            )
            for att in attendees
        ])

        # Broadcast bulk notification over WS
        channel_layer = get_channel_layer()
        if channel_layer:
            bulk_payload = {
                'action': bulk_action,
                'count': len(attendees),
            }
            async_to_sync(channel_layer.group_send)(
                f"event_{event.event_id}_checkin",
                {'type': 'checkin_bulk_event', 'data': bulk_payload},
            )
            async_to_sync(channel_layer.group_send)(
                f"event_{event.event_id}_attendees",
                {'type': 'roster_bulk_event', 'data': bulk_payload},
            )

        return Response({'updated': len(attendees)}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='attendee-status',
            permission_classes=[IsEventStaffOrReadOnly])
    def attendee_status_update(self, request, *args, **kwargs):
        """
        Check in or check out one or more specific attendees by their UUIDs.

        The event is inferred from the attendees, so callers do not need to
        supply an event UUID. Attendees spanning multiple events are handled
        correctly — audit records and WS broadcasts are scoped per-event.

        Request body:
          attendee_ids (list[UUID])           — required, 1 or more
          action       (CHECK_IN | CHECK_OUT) — required
        """
        from apps.attendee.api.serializers import AttendeeStatusUpdateSerializer
        from apps.attendee.models import AttendeeStatus, AttendeeActionChoices
        import pytz

        serializer = AttendeeStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target_action = data['action']

        attendees = list(
            Attendee.objects
            .filter(attendee_id__in=data['attendee_ids'], deleted_at__isnull=True)
            .exclude(status=AttendeeStatus.CANCELLED)
            .select_related('event', 'area_from')
        )

        if not attendees:
            return Response({'updated': 0}, status=status.HTTP_200_OK)

        new_status = (
            AttendeeStatus.CHECKED_IN
            if target_action == CheckInAction.CHECK_IN
            else AttendeeStatus.CHECKED_OUT
        )
        action_choice = (
            AttendeeActionChoices.CHECKED_IN
            if target_action == CheckInAction.CHECK_IN
            else AttendeeActionChoices.CHECKED_OUT
        )

        # Group attendees by event (for correct event_day and per-event WS broadcast)
        events_seen: dict = {}
        for att in attendees:
            ev = att.event
            ev_key = str(ev.event_id)
            if ev_key not in events_seen:
                event_day = None
                try:
                    event_tz = (
                        pytz.timezone(str(ev.timezone))
                        if hasattr(ev, 'timezone') and ev.timezone
                        else pytz.UTC
                    )
                    now_local = timezone.now().astimezone(event_tz)
                    start_local = ev.start_datetime.astimezone(event_tz)
                    delta = (now_local.date() - start_local.date()).days
                    event_day = delta + 1
                except Exception:
                    event_day = None
                events_seen[ev_key] = {'event': ev, 'event_day': event_day, 'attendees': []}
            events_seen[ev_key]['attendees'].append(att)

        # Bulk create audit records (per-event for correct event_day)
        AttendeeCheckIn.objects.bulk_create([
            AttendeeCheckIn(
                attendee=att,
                action=target_action,
                method=CheckInMethod.ADMIN,
                scan_result=CheckInScanResult.SUCCESS,
                performed_by=request.user,
                attendee_status_snapshot=new_status,
                has_outstanding_payments=att.has_outstanding_payments,
                event_day=ev_data['event_day'],
            )
            for ev_data in events_seen.values()
            for att in ev_data['attendees']
        ])

        # Bulk update attendee statuses
        for att in attendees:
            att.status = new_status
        Attendee.objects.bulk_update(attendees, ['status', 'updated_at'])

        # Bulk create action log entries
        AttendeeAction.objects.bulk_create([
            AttendeeAction(
                action=action_choice,
                attendee=att,
                performed_by=request.user,
            )
            for att in attendees
        ])

        # Broadcast per-event WS notifications
        channel_layer = get_channel_layer()
        if channel_layer:
            for ev_data in events_seen.values():
                ev = ev_data['event']
                bulk_payload = {
                    'action': target_action,
                    'count': len(ev_data['attendees']),
                }
                async_to_sync(channel_layer.group_send)(
                    f"event_{ev.event_id}_checkin",
                    {'type': 'checkin_bulk_event', 'data': bulk_payload},
                )
                async_to_sync(channel_layer.group_send)(
                    f"event_{ev.event_id}_attendees",
                    {'type': 'roster_bulk_event', 'data': bulk_payload},
                )

        return Response({'updated': len(attendees)}, status=status.HTTP_200_OK)
