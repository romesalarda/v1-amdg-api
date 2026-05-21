"""
WebSocket consumer for the live attendee roster.

Clients connect to: ws://host/ws/events/{event_identifier}/attendees/

This consumer serves a paginated, filterable attendee list ordered by most-recently
checked-in first. It receives check-in broadcasts from the channel layer and pushes
incremental `attendee.updated` messages so the client can update rows in-place without
a full re-fetch.

Client → Server messages:
- attendee.list.request  : Request a page of attendees (paginated)
- attendee.filter.set    : Update active filters for this connection

Server → Client messages:
- attendee.list.response : Paginated attendee roster
- attendee.updated       : Single attendee state after a check-in occurred
- error                  : Validation / permission error (inherited)
- authenticated          : Connection established (inherited)
- pong                   : Keepalive (inherited)
- user.joined / user.left / presence.list : Presence (inherited)
"""
import json
import logging
from typing import Dict, Any

from channels.db import database_sync_to_async
from django.db.models import Max, Q, OuterRef, Subquery
from django.utils import timezone

from .base import BaseRealtimeConsumer
from apps.attendee.api.serializers import (
    AttendeeRosterFilterSerializer,
    AttendeeRosterRequestSerializer,
    AttendeeRosterItemSerializer,
)
from apps.attendee.api.filtersets import AttendeeFilterSet
from apps.attendee.models import Attendee, AttendeeCheckIn, CheckInAction, CheckInScanResult

from apps.events.models import Event

logger = logging.getLogger(__name__)


class AttendeeRosterConsumer(BaseRealtimeConsumer):
    """
    WebSocket consumer for the live attendee roster table.

    Extends BaseRealtimeConsumer with attendee-roster–specific logic.
    """

    resource_name = "attendee_roster"

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def connect(self):
        self.authenticated = False
        self.user = None
        self.group_name = None
        self.presence_group_name = None
        self.presence_key = None

        self.event_identifier = self.scope['url_route']['kwargs']['event_identifier']
        self.event = await self.get_event()

        if not self.event:
            logger.warning(
                f"[attendee_roster] Event not found for identifier: {self.event_identifier}"
            )
            await self.close()
            return

        self.event_id = self.event.event_id

        # Per-connection roster filter state
        self.roster_filters: dict = {}

        await super().connect()

    # ── Abstract method implementations ────────────────────────────────────

    async def get_room_name(self) -> str:
        return f"event_{self.event_id}_attendees"

    async def get_presence_room_name(self) -> str:
        return f"event_{self.event_id}_attendees_presence"

    async def get_presence_key(self) -> str:
        return f"event_attendees_presence:{self.event_id}"

    async def check_permission(self) -> bool:
        if not self.event:
            return False
        return await self.check_event_permission()

    async def get_user_context(self) -> Dict[str, Any]:
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': getattr(self.user, 'get_full_name', lambda: self.user.email)(),
            'event_id': str(self.event_id),
        }

    async def handle_authenticated_message(self, message_type: str, data: dict):
        if message_type == 'attendee.list.request':
            await self.handle_list_request(data)
        elif message_type == 'attendee.filter.set':
            await self.handle_filter_set(data)
        else:
            logger.debug(
                f"[attendee_roster] Unhandled message type: {message_type} "
                f"from user {self.user.email}"
            )

    # ── Message handlers ───────────────────────────────────────────────────

    async def handle_list_request(self, data: dict):
        """Return a paginated attendee roster page to this client only."""
        request_serializer = AttendeeRosterRequestSerializer(data=data)
        if not request_serializer.is_valid():
            await self.send_error(f"Invalid list request: {request_serializer.errors}")
            return

        validated = request_serializer.validated_data
        page = validated['page']
        page_size = validated['page_size']
        filters = validated.get('filters') or {}

        # Merge in any persistent per-connection filters
        merged_filters = {**self.roster_filters, **filters}

        result = await self.fetch_roster_page(page, page_size, merged_filters)

        await self.send(text_data=json.dumps({
            'type': 'attendee.list.response',
            'attendees': result['attendees'],
            'page': page,
            'page_size': page_size,
            'total_count': result['total_count'],
            'timestamp': timezone.now().isoformat(),
        }))

    async def handle_filter_set(self, data: dict):
        """Validate and store per-connection roster filters."""
        filter_data = data.get('filters', {})
        filter_serializer = AttendeeRosterFilterSerializer(data=filter_data)

        if not filter_serializer.is_valid():
            await self.send_error(f"Invalid filter data: {filter_serializer.errors}")
            return

        self.roster_filters = filter_serializer.validated_data
        await self.send(text_data=json.dumps({
            'type': 'attendee.filter.accepted',
            'filters': self.roster_filters,
            'timestamp': timezone.now().isoformat(),
        }))

    # ── Channel-layer event handler ────────────────────────────────────────

    async def roster_checkin_event(self, event: Dict[str, Any]):
        """
        Handle roster_checkin_event messages from the channel layer.

        Pushed by CheckInViewSet.create after a check-in is recorded.
        Fetches fresh attendee state and broadcasts attendee.updated.
        """
        try:
            payload = event.get('data', {})
            attendee_id = payload.get('attendee_id')
            if not attendee_id:
                return

            attendee_data = await self.fetch_single_attendee(str(attendee_id))
            if attendee_data:
                await self.send(text_data=json.dumps({
                    'type': 'attendee.updated',
                    'attendee': attendee_data,
                    'timestamp': timezone.now().isoformat(),
                }))
        except Exception as e:
            logger.error(
                f"[attendee_roster] Error handling roster_checkin_event: {str(e)}",
                exc_info=True,
            )

    async def roster_bulk_event(self, event: Dict[str, Any]):
        """
        Handle roster_bulk_event messages from the channel layer.

        Pushed by CheckInViewSet.bulk_status_update after a mass check-in/out.
        Tells clients that a bulk status change occurred so they can refresh.
        """
        payload = event.get('data', {})
        await self.send(text_data=json.dumps({
            'type': 'bulk.status.updated',
            'action': payload.get('action'),
            'count': payload.get('count'),
            'timestamp': timezone.now().isoformat(),
        }))

    # ── Database helpers ───────────────────────────────────────────────────

    @database_sync_to_async
    def get_event(self):
        """Resolve event from identifier (slug or UUID)."""
        try:
            return Event.objects.filter(url_safe_title=self.event_identifier).first()
        except ValueError:
            return Event.objects.filter(
                display_code__iexact=self.event_identifier
            ).first()

    @database_sync_to_async
    def check_event_permission(self) -> bool:
        """Staff / creator / superuser check."""
        if not self.user or not self.user.is_authenticated:
            return False
        if self.user.is_superuser or self.user.is_staff:
            return True
        if self.event.created_by == self.user:
            return True
        return self.event.is_staff(self.user)

    @database_sync_to_async
    def fetch_roster_page(self, page: int, page_size: int, filters: dict) -> dict:
        """
        Fetch a page of attendees for the event, ordered by most-recently
        checked-in first (unchecked attendees at the end).

        ``filters`` supports all fields validated by ``AttendeeRosterFilterSerializer``.
        The ``day`` field is handled locally via an annotation; all other fields are
        delegated to ``AttendeeFilterSet`` so that the WS roster and the HTTP
        participants dashboard share the same filter logic.
        """
        from apps.attendee.models import AttendeeCheckIn, CheckInAction, CheckInScanResult
        from django.db.models import Subquery, OuterRef, Case, When, Value

        # Latest successful CHECK_IN per attendee (optionally scoped to a day)
        checkin_qs = AttendeeCheckIn.objects.filter(
            attendee=OuterRef('pk'),
            action=CheckInAction.CHECK_IN,
            scan_result=CheckInScanResult.SUCCESS,
        )
        day_filter = filters.get('day')
        if day_filter is not None:
            checkin_qs = checkin_qs.filter(event_day=day_filter)

        checkin_qs = checkin_qs.order_by('-performed_at')

        attendee_qs = (
            Attendee.objects
            .filter(event__event_id=self.event_id, deleted_at__isnull=True)
            .select_related('area_from', 'booking')
            .annotate(
                last_check_in_at=Subquery(checkin_qs.values('performed_at')[:1]),
                event_day_last_seen=Subquery(checkin_qs.values('event_day')[:1]),
            )
        )

        # Apply all remaining filters via AttendeeFilterSet (reuses HTTP filter logic).
        # Strip day and blank/None values — django-filters handles only known field names.
        filterset_data = {
            k: v
            for k, v in filters.items()
            if k != 'day' and v is not None and v != ''
        }
        if filterset_data:
            filterset = AttendeeFilterSet(data=filterset_data, queryset=attendee_qs)
            if filterset.is_valid():
                attendee_qs = filterset.qs

        # Order: checked-in most-recently first, unchecked at the end
        attendee_qs = attendee_qs.order_by(
            Case(When(last_check_in_at__isnull=True, then=Value(1)), default=Value(0)),
            '-last_check_in_at',
        )

        total_count = attendee_qs.count()
        offset = (page - 1) * page_size
        attendees = attendee_qs[offset: offset + page_size]

        serializer = AttendeeRosterItemSerializer(attendees, many=True)
        return {
            'attendees': serializer.data,
            'total_count': total_count,
        }

    @database_sync_to_async
    def fetch_single_attendee(self, attendee_id: str) -> dict | None:
        """Fetch a single attendee with fresh check-in state for attendee.updated push."""

        checkin_qs = AttendeeCheckIn.objects.filter(
            attendee=OuterRef('pk'),
            action=CheckInAction.CHECK_IN,
            scan_result=CheckInScanResult.SUCCESS,
        ).order_by('-performed_at')

        try:
            attendee = (
                Attendee.objects
                .filter(attendee_id=attendee_id)
                .select_related('area_from', 'booking')
                .annotate(
                    last_check_in_at=Subquery(checkin_qs.values('performed_at')[:1]),
                    event_day_last_seen=Subquery(checkin_qs.values('event_day')[:1]),
                )
                .first()
            )
            if not attendee:
                return None
            return AttendeeRosterItemSerializer(attendee).data
        except Exception as e:
            logger.error(f"[attendee_roster] fetch_single_attendee error: {e}", exc_info=True)
            return None
