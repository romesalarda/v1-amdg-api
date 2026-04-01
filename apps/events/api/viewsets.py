from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch, Count
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.shortcuts import get_object_or_404
from decimal import Decimal
import uuid
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.events.models import (
    Event, EventType, EventSettings, EventStatusChoices,
    EventAuthorization, EventAuthorizationStatusChoices,
    EventPermission, EventPermissionAssignment,
    EventRole, EventRoleAssignment,
    EventStaff, EventStaffAvailability, EventStaffInvite,
    EventReview,
    EventQuestion, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice, EventVenue, EventRoleCategoryChoices
)
from apps.common.models import AvailabilityWindow, Resource
from apps.common.api.serializers import (
    AvailabilityWindowSerializer,
    AvailabilityWindowTemplateSerializer,
    ResourceSerializer
)
from apps.events.api.serializers import (
    
    EventTypeSerializer, EventListSerializer, EventDetailSerializer,
    EventCreateUpdateSerializer, EventSettingsSerializer, SponsorableEventListSerializer,
    EventAuthorizationSerializer, EventPermissionSerializer,
    EventPermissionAssignmentSerializer, EventRoleSerializer,
    EventRoleAssignmentSerializer, EventStaffSerializer,
    EventStaffAvailabilitySerializer, EventReviewSerializer,
    EventQuestionSerializer, EventQuestionOptionSerializer,
    EventQuestionAnswerSerializer, EventQuestionAnswerChoiceSerializer,
    EventVenueSerializer, EventStaffInviteSerializer, EventStaffInviteListSerializer,
    EventMyBookingResponseSerializer,
        EventMyOutstandingPaymentSerializer,
        EventMyPaymentSummarySerializer,
)
from apps.bookings.models import Booking
from apps.products.models.orders import Order
from apps.payments.models import PaymentStatusChoices

from apps.events.services import OutstandingPaymentsService
from apps.events.api.filtersets import (
    EventAuthorizationFilterSet,
    EventQuestionAnswerFilterSet,
    EventQuestionFilterSet,
    EventMyBookingFilterSet,
    EventMyOutstandingPaymentsFilterSet,
    EventPermissionAssignmentFilterSet,
    EventReviewFilterSet,
    EventRoleAssignmentFilterSet,
    EventStaffFilterSet,
    EventStaffInviteFilterSet,
    EventVenueFilterSet,
)

from apps.events.api.pagination import StandardPagination

from apps.events.api.permissions import (
    IsEventOwnerOrStaffMember,
    CannotTargetEventCreator,
)
from apps.organisations.models import EventSponsor, EventSponsorPackage, OrganisationControl
from apps.organisations.api.serializers import (
    EventSponsorListSerializer,
    EventSponsorDetailSerializer,
    EventSponsorCreateUpdateSerializer,
    EventSponsorPackageListSerializer,
    EventSponsorPackageDetailSerializer,
    EventSponsorPackageCreateUpdateSerializer,
)


@extend_schema_view(
    list=extend_schema(
        summary="List Event Types",
        description=(
            "Retrieve a paginated list of all event types available in the system. "
            "Event types categorize events by their nature such as conferences, workshops, retreats, seminars, etc. "
            "Supports search functionality by title, code, and description for easy discovery."
        ),
        tags=["Event Types"],
        parameters=[
            OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search by title or code'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Type Details",
        description=(
            "Retrieve comprehensive information about a specific event type including "
            "title, code, description, and associated metadata for categorizing events."
        ),
        tags=["Event Types"],
    ),
    create=extend_schema(
        summary="Create Event Type",
        description=(
            "Create a new event type category for organizing and categorizing events. "
            "Event types help users filter and understand the nature of events. "
            "Requires authentication and appropriate permissions."
        ),
        tags=["Event Types"],
    ),
    update=extend_schema(
        summary="Update Event Type",
        description=(
            "Update all fields of an existing event type. Requires complete payload. "
            "Use PATCH for partial updates."
        ),
        tags=["Event Types"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Type",
        description="Partially update an event type without providing complete payload.",
        tags=["Event Types"],
    ),
    destroy=extend_schema(
        summary="Delete Event Type",
        description=(
            "Delete an event type category. Use with caution if events are associated with this type."
        ),
        tags=["Event Types"],
    )
)
class EventTypeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Event Types.
    
    Event types categorize events and help users filter and discover events by their nature.
    Supports CRUD operations with search and ordering capabilities.
    """
    queryset = EventType.objects.all()
    serializer_class = EventTypeSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'code', 'description']
    ordering_fields = ['title', 'created_at']
    ordering = ['-created_at']


@extend_schema_view(
    list=extend_schema(
        summary="List Events",
        description=(
            "Retrieve a paginated list of all events with comprehensive filtering and search capabilities. "
            "Results include event details, status, type, organization, dates, and registration information. "
            "Non-staff users only see published and active events, while staff can view all events including drafts. "
            "Supports filtering by status, event type, organization, and text search across titles and descriptions."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='status', type=OpenApiTypes.STR, description='Filter by status (DRAFT, PUBLISHED, OPEN, etc.)'),
            OpenApiParameter(name='event_type', type=OpenApiTypes.INT, description='Filter by event type ID'),
            OpenApiParameter(name='organisation', type=OpenApiTypes.INT, description='Filter by organisation ID'),
            OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search by title or description'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Details",
        description=(
            "Retrieve comprehensive details about a specific event including all metadata, dates, "
            "registration information, settings, staff, resources, reviews, and associated content. "
            "Includes HATEOAS links for related resources and nested endpoints."
        ),
        tags=["Events"],
    ),
    create=extend_schema(
        summary="Create Event",
        description=(
            "Create a new event with complete information including title, dates, location, type, and settings. "
            "Automatically assigns the authenticated user as the event creator. "
            "Creates associated event settings and generates unique display code for identification."
        ),
        tags=["Events"],
    ),
    update=extend_schema(
        summary="Update Event",
        description=(
            "Update all fields of an existing event. Requires complete payload with all fields. "
            "Use PATCH for partial updates. Only event creators and staff can update events."
        ),
        tags=["Events"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event",
        description=(
            "Partially update an event without providing complete payload. "
            "Allows updating individual fields like dates, description, or status. "
            "Only event creators and staff can update events."
        ),
        tags=["Events"],
    ),
    destroy=extend_schema(
        summary="Delete Event",
        description=(
            "Soft delete an event by marking it as deleted without permanent removal. "
            "Soft-deleted events are hidden from public view but retained for audit purposes. "
            "Only event creators and staff can delete events."
        ),
        tags=["Events"],
    )
)
class EventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for comprehensive event management with CRUD operations and extensive custom actions.
    
    Provides full event lifecycle management including:
    - Event creation, editing, and soft deletion
    - Staff management and assignments
    - Resource and media management (images, documents, links)
    - Availability window configuration
    - Permission and role assignments
    - Reviews and ratings
    - Advanced filtering, search, and ordering
    
    Custom Actions:
        - upcoming: List upcoming events
        - ongoing: List currently active events
        - event_settings: Get event settings
        - add_staff / remove_staff / staff_list: Manage event staff
        - soft_delete_event / restore_event: Soft delete operations
        - availability_windows: Manage availability windows
        - resources / add_resource / update_resource / remove_resource: Resource management
        - landing_images / add_landing_image / promote_landing_image / demote_landing_image: Landing page image management
        - assign_permission: Assign permissions to users
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'event_type', 'organisation']
    search_fields = ['title', 'short_description', 'long_description', 'display_code']
    ordering_fields = ['title', 'start_datetime', 'created_at']
    ordering = ['-start_datetime']
    lookup_field = 'url_safe_title'
    
    def get_queryset(self):
        queryset = Event.objects.select_related(
            'event_type', 'organisation', 'created_by'
        ).prefetch_related('settings')
      
        # # return events that the user is involved in
        # if self.request.user.is_authenticated:
        #     queryset = queryset.filter(
        #         Q(created_by=self.request.user) |
        #         Q(staff_members__user=self.request.user)
        #     ).distinct()
        # else:
        #     print(queryset)
        #     queryset = queryset.filter(status__in=[
        #         EventStatusChoices.PUBLISHED,
        #         EventStatusChoices.OPEN,
        #         EventStatusChoices.POSTPONED,
        #         EventStatusChoices.IN_PROGRESS,
        #         EventStatusChoices.COMPLETED
        #     ])

        # users that are involved in events should be able to see there own events, otherwise, show only public facing statuses to non staff users
        if self.request.user.is_authenticated and not self.request.user.is_staff:
            queryset = queryset.filter(
                Q(created_by=self.request.user) |
                Q(staff_members__user=self.request.user) |
                Q(status__in=[
                    EventStatusChoices.PUBLISHED,
                    EventStatusChoices.OPEN,
                    EventStatusChoices.POSTPONED,
                    EventStatusChoices.IN_PROGRESS,
                    EventStatusChoices.COMPLETED
                ])
            ).distinct()
        elif not self.request.user.is_authenticated:
            queryset = queryset.filter(status__in=[
                EventStatusChoices.PUBLISHED,
                EventStatusChoices.OPEN,
                EventStatusChoices.POSTPONED,
                EventStatusChoices.IN_PROGRESS,
                EventStatusChoices.COMPLETED
            ])
        
        
        return queryset
    
    def get_serializer_class(self):
        if self.action == 'list':
            return EventListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventCreateUpdateSerializer
        return EventDetailSerializer
    
    def perform_destroy(self, instance):
        return instance.soft_delete()
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @extend_schema(
        summary="Get Upcoming Events",
        description=(
            "Retrieve all upcoming events that haven't started yet, ordered by start date. "
            "Useful for displaying future events on calendars and event listings. "
            "Includes pagination support for large result sets."
        ),
        tags=["Events"],
        responses={
            200: EventListSerializer(many=True),
        },
        parameters=[
            OpenApiParameter(name='page', type=OpenApiTypes.INT, description='Page number'),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, description='Number of results per page'),
        ]
    )
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        from django.utils import timezone
        queryset = self.get_queryset().filter(start_datetime__gte=timezone.now())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EventListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = EventListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Get Ongoing Events",
        description=(
            "Retrieve all currently active/ongoing events that have started but not yet ended. "
            "Perfect for displaying 'happening now' events and real-time event monitoring. "
            "Filters events where current time is between start and end datetime."
        ),
        tags=["Events"],
        responses={
            200: EventListSerializer(many=True),
        },
        parameters=[
            OpenApiParameter(name='page', type=OpenApiTypes.INT, description='Page number'),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, description='Number of results per page'),
        ]
    )
    @action(detail=False, methods=['get'])
    def ongoing(self, request):
        from django.utils import timezone
        now = timezone.now()
        queryset = self.get_queryset().filter(
            start_datetime__lte=now,
            end_datetime__gte=now
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EventListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = EventListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Get Current User Bookings For Event (Paginated)",
        description=(
            "Retrieve all of the current authenticated user's bookings for this event with "
            "pagination and filtering support. Results include attendees, tickets, and payments. "
            "Selection precedence is: bookings created by current user first, then bookings "
            "where user is linked as an attendee. Supports filtering by outstanding payments, "
            "booking dates, attendee names, and more. Uses OR logic for combining filters."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name='has_outstanding_payments',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter by outstanding payment status (true/false)'
            ),
            OpenApiParameter(
                name='booked_after',
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                description='Filter bookings made after this date (ISO 8601 format)'
            ),
            OpenApiParameter(
                name='booked_before',
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                description='Filter bookings made before this date (ISO 8601 format)'
            ),
            OpenApiParameter(
                name='booked_in_days',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Filter bookings from last N days (e.g., 7, 30, 90)'
            ),
            OpenApiParameter(
                name='attendee_name',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by attendee name (first or last, case-insensitive)'
            ),
            OpenApiParameter(
                name='booking_reference',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by booking reference (contains, case-insensitive)'
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Page number (defaults to 1, 20 results per page)'
            ),
        ],
        responses={
            200: OpenApiResponse(description='Paginated list of user bookings'),
            401: OpenApiResponse(description='Authentication required'),
            404: OpenApiResponse(description='Event not found'),
        }
    )
    @action(
        detail=True,
        methods=['get'],
        url_path='my-booking',
        permission_classes=[permissions.IsAuthenticated],
    )
    def my_booking(self, request, *args, **kwargs):
        """Get all user's bookings for an event with pagination and filtering."""
        event = self.get_object()

        # Query all bookings where user is owner or attendee
        base_queryset = Booking.objects.filter(
            event=event,
        ).filter(
            Q(made_by=request.user) | Q(attendees__user=request.user)
        ).select_related(
            'event',
            'made_by',
        ).prefetch_related(
            'attendees__tickets',
            'attendees__user',
        ).distinct().order_by('-booked_at', '-id')

        # Apply filters
        filterset = EventMyBookingFilterSet(
            request.GET,
            queryset=base_queryset,
            request=request
        )
        filtered_queryset = filterset.qs

        # Apply pagination
        paginator = StandardPagination()
        paginated_queryset = paginator.paginate_queryset(
            filtered_queryset,
            request
        )

        if paginated_queryset is None:
            paginated_queryset = filtered_queryset

        booking_items = []
        for booking in paginated_queryset:
            is_owner = booking.made_by_id == request.user.id
            booking_items.append(
                {
                    'booking': booking,
                    'is_booking_owner': is_owner,
                    'selection_reason': 'made_by' if is_owner else 'attendee_linked',
                    'can_manage_all_attendees': is_owner,
                }
            )

        serializer = EventMyBookingResponseSerializer(
            {
                'event': event,
                'primary_booking_reference': paginated_queryset[0].booking_reference if paginated_queryset else None,
                'bookings': booking_items,
            },
            context={'request': request, 'event': event},
        )
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Get Outstanding Booking Payments",
        description=(
            "Retrieve all outstanding (unpaid) payment records for the current authenticated user "
            "in this event. Outstanding payments include both payments linked to existing bookings "
            "and payments with pending checkout intents (bookings not yet created). "
            "Supports pagination and comprehensive filtering by payment status, booking dates, "
            "attendee names, and more. Uses OR logic for combining filters to show broader results."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name='payment_status',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by payment status (PENDING, DRAFTING, etc.)'
            ),
            OpenApiParameter(
                name='booked_after',
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                description='Filter payments for bookings made after this date (ISO 8601 format)'
            ),
            OpenApiParameter(
                name='booked_before',
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                description='Filter payments for bookings made before this date (ISO 8601 format)'
            ),
            OpenApiParameter(
                name='booked_in_days',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Filter payments for bookings from last N days (e.g., 7, 30, 90)'
            ),
            OpenApiParameter(
                name='attendee_name',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by attendee name in associated booking (first or last, case-insensitive)'
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Page number (defaults to 1, 20 results per page)'
            ),
        ],
        responses={
            200: OpenApiResponse(description='Paginated list of outstanding payments'),
            401: OpenApiResponse(description='Authentication required'),
            404: OpenApiResponse(description='Event not found'),
        }
    )
    @action(
        detail=True,
        methods=['get'],
        url_path='my-outstanding-booking-payments',
        permission_classes=[permissions.IsAuthenticated],
    )
    def my_outstanding_booking_payments(self, request, url_safe_title=None):
        """Get all outstanding (unpaid) payments for an event with pagination and filtering."""
        event = self.get_object()

        # Get outstanding payments using the service
        outstanding_qs = OutstandingPaymentsService.get_user_outstanding_payments_with_validation(
            request.user, event
        )

        # Sort by created_at descending (most recent first)
        outstanding_qs = outstanding_qs.order_by('-created_at')

        # Apply filters
        filterset = EventMyOutstandingPaymentsFilterSet(
            request.GET,
            queryset=outstanding_qs,
            request=request
        )
        filtered_queryset = filterset.qs

        # Apply pagination
        paginator = StandardPagination()
        paginated_queryset = paginator.paginate_queryset(
            filtered_queryset,
            request
        )

        if paginated_queryset is None:
            paginated_queryset = filtered_queryset

        # Serialize payments with their associated bookings
        serializer = EventMyOutstandingPaymentSerializer(
            paginated_queryset,
            many=True,
            context={'request': request, 'event': event},
        )

        # Return paginated response
        return paginator.get_paginated_response(serializer.data)

    def _serialize_payment_summary_item(self, payment, source, order=None, attendee=None):
        amount = None
        currency = None
        if getattr(payment, 'base_amount', None):
            amount = str(payment.base_amount)
            currency = str(payment.base_amount.currency)

        method = getattr(payment, 'method', None)
        descriptor = payment.target_type.model if getattr(payment, 'target_type', None) else None

        return {
            'payment_id': payment.payment_id,
            'payment_reference': payment.payment_reference,
            'status': payment.status,
            'amount': amount,
            'currency': currency,
            'created_at': payment.created_at,
            'method_type': getattr(method, 'method_type', None),
            'method_title': getattr(method, 'title', None),
            'provided_details': getattr(method, 'provided_details', None),
            'bank_reference': payment.bank_transfer_reference,
            'source': source,
            'is_outstanding': payment.status in [
                PaymentStatusChoices.DRAFTING,
                PaymentStatusChoices.PENDING,
            ],
            'descriptor': descriptor,
            'order_id': getattr(order, 'order_id', None),
            'order_reference': getattr(order, 'order_reference_id', None),
            'order_status': getattr(order, 'status', None),
            'attendee_id': getattr(attendee, 'attendee_id', None),
            'attendee_display_id': getattr(attendee, 'attendee_display_id', None),
            'attendee_name': getattr(attendee, 'full_name', None),
        }

    @extend_schema(
        summary='Get Unified Payment Summary For Current User Booking',
        description=(
            'Retrieve a unified booking payment summary for the current authenticated user, '
            'including booking-level payments and shop/order payments for attendees in the booking. '
            'Supports optional attendee filtering to focus attendee-specific payments while still '
            'returning booking-wide payment context.'
        ),
        tags=['Events'],
        parameters=[
            OpenApiParameter(
                name='booking_reference',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional booking reference to target a specific booking within this event.'
            ),
            OpenApiParameter(
                name='attendee_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional attendee UUID filter for attendee-specific payment section.'
            ),
        ],
        responses={
            200: EventMyPaymentSummarySerializer,
            401: OpenApiResponse(description='Authentication required'),
            404: OpenApiResponse(description='Event or booking not found'),
        }
    )
    @action(
        detail=True,
        methods=['get'],
        url_path='my-payment-summary',
        permission_classes=[permissions.IsAuthenticated],
    )
    def my_payment_summary(self, request, url_safe_title=None):
        event = self.get_object()

        bookings_qs = Booking.objects.filter(event=event).filter(
            Q(made_by=request.user) | Q(attendees__user=request.user)
        ).distinct().order_by('-booked_at', '-id')

        booking_reference = request.query_params.get('booking_reference')
        if booking_reference:
            bookings_qs = bookings_qs.filter(booking_reference=booking_reference)

        booking = bookings_qs.first()
        if not booking:
            return Response(
                {'detail': 'Booking not found for this event.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        attendee_filter = request.query_params.get('attendee_id')
        # test if the attendee id is a uuid, if not, fetch the attendee id 
        if attendee_filter:
            try:
                uuid.UUID(attendee_filter)  


            except ValueError:
                # expected firstname-lastname attempt to parse

                try:
                    first_name, last_name = attendee_filter.split('-')
                except ValueError:
                    return Response(
                        {'detail': 'Invalid attendee_id format. Must be UUID or first-last name separated by hyphen.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                
                attendee = booking.attendees.filter(
                    Q(user__first_name__iexact=first_name, user__last_name__iexact=last_name) |
                    Q(attendee_display_id=attendee_filter)
                ).first()
                if attendee:
                    attendee_filter = str(attendee.attendee_id)
                else:
                    return Response(
                        {'detail': 'Attendee not found for this booking.'},
                        status=status.HTTP_404_NOT_FOUND,
                    )

        booking_attendees = booking.attendees.filter(event=event)

        booking_payments_qs = booking.payments.select_related('method', 'target_type').order_by('-created_at')

        order_qs = Order.objects.filter(
            attendee__booking=booking,
            attendee__event=event,
            payment__isnull=False,
        ).select_related('payment__method', 'payment__target_type', 'attendee').order_by('-created_at')

        if attendee_filter:
            order_qs = order_qs.filter(attendee__attendee_id=attendee_filter)

        booking_payment_items = [
            self._serialize_payment_summary_item(payment=payment, source='BOOKING')
            for payment in booking_payments_qs
        ]

        shop_payment_items = [
            self._serialize_payment_summary_item(
                payment=order.payment,
                source='SHOP_ORDER',
                order=order,
                attendee=order.attendee,
            )
            for order in order_qs
            if order.payment is not None
        ]

        attendee_payment_items = shop_payment_items
        if not attendee_filter:
            attendee_ids = set(booking_attendees.values_list('attendee_id', flat=True))
            attendee_payment_items = [
                item for item in shop_payment_items
                if item.get('attendee_id') in attendee_ids
            ]

        all_items = booking_payment_items + shop_payment_items
        outstanding_items = [item for item in all_items if item.get('is_outstanding')]

        outstanding_total = Decimal('0.00')
        for item in outstanding_items:
            amount = str(item.get('amount') or '')
            try:
                outstanding_total += Decimal(amount.split(' ')[0])
            except Exception:
                continue

        booking_outstanding = len([
            item for item in booking_payment_items if item.get('is_outstanding')
        ])
        shop_outstanding = len([
            item for item in shop_payment_items if item.get('is_outstanding')
        ])

        payload = {
            'booking_reference': booking.booking_reference,
            'attendee_filter': attendee_filter,
            'totals': {
                'total_payments': len(all_items),
                'outstanding_payments': len(outstanding_items),
                'booking_outstanding_payments': booking_outstanding,
                'shop_outstanding_payments': shop_outstanding,
                'total_outstanding_amount': f'{outstanding_total:.2f}',
            },
            'booking_payments': booking_payment_items,
            'shop_payments': shop_payment_items,
            'attendee_payments': attendee_payment_items,
            'outstanding_payments': outstanding_items,
        }

        serializer = EventMyPaymentSummarySerializer(payload, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Get sponsorable events",
        description=(
            "Retrieve events available for sponsorship checkout. "
            "Results are limited to events with sponsorships enabled and at least one active sponsorship package."
        ),
        tags=["Events"],
        responses={200: SponsorableEventListSerializer(many=True)},
        parameters=[
            OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search by title, description, or display code.'),
            OpenApiParameter(name='page', type=OpenApiTypes.INT, description='Page number.'),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, description='Number of results per page.'),
        ],
    )
    @action(detail=False, methods=['get'], url_path='sponsorable')
    def sponsorable(self, request):
        queryset = self.get_queryset().filter(
            settings__accepting_sponsorships_enabled=True,
            sponsorship_packages__active=True,
        ).annotate(
            active_sponsorship_packages_count=Count(
                'sponsorship_packages',
                filter=Q(sponsorship_packages__active=True),
                distinct=True,
            )
        ).distinct()

        search_value = request.query_params.get('search')
        if search_value:
            queryset = queryset.filter(
                Q(title__icontains=search_value)
                | Q(short_description__icontains=search_value)
                | Q(long_description__icontains=search_value)
                | Q(display_code__icontains=search_value)
            )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = SponsorableEventListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = SponsorableEventListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Get Event Settings",
        description=(
            "Retrieve configuration settings for a specific event including product selling options, "
            "order approval requirements, booking configuration, and other event-specific preferences."
        ),
        tags=["Events"],
        responses={
            200: EventSettingsSerializer,
            404: OpenApiResponse(description='Settings not found for this event'),
        }
    )
    @action(detail=True, methods=['get'], url_path='settings')
    def event_settings(self, request, url_safe_title=None):
        event = self.get_object()
        event_settings = getattr(event, 'settings', None)
        if not event_settings:
            return Response(
                {"detail": "Settings not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = EventSettingsSerializer(event_settings)
        return Response(serializer.data)

    def _is_event_admin(self, user, event) -> bool:
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return EventRoleAssignment.objects.filter(
            user=user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).exists()

    def _can_manage_sponsor_for_organisation(self, user, event, organisation) -> bool:
        if self._is_event_admin(user, event):
            return True
        return OrganisationControl.objects.filter(
            user=user,
            organisation=organisation,
        ).exists()

    @extend_schema(
        summary="Event Sponsors",
        description="List sponsors for an event or create a sponsor for the event.",
        tags=["Events", "Event Sponsors"],
    )
    @extend_schema(methods=['get'], operation_id='event_list_sponsors_list')
    @extend_schema(methods=['post'], operation_id='event_list_sponsors_create')
    @action(detail=True, methods=['get', 'post'], url_path='sponsors', permission_classes=[permissions.IsAuthenticated])
    def sponsors(self, request, url_safe_title=None):
        event = self.get_object()
        queryset = EventSponsor.objects.select_related(
            'organisation', 'event', 'package', 'added_by', 'verified_by', 'processed_by'
        ).filter(event=event)

        if request.method == 'GET':
            page = self.paginate_queryset(queryset)
            serializer = EventSponsorListSerializer(
                page if page is not None else queryset,
                many=True,
                context={'request': request},
            )
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        payload = request.data.copy()
        payload.setdefault('event', event.id)

        serializer = EventSponsorCreateUpdateSerializer(
            data=payload,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)

        organisation = serializer.validated_data.get('organisation')
        if not organisation:
            return Response({'organisation_id': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)

        if not self._can_manage_sponsor_for_organisation(request.user, event, organisation):
            return Response(
                {'detail': "You don't have permission to create a sponsor for this organisation."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if serializer.validated_data.get('event') != event:
            return Response(
                {'event_id': ['Event in payload must match URL event_id.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sponsor = serializer.save()
        return Response(
            EventSponsorDetailSerializer(sponsor, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Event Sponsor Detail",
        description="Retrieve, update, or delete a sponsor within an event context.",
        parameters=[
            OpenApiParameter(name='sponsor_id', type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, required=True),
        ],
        tags=["Events", "Event Sponsors"],
    )
    @extend_schema(methods=['get'], operation_id='event_list_sponsors_retrieve')
    @extend_schema(methods=['patch'], operation_id='event_list_sponsors_partial_update')
    @extend_schema(methods=['delete'], operation_id='event_list_sponsors_destroy')
    @action(
        detail=True,
        methods=['get', 'patch', 'delete'],
        url_path='sponsors/(?P<sponsor_id>[^/.]+)',
        permission_classes=[permissions.IsAuthenticated],
    )
    def sponsor_detail(self, request, url_safe_title=None, sponsor_id=None):
        event = self.get_object()
        sponsor = get_object_or_404(
            EventSponsor.objects.select_related('organisation', 'event', 'package', 'added_by', 'verified_by', 'processed_by'),
            sponsor_id=sponsor_id,
            event=event,
        )

        if request.method == 'GET':
            serializer = EventSponsorDetailSerializer(sponsor, context={'request': request})
            return Response(serializer.data)

        if not self._can_manage_sponsor_for_organisation(request.user, event, sponsor.organisation):
            return Response(
                {'detail': "You don't have permission to manage this sponsor."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'DELETE':
            sponsor.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        payload = request.data.copy()
        payload.setdefault('event', event.id)

        serializer = EventSponsorCreateUpdateSerializer(
            sponsor,
            data=payload,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)

        payload_event = serializer.validated_data.get('event')
        if payload_event and payload_event != event:
            return Response(
                {'event_id': ['Event in payload must match URL event_id.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sponsor = serializer.save()
        return Response(EventSponsorDetailSerializer(sponsor, context={'request': request}).data)

    @extend_schema(
        summary="Approve Event Sponsor",
        description="Mark a sponsor as verified. Event admin permissions required.",
        parameters=[
            OpenApiParameter(name='sponsor_id', type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, required=True),
        ],
        operation_id='event_list_sponsors_approve',
        tags=["Events", "Event Sponsors"],
    )
    @action(
        detail=True,
        methods=['post'],
        url_path='sponsors/(?P<sponsor_id>[^/.]+)/approve',
        permission_classes=[permissions.IsAuthenticated],
    )
    def approve_sponsor(self, request, url_safe_title=None, sponsor_id=None):
        event = self.get_object()
        if not self._is_event_admin(request.user, event):
            return Response(
                {'detail': "Only event admins can approve sponsors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        sponsor = get_object_or_404(
            EventSponsor.objects.select_related('organisation', 'event', 'package', 'added_by', 'verified_by', 'processed_by'),
            sponsor_id=sponsor_id,
            event=event,
        )
        sponsor.mark_verified(verifier=request.user)
        serializer = EventSponsorDetailSerializer(sponsor, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Reject Event Sponsor",
        description="Mark a sponsor as rejected. Event admin permissions required.",
        parameters=[
            OpenApiParameter(name='sponsor_id', type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, required=True),
        ],
        operation_id='event_list_sponsors_reject',
        tags=["Events", "Event Sponsors"],
    )
    @action(
        detail=True,
        methods=['post'],
        url_path='sponsors/(?P<sponsor_id>[^/.]+)/reject',
        permission_classes=[permissions.IsAuthenticated],
    )
    def reject_sponsor(self, request, url_safe_title=None, sponsor_id=None):
        event = self.get_object()
        if not self._is_event_admin(request.user, event):
            return Response(
                {'detail': "Only event admins can reject sponsors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        sponsor = get_object_or_404(
            EventSponsor.objects.select_related('organisation', 'event', 'package', 'added_by', 'verified_by', 'processed_by'),
            sponsor_id=sponsor_id,
            event=event,
        )
        sponsor.mark_rejected(verifier=request.user)
        serializer = EventSponsorDetailSerializer(sponsor, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Event Sponsorship Packages",
        description="List or create sponsor packages for an event.",
        tags=["Events", "Sponsorship Packages"],
    )
    @extend_schema(methods=['get'], operation_id='event_list_sponsorship_packages_list')
    @extend_schema(methods=['post'], operation_id='event_list_sponsorship_packages_create')
    @action(detail=True, methods=['get', 'post'], url_path='sponsorship-packages', permission_classes=[permissions.IsAuthenticated])
    def sponsorship_packages(self, request, url_safe_title=None):
        event = self.get_object()

        if request.method == 'GET':
            queryset = EventSponsorPackage.objects.select_related('event').filter(event=event)
            page = self.paginate_queryset(queryset)
            serializer = EventSponsorPackageListSerializer(
                page if page is not None else queryset,
                many=True,
                context={'request': request},
            )
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        if not self._is_event_admin(request.user, event):
            return Response(
                {'detail': "Only event admins can create sponsorship packages."},
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = request.data.copy()
        payload.setdefault('event', event.id)
        serializer = EventSponsorPackageCreateUpdateSerializer(data=payload, context={'request': request})
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get('event') != event:
            return Response(
                {'event_id': ['Event in payload must match URL event_id.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        package = serializer.save()
        return Response(
            EventSponsorPackageDetailSerializer(package, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Event Sponsorship Package Detail",
        description="Retrieve, update, or delete a sponsorship package for an event.",
        parameters=[
            OpenApiParameter(name='package_id', type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, required=True),
        ],
        tags=["Events", "Sponsorship Packages"],
    )
    @extend_schema(methods=['get'], operation_id='event_list_sponsorship_packages_retrieve')
    @extend_schema(methods=['patch'], operation_id='event_list_sponsorship_packages_partial_update')
    @extend_schema(methods=['delete'], operation_id='event_list_sponsorship_packages_destroy')
    @action(
        detail=True,
        methods=['get', 'patch', 'delete'],
        url_path='sponsorship-packages/(?P<package_id>[^/.]+)',
        permission_classes=[permissions.IsAuthenticated],
    )
    def sponsorship_package_detail(self, request, url_safe_title=None, package_id=None):
        event = self.get_object()
        package = get_object_or_404(
            EventSponsorPackage.objects.select_related('event'),
            package_id=package_id,
            event=event,
        )

        if request.method == 'GET':
            serializer = EventSponsorPackageDetailSerializer(package, context={'request': request})
            return Response(serializer.data)

        if not self._is_event_admin(request.user, event):
            return Response(
                {'detail': "Only event admins can modify sponsorship packages."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'DELETE':
            if package.payment is not None:
                return Response(
                    {'detail': 'Cannot delete a package that already has an associated payment.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            package.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        payload = request.data.copy()
        payload.setdefault('event', event.id)

        serializer = EventSponsorPackageCreateUpdateSerializer(
            package,
            data=payload,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        payload_event = serializer.validated_data.get('event')
        if payload_event and payload_event != event:
            return Response(
                {'event_id': ['Event in payload must match URL event_id.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        package = serializer.save()
        return Response(EventSponsorPackageDetailSerializer(package, context={'request': request}).data)

    @extend_schema(
        summary="Public Event Sponsors",
        description="List approved sponsors visible on the event landing page.",
        tags=["Events", "Event Sponsors"],
    )
    @action(detail=True, methods=['get'], url_path='public-sponsors', permission_classes=[permissions.AllowAny])
    def public_sponsors(self, request, url_safe_title=None):
        event = self.get_object()
        queryset = EventSponsor.objects.select_related('organisation', 'event', 'package').filter(
            event=event,
            approval_status='APPROVED',
            show_on_landing=True,
        )
        serializer = EventSponsorListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Add Staff to Event",
        description=(
            "Add a user as a staff member to the event with optional notes. "
            "Creates an EventStaff instance linking the user to the event. "
            "Only event creators, staff, and superusers can add staff members. "
            "Returns validation error if user is already a staff member."
        ),
        tags=["Events"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'User ID to add as staff'},
                    'notes': {'type': 'string', 'description': 'Optional notes about the staff member'}
                },
                'required': ['user_id']
            }
        },
        responses={
            201: EventStaffSerializer,
            400: OpenApiResponse(description='Bad request - validation errors'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='User not found')
        }
    )
    @action(detail=True, methods=['post'], url_path='add-staff', permission_classes=[permissions.IsAuthenticated])
    def add_staff(self, request, url_safe_title=None):
        from django.contrib.auth import get_user_model
        
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to add staff to this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        notes = request.data.get('notes', '')
        
        if not user_id:
            return Response(
                {"detail": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if already staff
        if EventStaff.objects.filter(event=event, user=user).exists():
            return Response(
                {"detail": "User is already a staff member of this event"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        staff_member = EventStaff.objects.create(
            event=event,
            user=user,
            assigned_by=request.user,
            notes=notes
        )
        
        serializer = EventStaffSerializer(staff_member)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Remove Staff from Event",
        description=(
            "Remove a staff member from an event by their staff ID. "
            "Permanently deletes the EventStaff instance. "
            "Only event creators, staff, and superusers can remove staff members. "
            "Requires staff_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='staff_id', type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY, 
                           description='Staff member ID to remove', required=True)
        ],
        responses={
            204: OpenApiResponse(description='Staff member removed successfully'),
            400: OpenApiResponse(description='Bad request - staff_id required'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Staff member not found')
        }
    )
    @action(detail=True, methods=['delete'], url_path='remove-staff', permission_classes=[permissions.IsAuthenticated])
    def remove_staff(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to remove staff from this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        staff_id = request.query_params.get('staff_id')
        if not staff_id:
            return Response(
                {"detail": "staff_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            staff_member = EventStaff.objects.get(staff_id=staff_id, event=event)
        except EventStaff.DoesNotExist:
            return Response(
                {"detail": "Staff member not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )

        if staff_member.user_id == event.created_by_id:
            return Response(
                {"detail": CannotTargetEventCreator.message},
                status=status.HTTP_403_FORBIDDEN
            )
        
        staff_member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @extend_schema(
        summary="List Event Staff",
        description=(
            "Retrieve a complete list of all staff members assigned to the event. "
            "Includes user details, assignment information, and associated notes. "
            "Automatically includes related user and assigned_by data for efficient queries."
        ),
        tags=["Events"],
        responses={
            200: EventStaffSerializer(many=True),
        }
    )
    @action(detail=True, methods=['get'], url_path='staff-list')
    def staff_list(self, request, url_safe_title=None):
        event = self.get_object()
        staff_members = event.staff_members.select_related('user', 'assigned_by').all()
        serializer = EventStaffSerializer(staff_members, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Soft Delete Event",
        description=(
            "Soft delete an event by marking it as deleted without permanent removal. "
            "Records the user who performed the deletion and timestamp. "
            "Soft-deleted events can be restored later using the restore endpoint. "
            "Only event creators, staff, and superusers can soft delete events."
        ),
        tags=["Events"],
        responses={
            200: OpenApiResponse(description='Event soft deleted successfully'),
            400: OpenApiResponse(description='Event is already deleted'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(detail=True, methods=['post'], url_path='soft-delete', permission_classes=[permissions.IsAuthenticated])
    def soft_delete_event(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to delete this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            event.soft_delete()
            event.deleted_by = request.user
            event.save(update_fields=['deleted_by'])
            return Response(
                {"detail": "Event soft deleted successfully", "deleted_at": event.deleted_at.isoformat() if event.deleted_at else None},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @extend_schema(
        summary="Restore Soft-Deleted Event",
        description=(
            "Restore a previously soft-deleted event back to active status. "
            "Clears the deletion timestamp and deleted_by field. "
            "Makes the event visible and accessible again in all listings. "
            "Only event creators, staff, and superusers can restore events."
        ),
        tags=["Events"],
        responses={
            200: OpenApiResponse(description='Event restored successfully'),
            400: OpenApiResponse(description='Event is not deleted'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(detail=True, methods=['post'], url_path='restore', permission_classes=[permissions.IsAuthenticated])
    def restore_event(self, request, url_safe_title=None):
        event = Event.all_objects.get(url_safe_title=url_safe_title)
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to restore this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            event.restore()
            event.deleted_by = None
            event.save(update_fields=['deleted_by'])
            return Response(
                {"detail": "Event restored successfully"},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @extend_schema(
        summary="List Availability Windows",
        description=(
            "Retrieve all availability windows configured for the event. "
            "Availability windows define time slots when the event is open for registrations or bookings. "
            "Used for scheduling and capacity management."
        ),
        tags=["Events"],
        responses={
            200: AvailabilityWindowSerializer(many=True),
        }
    )
    @action(detail=True, methods=['get'], url_path='availability-windows')
    def availability_windows(self, request, url_safe_title=None):
        event = self.get_object()
        windows = event.extended_availability_windows.all()

        # TODO: get related products, packages 


        paginated = self.paginate_queryset(windows)
        if paginated is not None:
            serializer = AvailabilityWindowSerializer(paginated, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = AvailabilityWindowSerializer(windows, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Add Availability Window",
        description=(
            "Add a new availability window to the event defining when registrations are open. "
            "Specify start and end times, capacity limits, and other scheduling constraints. "
            "Only event creators, staff, and superusers can add availability windows."
        ),
        tags=["Events"],
        request=AvailabilityWindowSerializer,
        responses={
            201: AvailabilityWindowSerializer,
            400: OpenApiResponse(description='Validation errors'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(detail=True, methods=['post'], url_path='add-availability-window', permission_classes=[permissions.IsAuthenticated])
    def add_availability_window(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to add availability windows to this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = AvailabilityWindowSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(Event)
            window = serializer.save(
                target_type=content_type,
                target_id=event.id
            )
            return Response(
                AvailabilityWindowSerializer(window, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Remove Availability Window",
        description=(
            "Remove an availability window from the event by its window ID. "
            "Permanently deletes the window and affects event scheduling. "
            "Only event creators, staff, and superusers can remove availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='window_id', type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY,
                           description='Availability window ID to remove', required=True)
        ],
        responses={
            204: OpenApiResponse(description='Window removed successfully'),
            400: OpenApiResponse(description='Bad request'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Window not found')
        }
    )
    @action(detail=True, methods=['delete'], url_path='remove-availability-window', permission_classes=[permissions.IsAuthenticated])
    def remove_availability_window(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to remove availability windows from this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        window_id = request.query_params.get('window_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            window = AvailabilityWindow.objects.get(availability_id=window_id, target_id=event.id)
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        window.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @extend_schema(
        summary="Update Availability Window",
        description=(
            "Update an existing availability window for the event. "
            "Allows partial updates (PATCH) or full updates (PUT) of availability window properties. "
            "Only event creators, staff, and superusers can update availability windows. "
            "The window_id can be provided as a query parameter or in the request body as 'availability_id'. "
            "Validates that the window belongs to this event before updating."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to update (UUID). Can also be provided in request body as availability_id.',
                required=False
            )
        ],
        request=AvailabilityWindowSerializer,
        responses={
            200: AvailabilityWindowSerializer,
            400: OpenApiResponse(description='Invalid data or missing window_id'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Window not found for this event')
        }
    )
    @action(detail=True, methods=['patch', 'put'], url_path='update-availability-window', permission_classes=[permissions.IsAuthenticated])
    def update_availability_window(self, request, url_safe_title=None):
        """
        Update an existing availability window for the event.
        
        Allows partial updates (PATCH) or full updates (PUT) of availability windows.
        Only the event creator, staff, or superuser can update windows.
        
        Path Parameters:
        - url_safe_title (string): The URL-safe title of the event
        
        Query Parameters:
        - window_id (UUID, optional): The availability_id of the window to update.
          Can also be provided in the request body as 'availability_id'.
        
        Request Body:
        - name (string, optional): Window name
        - description (string, optional): Window description
        - availability_type (string, optional): Type of availability window
        - available_from (datetime, optional): Start datetime
        - available_to (datetime, optional): End datetime
        - timezone (string, optional): Timezone string
        - availability_id (UUID, optional): Window ID if not in query params
        
        Response Codes:
        - 200: Window updated successfully
        - 400: Invalid data or missing window_id
        - 403: Permission denied
        - 404: Window not found for this event
        
        Example Request:
        PATCH /api/events/{event_id}/update-availability-window/?window_id={uuid}
        {
          "name": "Updated Registration Window",
          "available_to": "2026-03-15T23:59:59Z"
        }
        """
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to update availability windows for this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get window_id from query params or request body
        # availability_id is UUID type, event_id in path is string
        window_id = request.query_params.get('window_id') or request.data.get('availability_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter or availability_id in request body is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Fetch the window and verify it belongs to this event
        try:
            content_type = ContentType.objects.get_for_model(Event)
            window = AvailabilityWindow.objects.get(
                availability_id=window_id,
                target_id=event.id,
                target_type=content_type
            )
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Determine if partial update (PATCH) or full update (PUT)
        partial = request.method == 'PATCH'
        
        # Update the window using the serializer
        serializer = AvailabilityWindowSerializer(
            window,
            data=request.data,
            partial=partial,
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="List Availability Window Templates",
        description=(
            "Retrieve all available templates for creating availability windows. "
            "Includes both system-defined predefined templates and custom templates "
            "created by the user's organization. Templates contain configurations for "
            "creating multiple availability windows with predefined offsets from the event date."
        ),
        tags=["Events", "Availability Windows"],
        responses={
            200: AvailabilityWindowTemplateSerializer(many=True),
        }
    )
    @action(detail=False, methods=['get'], url_path='availability-templates')
    def availability_templates(self, request):
        """
        List availability window templates.
        
        Returns:
        - Templates created by the current user
        - Predefined templates (is_predefined=True) from the user's organization(s)
        """
        from apps.common.models import AvailabilityWindowTemplate
        from apps.common.api.serializers import AvailabilityWindowTemplateSerializer
        from apps.organisations.models import Organisation
        from django.db.models import Q
        
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get user's organizations
        user_orgs = Organisation.objects.filter(
            memberships__user=request.user
        )
        
        # Filter: (created by user) OR (predefined AND in user's org)
        templates = AvailabilityWindowTemplate.objects.filter(
            Q(created_by=request.user) |  # Templates created by this user
            Q(is_predefined=True, organisation__in=user_orgs)  # Predefined templates from user's orgs
        ).distinct().order_by('-created_at')

        # Paginate results
        paginated = self.paginate_queryset(templates)
        if paginated is not None:
            serializer = AvailabilityWindowTemplateSerializer(paginated, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        

        return Response(serializer.data)
    
    @extend_schema(
        summary="Manage Availability Window Template",
        description=(
            "Update (PATCH) or delete (DELETE) an availability window template. "
            "Only the creator of the template can modify it. Predefined templates cannot be modified. "
            "For updates: only name and description can be changed. Window configurations are immutable."
        ),
        tags=["Events", "Availability Windows"],
        parameters=[
            OpenApiParameter(
                name='template_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='UUID of the template to update or delete',
                required=True
            )
        ],
        request=AvailabilityWindowTemplateSerializer,
        responses={
            200: AvailabilityWindowTemplateSerializer,
            204: {"description": "Template deleted successfully"},
            400: {"description": "Missing or invalid template_id"},
            403: {"description": "Permission denied - not the creator or template is predefined"},
            404: {"description": "Template not found"},
        }
    )
    @action(detail=False, methods=['patch', 'delete'], url_path='availability-templates/manage', url_name='manage-availability-template')
    def manage_availability_template(self, request, **kwargs):
        """
        Update or delete a template based on HTTP method.
        
        PATCH: Update template metadata (name and description only).
        DELETE: Remove the template permanently.
        
        Only the creator can modify. Predefined templates are immutable.
        """
        from apps.common.models import AvailabilityWindowTemplate
        from apps.common.api.serializers import AvailabilityWindowTemplateSerializer
        
        template_id = request.query_params.get('template_id')
        if not template_id:
            return Response(
                {"detail": "template_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            template = AvailabilityWindowTemplate.objects.get(template_id=template_id)
        except AvailabilityWindowTemplate.DoesNotExist:
            return Response(
                {"detail": "Template not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if template is predefined
        if template.is_predefined:
            action = "modified" if request.method == 'PATCH' else "deleted"
            return Response(
                {"detail": f"Predefined templates cannot be {action}"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if user is the creator
        if template.created_by != request.user:
            action = "edit" if request.method == 'PATCH' else "delete"
            return Response(
                {"detail": f"Only the creator can {action} this template"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Handle DELETE method
        if request.method == 'DELETE':
            template.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        # Handle PATCH method
        # Only allow updating name and description
        allowed_fields = {'name', 'description'}
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
        
        serializer = AvailabilityWindowTemplateSerializer(
            template,
            data=update_data,
            partial=True,
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Preview Template Application",
        description=(
            "Preview what availability windows would be created if this template is applied to the event. "
            "Returns a list of windows that would be created with their calculated dates, "
            "plus any conflicts with existing windows."
        ),
        tags=["Events", "Availability Windows"],
        parameters=[
            OpenApiParameter(
                name='template_id',
                type=str,
                location=OpenApiParameter.QUERY,
                description='ID of the template to preview',
                required=True,
            ),
        ],
        responses={
            200: {
                "description": "Preview data with windows and conflicts",
                "type": "object",
                "properties": {
                    "windows": {"type": "array"},
                    "conflicts": {"type": "array"},
                    "has_conflicts": {"type": "boolean"},
                }
            },
            404: {"description": "Event or template not found"},
        }
    )
    @action(detail=True, methods=['get'], url_path='preview-template-application', url_name='preview-template-application')
    def preview_template_application(self, request, url_safe_title=None, **kwargs):
        """
        Preview template application showing what windows would be created and any conflicts.
        """
        from apps.common.models import AvailabilityWindowTemplate, AvailabilityWindow
        from datetime import timedelta
        
        template_id = request.query_params.get('template_id')
        if not template_id:
            return Response(
                {"detail": "template_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get event
        event = self.get_object()
        
        # Get template
        try:
            template = AvailabilityWindowTemplate.objects.get(template_id=template_id)
        except AvailabilityWindowTemplate.DoesNotExist:
            return Response(
                {"detail": "Template not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not event.start_datetime:
            return Response(
                {"detail": "Event must have a start date to apply template"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get existing windows for conflict detection
        existing_windows = AvailabilityWindow.objects.filter(
            availability_type=ContentType.objects.get_for_model(Event),
            target_id=event.event_id
        )
        
        # Calculate what windows would be created
        preview_windows = []
        conflicts = []
        
        for window_config in template.windows_config:
            # Calculate dates
            available_from = event.start_datetime + timedelta(days=window_config['offset_from_event_start'])
            available_to = event.start_datetime + timedelta(days=window_config['offset_to_event_start'])
            
            window_data = {
                'name': window_config.get('name', f"{window_config['availability_type'].replace('_', ' ').title()}"),
                'description': window_config.get('description'),
                'availability_type': window_config['availability_type'],
                'available_from': available_from.isoformat(),
                'available_to': available_to.isoformat(),
            }
            preview_windows.append(window_data)
            
            # Check for conflicts with existing windows
            for existing in existing_windows:
                if not existing.available_from or not existing.available_to:
                    continue
                
                # Check if dates overlap
                if (available_from < existing.available_to and 
                    available_to > existing.available_from):
                    
                    # Same type overlap is more critical
                    is_same_type = existing.availability_type == window_config['availability_type']
                    
                    conflicts.append({
                        'new_window': window_data['name'],
                        'existing_window': existing.name,
                        'conflict_type': 'same_type_overlap' if is_same_type else 'different_type_overlap',
                        'severity': 'high' if is_same_type else 'medium',
                        'message': f"{'Same type ' if is_same_type else ''}Overlap with existing window '{existing.name}'",
                        'existing_window_details': {
                            'name': existing.name,
                            'type': existing.availability_type,
                            'from': existing.available_from.isoformat(),
                            'to': existing.available_to.isoformat(),
                        }
                    })
        
        return Response({
            'windows': preview_windows,
            'conflicts': conflicts,
            'has_conflicts': len(conflicts) > 0,
            'conflict_summary': f"{len(conflicts)} conflict(s) detected" if conflicts else "No conflicts",
        })
    
    @extend_schema(
        summary="Apply Template to Event",
        description=(
            "Apply an availability window template to the event. This will create multiple "
            "availability windows based on the template configuration. Each window's dates "
            "are calculated using offsets from the event start date. This is a convenient "
            "way to set up standard availability windows (registration, payment, refunds, etc.) "
            "without manually creating each one."
        ),
        tags=["Events", "Availability Windows"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'template_id': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'UUID of the template to apply'
                    }
                },
                'required': ['template_id']
            }
        },
        responses={
            201: AvailabilityWindowSerializer(many=True),
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        }
    )
    @action(detail=True, methods=['post'], url_path='apply-availability-template', 
            permission_classes=[permissions.IsAuthenticated], url_name='apply-availability-template')
    def apply_availability_template(self, request, url_safe_title=None, **kwargs):
        """
        Apply a template to create multiple availability windows for the event.
        
        The frontend should call preview-template-application first to check for conflicts.
        This endpoint will apply the template regardless of conflicts.
        """
        from apps.common.models import AvailabilityWindowTemplate, AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowTemplateSerializer, AvailabilityWindowSerializer
        from apps.organisations.models import Organisation
        from datetime import timedelta
        
        event = self.get_object()
        
        # Permission check
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to apply templates to this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        template_id = request.data.get('template_id')
        if not template_id:
            return Response(
                {"detail": "template_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            template = AvailabilityWindowTemplate.objects.get(template_id=template_id)
        except AvailabilityWindowTemplate.DoesNotExist:
            return Response(
                {"detail": "Template not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if template is accessible (created by user OR predefined in user's org)
        from django.db.models import Q
        user_orgs = Organisation.objects.filter(memberships__user=request.user)
        
        is_accessible = (
            template.created_by == request.user or
            (template.is_predefined and template.organisation in user_orgs)
        )
        
        if not is_accessible:
            return Response(
                {"detail": "You don't have access to this template"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check for conflicts before applying
        existing_windows = AvailabilityWindow.objects.filter(
            availability_type=ContentType.objects.get_for_model(Event),
            target_id=event.event_id
        )
        
        conflicts = []
        for window_config in template.windows_config:
            available_from = event.start_datetime + timedelta(days=window_config['offset_from_event_start'])
            available_to = event.start_datetime + timedelta(days=window_config['offset_to_event_start'])
            
            for existing in existing_windows:
                if not existing.available_from or not existing.available_to:
                    continue
                
                if (available_from < existing.available_to and 
                    available_to > existing.available_from):
                    is_same_type = existing.availability_type == window_config['availability_type']
                    conflicts.append({
                        'new_window': window_config.get('name', window_config['availability_type']),
                        'existing_window': existing.name,
                        'same_type': is_same_type,
                    })
        
        # Apply the template
        try:
            created_windows = template.apply_to_event(event, timezone=event.timezone)
            serializer = AvailabilityWindowSerializer(created_windows, many=True, context={'request': request})
            
            response_data = {
                'windows': serializer.data,
                'conflicts_detected': conflicts,
                'message': f"Created {len(created_windows)} availability window(s)" + 
                          (f" with {len(conflicts)} overlap(s)" if conflicts else "")
            }
            
            return Response(response_data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"detail": f"Failed to apply template: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @extend_schema(
        summary="Save Current Windows as Template",
        description=(
            "Save the current event's availability windows as a reusable template. "
            "The template will be associated with your organization and can be applied "
            "to future events. Window dates are converted to offsets from event start date "
            "for reusability."
        ),
        tags=["Events", "Availability Windows"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': 'Name for the template'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Optional description of the template'
                    }
                },
                'required': ['name']
            }
        },
        responses={
            201: AvailabilityWindowTemplateSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
        }
    )
    @action(detail=True, methods=['post'], url_path='save-windows-as-template',
            permission_classes=[permissions.IsAuthenticated], url_name='save-windows-as-template')
    def save_windows_as_template(self, request, url_safe_title=None, **kwargs):
        """Save the current event's availability windows as a custom template."""
        from apps.common.models import AvailabilityWindowTemplate
        from apps.common.api.serializers import AvailabilityWindowTemplateSerializer
        from datetime import datetime
        
        event = self.get_object()
        
        # Permission check
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to create templates from this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        name = request.data.get('name')
        if not name:
            return Response(
                {"detail": "Template name is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get event's availability windows
        windows = event.availability_windows.all()
        if not windows:
            return Response(
                {"detail": "Event has no availability windows to save"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Convert windows to template format (calculate offsets from event start)
        event_start = event.start_datetime
        windows_config = []
        
        for window in windows:
            # Calculate offsets in days
            offset_from = (window.available_from - event_start).total_seconds() / (24 * 3600)
            offset_to = (window.available_to - event_start).total_seconds() / (24 * 3600)
            
            windows_config.append({
                'name': window.name,
                'description': window.description or '',
                'availability_type': window.availability_type,
                'offset_from_event_start': round(offset_from, 2),
                'offset_to_event_start': round(offset_to, 2),
            })
        
        # Create the template
        template = AvailabilityWindowTemplate.objects.create(
            name=name,
            description=request.data.get('description', ''),
            is_predefined=False,
            organisation=event.organisation,
            windows_config=windows_config,
            created_by=request.user
        )
        
        serializer = AvailabilityWindowTemplateSerializer(template, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="List Event Resources",
        description=(
            "Retrieve all resources associated with the event including documents, images, videos, and links. "
            "Supports filtering by tag (e.g., LANDING_PHOTO) and resource type. "
            "Resources can be public or restricted based on permissions."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='tag', type=OpenApiTypes.STR, description='Filter by resource tag'),
            OpenApiParameter(name='resource_type', type=OpenApiTypes.STR, description='Filter by resource type'),
        ],
        responses={
            200: ResourceSerializer(many=True),
        }
    )
    @action(detail=True, methods=['get'], url_path='resources')
    def resources(self, request, url_safe_title=None):
        event = self.get_object()
        resources = event.resources.all()
        
        # Filter by tag if provided
        tag = request.query_params.get('tag')
        if tag:
            resources = resources.filter(tag__iexact=tag)
        
        # Filter by resource_type if provided
        resource_type = request.query_params.get('resource_type')
        if resource_type:
            resources = resources.filter(resource_type=resource_type)

        # paginate
        paginated = self.paginate_queryset(resources)
        if paginated is not None:
            serializer = ResourceSerializer(paginated, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        serializer = ResourceSerializer(resources, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Add Resource to Event",
        description=(
            "Add a new resource to the event such as documents, images, videos, audio files, or links. "
            "Supports file uploads for documents and images, or URL for links. "
            "Resources can be tagged for organization (e.g., LANDING_PHOTO) and marked as public or private. "
            "Only event creators, staff, and superusers can add resources."
        ),
        tags=["Events"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Resource name'},
                    'description': {'type': 'string', 'description': 'Optional description'},
                    'tag': {'type': 'string', 'description': 'Optional tag (e.g., LANDING_PHOTO)'},
                    'resource_type': {'type': 'string', 'enum': ['DOCUMENT', 'IMAGE', 'VIDEO', 'AUDIO', 'LINK', 'OTHER']},
                    'public': {'type': 'boolean', 'description': 'Whether resource is public'},
                    'file': {'type': 'string', 'format': 'binary', 'description': 'File upload for DOCUMENT/OTHER types'},
                    'image': {'type': 'string', 'format': 'binary', 'description': 'Image upload for IMAGE type'},
                    'link': {'type': 'string', 'format': 'uri', 'description': 'URL for LINK type'}
                },
                'required': ['name', 'resource_type']
            }
        },
        responses={
            201: ResourceSerializer,
            400: OpenApiResponse(description='Validation errors'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(detail=True, methods=['post'], url_path='add-resource', 
            permission_classes=[permissions.IsAuthenticated],
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def add_resource(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to add resources to this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = ResourceSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(Event)
            resource = serializer.save(
                target_type=content_type,
                target_id=event.id,
                added_by=request.user
            )
            return Response(
                ResourceSerializer(resource, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Add Landing Image to Event",
        description=(
            "Add a landing image to the event for display on event pages and listings. "
            "Can specify whether this is the main landing image or a secondary image. "
            "If set as main, any existing main landing image is automatically demoted to secondary. "
            "Only event creators, staff, and superusers can add landing images."
        ),
        tags=["Events"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Image name'},
                    'description': {'type': 'string', 'description': 'Optional description'},
                    'image': {'type': 'string', 'format': 'binary', 'description': 'Image file'},
                    'is_main': {'type': 'boolean', 'description': 'Set as main landing image (default: true)'},
                    'public': {'type': 'boolean', 'description': 'Whether image is public (default: true)'}
                },
                'required': ['name', 'image']
            }
        },
        responses={
            201: ResourceSerializer,
            400: OpenApiResponse(description='Validation errors'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(detail=True, methods=['post'], url_path='add-landing-image',
            permission_classes=[permissions.IsAuthenticated],
            parser_classes=[MultiPartParser, FormParser])
    def add_landing_image(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        self.check_object_permissions(request, event)
        
        if 'image' not in request.FILES:
            return Response(
                {"detail": "image file is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create resource data
        data = {
            'name': request.data.get('name'),
            'description': request.data.get('description', ''),
            'resource_type': 'IMAGE',
            'public': request.data.get('public', 'true').lower() == 'true',
            'image': request.FILES['image']
        }
        
        serializer = ResourceSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(Event)
            
            is_main = request.data.get('is_main', 'true').lower() == 'true'
            
            # If setting as main, update existing main to secondary
            if is_main:
                existing_main = event.resources.filter(tag='LANDING_PHOTO_MAIN')
                for res in existing_main:
                    res.tag = 'LANDING_PHOTO_SECONDARY'
                    res.save()
            
            resource = serializer.save(
                target_type=content_type,
                target_id=event.id,
                added_by=request.user,
                tag='LANDING_PHOTO_MAIN' if is_main else 'LANDING_PHOTO_SECONDARY'
            )
            
            return Response(
                ResourceSerializer(resource, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Update Resource Metadata",
        description=(
            "Update resource metadata such as name, description, tag, and public visibility. "
            "This endpoint updates resource information without requiring file re-upload. "
            "Useful for changing resource categories, updating descriptions, or modifying tags. "
            "Only event creators, staff, and superusers can update resources. "
            "Requires resource_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='resource_id', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description='Resource ID to update', required=True)
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Resource name'},
                    'description': {'type': 'string', 'description': 'Resource description'},
                    'tag': {'type': 'string', 'description': 'Resource tag (e.g., LANDING_PHOTO_MAIN, LANDING_PHOTO_SECONDARY)'},
                    'public': {'type': 'boolean', 'description': 'Whether resource is public'},
                },
            }
        },
        responses={
            200: ResourceSerializer,
            400: OpenApiResponse(description='Bad request or protected resource'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Resource not found')
        }
    )
    @action(detail=True, methods=['patch'], url_path='update-resource', permission_classes=[permissions.IsAuthenticated])
    def update_resource(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to update resources for this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        resource_id = request.query_params.get('resource_id')
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if resource.protected:
            return Response(
                {"detail": "This resource is protected and cannot be updated"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Use serializer for validation and update
        serializer = ResourceSerializer(
            resource, 
            data=request.data, 
            partial=True,  # Allow partial updates
            context={'request': request}
        )
        
        if serializer.is_valid():
            # Only allow updating specific fields (security measure)
            allowed_fields = ['name', 'description', 'tag', 'public']
            update_data = {k: v for k, v in serializer.validated_data.items() if k in allowed_fields}
            
            if not update_data:
                return Response(
                    {"detail": "No valid fields to update. Allowed fields: name, description, tag, public"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            serializer.save(**update_data)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Promote Landing Image to Main",
        description=(
            "Promote a secondary landing image to main landing image by updating its tag. "
            "Automatically demotes the current main image to secondary if one exists. "
            "This is more efficient than deleting and re-creating images. "
            "Only event creators, staff, and superusers can promote images. "
            "Requires resource_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='resource_id', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description='Resource ID of the secondary image to promote', required=True)
        ],
        responses={
            200: ResourceSerializer,
            400: OpenApiResponse(description='Bad request - resource must be a landing image'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Resource not found')
        }
    )
    @action(detail=True, methods=['post'], url_path='promote-landing-image', permission_classes=[permissions.IsAuthenticated])
    def promote_landing_image(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to modify landing images for this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        resource_id = request.query_params.get('resource_id')
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verify this is a landing image
        if resource.tag not in ['LANDING_PHOTO_MAIN', 'LANDING_PHOTO_SECONDARY']:
            return Response(
                {"detail": "Resource must be a landing image (LANDING_PHOTO_MAIN or LANDING_PHOTO_SECONDARY)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # If already main, nothing to do
        if resource.tag == 'LANDING_PHOTO_MAIN':
            return Response(
                {"detail": "Resource is already the main landing image"},
                status=status.HTTP_200_OK
            )
        
        # Demote current main image to secondary
        existing_main = event.resources.filter(tag='LANDING_PHOTO_MAIN').exclude(id=resource.id)
        for main_image in existing_main:
            main_image.tag = 'LANDING_PHOTO_SECONDARY'
            main_image.save()
        
        # Promote this image to main
        resource.tag = 'LANDING_PHOTO_MAIN'
        resource.save()
        
        serializer = ResourceSerializer(resource, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Demote Landing Image to Secondary",
        description=(
            "Demote the main landing image to secondary by updating its tag. "
            "This is more efficient than deleting and re-creating images. "
            "Only event creators, staff, and superusers can demote images. "
            "Requires resource_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='resource_id', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description='Resource ID of the main image to demote', required=True)
        ],
        responses={
            200: ResourceSerializer,
            400: OpenApiResponse(description='Bad request - resource must be the main landing image'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Resource not found')
        }
    )
    @action(detail=True, methods=['post'], url_path='demote-landing-image', permission_classes=[permissions.IsAuthenticated])
    def demote_landing_image(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to modify landing images for this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        resource_id = request.query_params.get('resource_id')
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verify this is the main landing image
        if resource.tag != 'LANDING_PHOTO_MAIN':
            return Response(
                {"detail": "Resource must be the main landing image (LANDING_PHOTO_MAIN)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Demote to secondary
        resource.tag = 'LANDING_PHOTO_SECONDARY'
        resource.save()
        
        serializer = ResourceSerializer(resource, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Remove Resource from Event",
        description=(
            "Remove a resource from the event by its resource ID. "
            "Permanently deletes the resource including any uploaded files. "
            "Protected resources cannot be removed. "
            "Only event creators, staff, and superusers can remove resources. "
            "Requires resource_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='resource_id', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description='Resource ID to remove', required=True)
        ],
        responses={
            204: OpenApiResponse(description='Resource removed successfully'),
            400: OpenApiResponse(description='Bad request or resource is protected'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Resource not found')
        }
    )
    @action(detail=True, methods=['delete'], url_path='remove-resource', permission_classes=[permissions.IsAuthenticated])
    def remove_resource(self, request, url_safe_title=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to remove resources from this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        resource_id = request.query_params.get('resource_id')
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if resource.protected:
            return Response(
                {"detail": "This resource is protected and cannot be deleted"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        resource.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @extend_schema(
        summary="Get Landing Images",
        description=(
            "Retrieve all landing images for the event including both main and secondary images. "
            "Landing images are displayed on event pages, listings, and promotional materials. "
            "Images are tagged as LANDING_PHOTO_MAIN or LANDING_PHOTO_SECONDARY for identification."
        ),
        tags=["Events"],
        responses={
            200: ResourceSerializer(many=True),
        }
    )
    @action(detail=True, methods=['get'], url_path='landing-images')
    def landing_images(self, request, url_safe_title=None):
        event = self.get_object()
        images = event.landing_images.all()
        serializer = ResourceSerializer(images, many=True, context={'request': request})
        # paginate
        page = self.paginate_queryset(images)
        if page is not None:
            serializer = ResourceSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        return Response(serializer.data)
    
    @extend_schema(
        summary="Get WebSocket Token",
        description=(
            "Exchange a valid HTTP JWT for a short-lived WebSocket-specific JWT token. "
            "This token is required to establish WebSocket connections for real-time updates. "
            "\n\n**Security:**\n"
            "- Token expires in 5 minutes\n"
            "- Token type='websocket' to prevent cross-use with HTTP endpoints\n"
            "- User must have permission to access the event (creator, staff, or admin)\n"
            "\n\n**Usage:**\n"
            "1. Call this endpoint with valid HTTP authentication\n"
            "2. Receive short-lived WebSocket token\n"
            "3. Connect to WebSocket: `ws://host/ws/events/{event_id}/questions/?token={ws_token}`\n"
            "4. Token must be refreshed every 5 minutes for ongoing connections\n"
            "\n\n**Response includes:**\n"
            "- `token`: The WebSocket JWT to use in query parameter\n"
            "- `expires_in`: Seconds until expiration (300)\n"
            "- `ws_url`: Complete WebSocket URL with placeholders\n"
        ),
        tags=["Events", "WebSocket"],
        responses={
            200: OpenApiResponse(
                response={
                    'type': 'object',
                    'properties': {
                        'token': {
                            'type': 'string',
                            'description': 'WebSocket-specific JWT token (5-minute expiry)'
                        },
                        'expires_in': {
                            'type': 'integer',
                            'description': 'Token lifetime in seconds (300)',
                            'example': 300
                        },
                        'ws_url': {
                            'type': 'string',
                            'description': 'WebSocket URL pattern to connect to',
                            'example': 'ws://localhost:8000/ws/events/{event_id}/questions/?token={token}'
                        }
                    }
                },
                description='WebSocket token successfully generated'
            ),
            403: OpenApiResponse(
                description='Permission denied - user does not have access to this event'
            ),
            404: OpenApiResponse(
                description='Event not found'
            )
        }
    )
    @action(detail=True, methods=['post'], url_path='ws-token', permission_classes=[permissions.IsAuthenticated])
    def ws_token(self, request, *args, **kwargs):
        """
        Generate a short-lived JWT token for WebSocket authentication.
        
        This endpoint exchanges a valid HTTP JWT for a WebSocket-specific token
        that allows establishing real-time connections for event question updates.
        """
        from datetime import timedelta
        from rest_framework_simplejwt.tokens import RefreshToken
        from django.utils import timezone
        import jwt
        from django.conf import settings
        
        event = self.get_object()
        
        # Check if user has permission to access this event
        has_permission = (
            event.created_by == request.user or
            event.staff_members.filter(user=request.user).exists() or
            request.user.is_staff or
            request.user.is_superuser
        )
        
        if not has_permission:
            return Response(
                {'detail': 'You do not have permission to access this event.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Generate WebSocket-specific JWT
        expires_in = 300  # 5 minutes
        expiration = timezone.now() + timedelta(seconds=expires_in)
        
        # Generate unique JTI (JWT ID) for token
        import uuid
        
        payload = {
            'user_id': request.user.id,
            'event_id': str(event.event_id),
            'type': 'websocket',
            'exp': expiration,
            'iat': timezone.now(),
            'jti': str(uuid.uuid4()),  # Required by simplejwt validation
        }
        
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
        
        # Construct WebSocket URL
        # Use request to determine protocol (ws:// or wss://)
        ws_protocol = 'wss' if request.is_secure() else 'ws'
        host = request.get_host()
        ws_url = f"{ws_protocol}://{host}/ws/events/{event.event_id}/questions/?token={{token}}"
        
        return Response({
            'token': token,
            'expires_in': expires_in,
            'ws_url': ws_url
        })
    
    @extend_schema(
        summary="Assign Permission to User",
        description=(
            "Assign a specific permission to a user for this event, granting them access to perform specific actions. "
            "Creates an EventPermissionAssignment linking user, event, and permission with CRUD flags. "
            "CRUD flags control granular access: read_only (if True, only read access), allow_create, allow_update, allow_delete. "
            "Prevents duplicate assignments to the same user for the same permission. "
            "Only event creators, staff, and superusers can assign permissions."
        ),
        tags=["Events"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'User ID'},
                    'permission_id': {'type': 'integer', 'description': 'Permission ID'},
                    'read_only': {'type': 'boolean', 'description': 'If True, user can only READ (other flags ignored)', 'default': False},
                    'allow_create': {'type': 'boolean', 'description': 'Allow CREATE operations', 'default': False},
                    'allow_update': {'type': 'boolean', 'description': 'Allow UPDATE operations', 'default': False},
                    'allow_delete': {'type': 'boolean', 'description': 'Allow DELETE operations', 'default': False}
                },
                'required': ['user_id', 'permission_id']
            }
        },
        responses={
            201: EventPermissionAssignmentSerializer,
            400: OpenApiResponse(description='Validation errors'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(detail=True, methods=['post'], url_path='assign-permission', permission_classes=[permissions.IsAuthenticated])
    def assign_permission(self, request, pk=None):
        from django.contrib.auth import get_user_model
        
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to assign permissions for this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        permission_id = request.data.get('permission_id')
        read_only = request.data.get('read_only', False)
        allow_create = request.data.get('allow_create', False)
        allow_update = request.data.get('allow_update', False)
        allow_delete = request.data.get('allow_delete', False)
        
        if not user_id or not permission_id:
            return Response(
                {"detail": "user_id and permission_id are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
            permission = EventPermission.objects.get(id=permission_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except EventPermission.DoesNotExist:
            return Response({"detail": "Permission not found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if already assigned
        assignment, created = EventPermissionAssignment.objects.get_or_create(
            event=event,
            user=user,
            permission=permission,
            defaults={
                'assigned_by': request.user,
                'read_only': read_only,
                'allow_create': allow_create,
                'allow_update': allow_update,
                'allow_delete': allow_delete
            }
        )
        
        if not created:
            # Update existing assignment with new CRUD flags
            assignment.read_only = read_only
            assignment.allow_create = allow_create
            assignment.allow_update = allow_update
            assignment.allow_delete = allow_delete
            assignment.save()
            
            serializer = EventPermissionAssignmentSerializer(assignment, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        serializer = EventPermissionAssignmentSerializer(assignment, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Revoke Permission from User",
        description=(
            "Revoke a specific permission from a user for this event by deleting the permission assignment. "
            "Immediately removes the user's access to perform the specific action. "
            "Only event creators, staff, and superusers can revoke permissions. "
            "Requires assignment_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name='assignment_id', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description='Permission assignment ID to revoke', required=True)
        ],
        responses={
            204: OpenApiResponse(description='Permission revoked successfully'),
            400: OpenApiResponse(description='Bad request'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Assignment not found')
        }
    )
    @action(detail=True, methods=['delete'], url_path='revoke-permission', permission_classes=[permissions.IsAuthenticated])
    def revoke_permission(self, request, *args, **kwargs):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to revoke permissions for this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        assignment_id = request.query_params.get('assignment_id')
        if not assignment_id:
            return Response(
                {"detail": "assignment_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            assignment = EventPermissionAssignment.objects.get(id=assignment_id, event=event)
        except EventPermissionAssignment.DoesNotExist:
            return Response(
                {"detail": "Permission assignment not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        assignment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @extend_schema(
        summary="Check User Permissions for Event",
        description=(
            "Get comprehensive permission information for a user on this event. "
            "Returns detailed access rights including:\n\n"
            "**User Relationships:**\n"
            "- Whether the user is the event creator\n"
            "- Whether the user is an event staff member\n"
            "- Whether the user is a Django admin/staff\n\n"
            "**Computed Permissions:**\n"
            "- `can_manage_event`: Edit event details, settings, and configuration\n"
            "- `can_manage_staff`: Add/remove staff members and manage team\n"
            "- `can_manage_invites`: Create and manage staff invitations\n"
            "- `can_manage_resources`: Add/remove event resources (documents, images, links)\n"
            "- `can_delete_event`: Soft delete or restore the event\n\n"
            "**Explicit Assignments:**\n"
            "- List of specific permissions explicitly assigned to the user\n"
            "- List of roles assigned to the user (which grant bundles of permissions)\n\n"
            "**Usage:**\n"
            "- If `user_id` query param is provided, checks permissions for that user (requires admin/owner access)\n"
            "- If no `user_id` provided, checks permissions for the currently authenticated user\n"
            "- Useful for UI to show/hide management buttons based on user access\n"
            "- Helps frontend determine what actions are available to the user"
        ),
        tags=["Events", "Permissions"],
        parameters=[
            OpenApiParameter(
                name='user_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Optional: Check permissions for a specific user ID. If omitted, checks current authenticated user.',
                required=False
            )
        ],
        responses={
            200: OpenApiResponse(
                response={
                    'type': 'object',
                    'properties': {
                        'user_id': {
                            'type': 'integer',
                            'description': 'ID of the user whose permissions were checked'
                        },
                        'user_email': {
                            'type': 'string',
                            'description': 'Email address of the user'
                        },
                        'user_name': {
                            'type': 'string',
                            'description': 'Full name of the user'
                        },
                        'is_creator': {
                            'type': 'boolean',
                            'description': 'Whether the user created this event'
                        },
                        'is_staff_member': {
                            'type': 'boolean',
                            'description': 'Whether the user is an event staff member'
                        },
                        'is_admin': {
                            'type': 'boolean',
                            'description': 'Whether the user is a Django staff/superuser'
                        },
                        'can_manage_event': {
                            'type': 'boolean',
                            'description': 'Can edit event details and settings'
                        },
                        'can_manage_staff': {
                            'type': 'boolean',
                            'description': 'Can add/remove staff members'
                        },
                        'can_manage_invites': {
                            'type': 'boolean',
                            'description': 'Can create/manage staff invitations'
                        },
                        'can_manage_resources': {
                            'type': 'boolean',
                            'description': 'Can add/remove resources (images, documents, links)'
                        },
                        'can_delete_event': {
                            'type': 'boolean',
                            'description': 'Can soft delete or restore the event'
                        },
                        'assigned_permissions': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'id': {'type': 'integer'},
                                    'permission_name': {'type': 'string'},
                                    'permission_code': {'type': 'string'},
                                    'permission_category': {'type': 'string'},
                                    'assigned_at': {'type': 'string', 'format': 'date-time'},
                                    'assigned_by_email': {'type': 'string'}
                                }
                            },
                            'description': 'List of explicitly assigned permissions with details'
                        },
                        'assigned_roles': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'id': {'type': 'integer'},
                                    'role_name': {'type': 'string'},
                                    'role_code': {'type': 'string'},
                                    'role_category': {'type': 'string'},
                                    'assigned_at': {'type': 'string', 'format': 'date-time'},
                                    'assigned_by_email': {'type': 'string'}
                                }
                            },
                            'description': 'List of assigned roles with details'
                        }
                    },
                    'required': [
                        'user_id', 'user_email', 'is_creator', 'is_staff_member', 'is_admin',
                        'can_manage_event', 'can_manage_staff', 'can_manage_invites',
                        'can_manage_resources', 'can_delete_event', 'assigned_permissions', 'assigned_roles'
                    ]
                },
                description='Comprehensive permission information for the user'
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in to check permissions'
            ),
            403: OpenApiResponse(
                description='Permission denied. Only admins and event creators can check permissions for other users'
            ),
            404: OpenApiResponse(
                description='User not found with the specified user_id'
            )
        }
    )
    @action(detail=True, methods=['get'], url_path='check-permissions')
    def check_user_permissions(self, request, url_safe_title=None):
        """
        Check comprehensive permissions for a user on this event.
        
        Returns detailed information about user's access rights including:
        - Basic relationships (creator, staff, admin)
        - Computed permissions (can manage various aspects)
        - Explicitly assigned permissions and roles
        """
        from django.contrib.auth import get_user_model
        
        event = self.get_object()
        
        # Determine which user to check
        user_id = request.query_params.get('user_id')
        if user_id:
            # Only admins and event creators can check other users' permissions
            if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
                return Response(
                    {"detail": "You don't have permission to check other users' permissions"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            User = get_user_model()
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {"detail": "User not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            if not request.user.is_authenticated:
                return Response(
                    {"detail": "Authentication required"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            user = request.user
        
        # Check basic relationships
        is_creator = user == event.created_by
        is_admin = user.is_staff or user.is_superuser
        is_staff_member = event.staff_members.filter(user=user).exists() if not is_creator else True
        
        # Compute derived permissions
        can_manage = is_creator or is_staff_member or is_admin
        
        # Get explicitly assigned permissions with details
        permission_assignments = EventPermissionAssignment.objects.filter(
            event=event,
            user=user
        ).select_related('permission', 'assigned_by')
        
        assigned_permissions = []
        for assignment in permission_assignments:
            # Determine effective permissions based on read_only flag
            if assignment.read_only:
                effective_access = {
                    'can_read': True,
                    'can_create': False,
                    'can_update': False,
                    'can_delete': False
                }
            else:
                effective_access = {
                    'can_read': assignment.allow_update or assignment.allow_delete or assignment.allow_create,
                    'can_create': assignment.allow_create,
                    'can_update': assignment.allow_update,
                    'can_delete': assignment.allow_delete
                }
            
            assigned_permissions.append({
                'id': assignment.id,
                'permission_name': assignment.permission.name,
                'permission_code': assignment.permission.code,
                'permission_category': assignment.permission.category,
                'permission_description': assignment.permission.description,
                'read_only': assignment.read_only,
                'allow_create': assignment.allow_create,
                'allow_update': assignment.allow_update,
                'allow_delete': assignment.allow_delete,
                'has_full_access': assignment.has_full_access,
                'effective_access': effective_access,
                'assigned_at': assignment.assigned_at,
                'assigned_by_email': assignment.assigned_by.email if assignment.assigned_by else None,
                'assigned_by_name': assignment.assigned_by.get_full_name() if assignment.assigned_by else None
            })
        
        # Get assigned roles with details
        role_assignments = EventRoleAssignment.objects.filter(
            event=event,
            user=user
        ).select_related('role', 'assigned_by')
        
        assigned_roles = [
            {
                'id': assignment.id,
                'role_name': assignment.role.name,
                'role_code': assignment.role.code,
                'role_category': assignment.role.category,
                'role_description': assignment.role.description,
                'assigned_at': assignment.assigned_at,
                'assigned_by_email': assignment.assigned_by.email if assignment.assigned_by else None,
                'assigned_by_name': assignment.assigned_by.get_full_name() if assignment.assigned_by else None
            }
            for assignment in role_assignments
        ]
        
        return Response({
            'user_id': user.id,
            'user_email': user.email,
            'user_name': user.get_full_name(),
            'is_creator': is_creator,
            'is_staff_member': is_staff_member,
            'is_admin': is_admin,
            'can_manage_event': can_manage,
            'can_manage_staff': can_manage,
            'can_manage_invites': can_manage,
            'can_manage_resources': can_manage,
            'can_delete_event': can_manage,
            'assigned_permissions': assigned_permissions,
            'assigned_roles': assigned_roles
        })
    
    # ====== Staff Invites Actions ======
    
    @extend_schema(
        methods=['GET'],
        operation_id='event_staff_invites_list',
        summary="List Event Staff Invites",
        description=(
            "Retrieve a paginated list of all staff invites for this specific event with comprehensive filtering capabilities. "
            "Permission-based visibility ensures users only see relevant invites:\n"
            "- Event creators and existing staff members can view ALL invites for their event\n"
            "- Regular authenticated users can only see invites where they are the target user\n"
            "- Django staff and superusers have full visibility\n\n"
            "**Filtering Options:**\n"
            "- `accepted`: Filter by whether invite has been accepted (true/false)\n"
            "- `is_valid`: Filter by validity status - valid invites are active, not expired, and not accepted\n"
            "- `target_user`: Filter by target user ID to see all invites for a specific user\n"
            "- `search`: Search by target user email address for quick lookup\n\n"
            "Results are automatically ordered by creation date (newest first) and include:\n"
            "- Invite status (active, accepted, expired)\n"
            "- Target user information (email, name)\n"
            "- Inviter information (who sent the invite)\n"
            "- Validity status (is_valid property)\n"
            "- HATEOAS links for invite management and acceptance"
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='url_safe_title',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='UUID of the event to list invites for',
                required=True
            ),
            OpenApiParameter(
                name='accepted',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter invites by acceptance status. true=accepted, false=not accepted',
                required=False
            ),
            OpenApiParameter(
                name='is_valid',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description=(
                    'Filter invites by validity status. Valid invites are: active, not expired, and not yet accepted. '
                    'Use true to get only valid (pending) invites, false to get invalid invites'
                ),
                required=False
            ),
            OpenApiParameter(
                name='target_user',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Filter invites by target user ID. Returns all invites sent to the specified user for this event',
                required=False
            ),
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Search invites by target user email address. Case-insensitive partial match',
                required=False
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Page number for pagination',
                required=False
            ),
            OpenApiParameter(
                name='page_size',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Number of results per page (default: 20)',
                required=False
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=EventStaffInviteListSerializer(many=True),
                description=(
                    'Successfully retrieved list of invites. Returns paginated results with invite summaries including: '
                    'invite ID, event details, target user info, inviter info, acceptance status, validity status, '
                    'timestamps, and HATEOAS links for related actions'
                )
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in to list invites'
            ),
            403: OpenApiResponse(
                description='Permission denied. User is not event creator, staff, or target user'
            ),
            404: OpenApiResponse(
                description='Event not found with the specified event_id'
            )
        }
    )
    @extend_schema(
        methods=['POST'],
        operation_id='event_staff_invites_create',
        summary="Create Event Staff Invite",
        description=(
            "Create a new staff invite to invite a user to join the event staff team. "
            "The invite is sent to a target user who can then accept it to become an event staff member.\n\n"
            "**Required Fields:**\n"
            "- `target_user` (integer): ID of the user being invited\n\n"
            "**Optional Fields:**\n"
            "- `expires_at` (datetime): When the invite expires (ISO 8601 format). If omitted, invite never expires\n\n"
            "**Permissions:**\n"
            "Only event creators and existing event staff members can create invites. "
            "Django staff and superusers also have permission.\n\n"
            "**Validations:**\n"
            "- Target user must exist in the system\n"
            "- Target user cannot already have an active invite for this event\n"
            "- Target user cannot already be an event staff member\n"
            "- Expiry date (if provided) must be in the future\n"
            "- The authenticated user is automatically recorded as the inviter\n\n"
            "**Workflow:**\n"
            "1. Event creator/staff creates invite\n"
            "2. Target user receives notification (outside API scope)\n"
            "3. Target user can view invite via GET request or my-invites action\n"
            "4. Target user accepts invite via accept action\n"
            "5. EventStaff record is automatically created\n"
            "6. Invite is marked as accepted and inactive"
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='url_safe_title',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='UUID of the event to create invite for',
                required=True
            ),
        ],
        request=EventStaffInviteSerializer,
        responses={
            201: OpenApiResponse(
                response=EventStaffInviteSerializer,
                description=(
                    'Successfully created new staff invite. Returns complete invite details including: '
                    'invite ID, event information, target user details, inviter details, expiry date, '
                    'validity status, and HATEOAS links for management and acceptance actions'
                )
            ),
            400: OpenApiResponse(
                description=(
                    'Bad request - validation errors occurred. Common causes:\n'
                    '- Target user already has an active invite for this event\n'
                    '- Target user is already an event staff member\n'
                    '- Expiry date is in the past\n'
                    '- Required fields missing (target_user)\n'
                    '- Invalid field values or formats'
                )
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in to create invites'
            ),
            403: OpenApiResponse(
                description='Permission denied. User is not event creator or existing staff member'
            ),
            404: OpenApiResponse(
                description='Event not found with the specified url_safe_title'
            )
        }
    )
    @action(detail=True, methods=['get', 'post'], url_path='staff-invites',
            permission_classes=[permissions.IsAuthenticated])
    def staff_invites(self, request, url_safe_title=None):
        """List all staff invites or create a new invite for this event."""

        event = get_object_or_404(Event, url_safe_title=url_safe_title)
        # GET - List invites
        if request.method == 'GET':
            queryset = EventStaffInvite.objects.filter(event=event).select_related(
                'target_user', 'invited_by'
            ).order_by('-added_at')
            
            # Non-staff/non-owner can only see their own invites
            if not (request.user == event.created_by or 
                    event.staff_members.filter(user=request.user).exists() or
                    request.user.is_staff or request.user.is_superuser):
                queryset = queryset.filter(target_user=request.user)
            
            # Apply filters
            accepted = request.query_params.get('accepted')
            if accepted is not None:
                queryset = queryset.filter(accepted=accepted.lower() in ['true', '1', 'yes'])
            
            is_valid_param = request.query_params.get('is_valid')
            if is_valid_param is not None:
                if is_valid_param.lower() in ['true', '1', 'yes']:
                    queryset = queryset.filter(
                        is_active=True,
                        accepted=False
                    ).filter(
                        Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
                    )
            
            target_user = request.query_params.get('target_user')
            if target_user:
                queryset = queryset.filter(target_user_id=target_user)
            
            search = request.query_params.get('search')
            if search:
                queryset = queryset.filter(
                    Q(target_user__email__icontains=search) |
                    Q(target_user__first_name__icontains=search) |
                    Q(target_user__last_name__icontains=search)
                )
            
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = EventStaffInviteListSerializer(page, many=True, context={'request': request, 'event': event.url_safe_title})
                return self.get_paginated_response(serializer.data)
            
            serializer = EventStaffInviteListSerializer(queryset, many=True, context={'request': request, 'event': event.url_safe_title})
            return Response(serializer.data)
        
        # POST - Create invite
        elif request.method == 'POST':
            # Check if user can manage invites for this event
            if not (request.user == event.created_by or 
                    event.staff_members.filter(user=request.user).exists() or
                    request.user.is_staff or request.user.is_superuser):
                return Response(
                    {'detail': 'You do not have permission to create invites for this event.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Don't pass event in data, it comes from context
            serializer = EventStaffInviteSerializer(data=request.data, context={'request': request, 'event': event.url_safe_title})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        methods=['GET'],
        operation_id='event_staff_invite_retrieve',
        summary="Retrieve Staff Invite Details",
        description=(
            "Fetch complete details for a specific event staff invite including:\n"
            "- Full invite metadata (ID, status, created/updated timestamps)\n"
            "- Complete event information (ID, name, description, dates)\n"
            "- Target user details (ID, email, name, profile)\n"
            "- Inviter information (who sent the invite)\n"
            "- Validity and acceptance status\n"
            "- Expiry information (if applicable)\n"
            "- HATEOAS links for invite management and acceptance\n\n"
            "**Permissions:** Users can retrieve invites if they are:\n"
            "- The event creator or existing staff member (can see all invites)\n"
            "- The target user of the invite (can see their own invite)\n"
            "- Django staff or superuser (full visibility)"
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='url_safe_title',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='UUID of the event containing the invite',
                required=True
            ),
            OpenApiParameter(
                name='invite_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='Integer ID of the specific staff invite to retrieve',
                required=True
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=EventStaffInviteSerializer,
                description=(
                    'Successfully retrieved invite. Returns complete invite details with all fields including: '
                    'invite ID, event information, target user details, inviter details, acceptance status, '
                    'validity status, timestamps, expiry date, and HATEOAS links'
                )
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in to access invites'
            ),
            403: OpenApiResponse(
                description='Permission denied. User is not event creator, staff, or the target user'
            ),
            404: OpenApiResponse(
                description=(
                    'Not found. Either the event does not exist with the specified event_id, '
                    'or the invite does not exist with the specified invite_id for this event'
                )
            )
        }
    )
    @extend_schema(
        methods=['PUT'],
        operation_id='event_staff_invite_update',
        summary="Full Update Staff Invite",
        description=(
            "Completely replace an existing staff invite with new data. All fields must be provided.\n\n"
            "**Required Fields:**\n"
            "- `target_user` (integer): New target user ID\n"
            "- `expires_at` (datetime or null): New expiry date (ISO 8601) or null for no expiry\n\n"
            "**Behavior:**\n"
            "- Replaces ALL editable fields with provided values\n"
            "- Read-only fields (event, created_at, updated_at) are preserved\n"
            "- Can change target user if new user doesn't have existing invite\n"
            "- Can modify expiry date or remove it (set to null)\n"
            "- Cannot modify already accepted invites\n\n"
            "**Permissions:**\n"
            "Only event creators and existing event staff members can update invites. "
            "Django staff and superusers also have full access."
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='url_safe_title',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='UUID of the event containing the invite',
                required=True
            ),
            OpenApiParameter(
                name='invite_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the specific staff invite to update',
                required=True
            ),
        ],
        request=EventStaffInviteSerializer,
        responses={
            200: OpenApiResponse(
                response=EventStaffInviteSerializer,
                description='Successfully updated invite. Returns complete updated invite details'
            ),
            400: OpenApiResponse(
                description=(
                    'Bad request - validation errors occurred. Common causes:\n'
                    '- Attempting to modify an already-accepted invite\n'
                    '- New target user already has an active invite for this event\n'
                    '- New target user is already an event staff member\n'
                    '- New expiry date is in the past\n'
                    '- Required fields missing'
                )
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in'
            ),
            403: OpenApiResponse(
                description='Permission denied. User is not event creator or existing staff member'
            ),
            404: OpenApiResponse(
                description='Invite not found'
            )
        }
    )
    @extend_schema(
        methods=['PATCH'],
        operation_id='event_staff_invite_partial_update',
        summary="Partial Update Staff Invite",
        description=(
            "Update specific fields of an existing staff invite without replacing the entire object.\n\n"
            "**Optional Fields** (provide only what you want to change):\n"
            "- `target_user` (integer): Change the target user\n"
            "- `expires_at` (datetime or null): Modify expiry date or remove expiry\n\n"
            "**Behavior:**\n"
            "- Only provided fields are updated\n"
            "- Unprovided fields remain unchanged\n"
            "- Useful for extending expiry without changing target user\n"
            "- Cannot modify already accepted invites\n\n"
            "**Permissions:**\n"
            "Only event creators and existing event staff members can update invites. "
            "Django staff and superusers also have full access."
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='url_safe_title',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='UUID of the event containing the invite',
                required=True
            ),
            OpenApiParameter(
                name='invite_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the specific staff invite to update',
                required=True
            ),
        ],
        request=EventStaffInviteSerializer,
        responses={
            200: OpenApiResponse(
                response=EventStaffInviteSerializer,
                description='Successfully updated invite. Returns complete updated invite details'
            ),
            400: OpenApiResponse(
                description=(
                    'Bad request - validation errors occurred. Common causes:\n'
                    '- Attempting to modify an already-accepted invite\n'
                    '- New target user already has an active invite for this event\n'
                    '- New expiry date is in the past'
                )
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in'
            ),
            403: OpenApiResponse(
                description='Permission denied. User is not event creator or existing staff member'
            ),
            404: OpenApiResponse(
                description='Invite not found'
            )
        }
    )
    @extend_schema(
        methods=['DELETE'],
        operation_id='event_staff_invite_delete',
        summary="Delete Staff Invite",
        description=(
            "Permanently delete a staff invite from the system. This action is irreversible.\n\n"
            "**Use Cases:**\n"
            "- Rescind an invite before it's accepted\n"
            "- Clean up expired or invalid invites\n"
            "- Remove duplicate or erroneous invites\n\n"
            "**Behavior:**\n"
            "- Completely removes invite record from database\n"
            "- Cannot be undone\n"
            "- Safe to delete accepted invites (doesn't affect EventStaff membership)\n"
            "- No response body on success (204 status)\n\n"
            "**Permissions:**\n"
            "Only event creators and existing event staff members can delete invites. "
            "Django staff and superusers also have full access."
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='url_safe_title',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='UUID of the event containing the invite',
                required=True
            ),
            OpenApiParameter(
                name='invite_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the specific staff invite to delete',
                required=True
            ),
        ],
        responses={
            204: OpenApiResponse(
                description='Successfully deleted invite. The invite has been permanently removed from the system'
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in'
            ),
            403: OpenApiResponse(
                description='Permission denied. User is not event creator or existing staff member'
            ),
            404: OpenApiResponse(
                description='Invite not found'
            )
        }
    )
    @action(detail=True, methods=['get', 'put', 'patch', 'delete'], 
            url_path='staff-invites/(?P<invite_id>[^/.]+)',
            permission_classes=[permissions.IsAuthenticated])
    def manage_staff_invite(self, request, url_safe_title=None, invite_id=None):
        """Retrieve, update, or delete a specific staff invite for this event."""
        event = self.get_object()
        
        try:
            invite = EventStaffInvite.objects.select_related(
                'target_user', 'invited_by'
            ).get(id=invite_id, event=event)
        except EventStaffInvite.DoesNotExist:
            return Response(
                {'detail': 'Staff invite not found for this event.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except EventStaffInvite.MultipleObjectsReturned:
            return Response(
                {'detail': 'Multiple invites found with the same ID for this event.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except ValueError:
            return Response(
                {'detail': 'Invalid invite ID format.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # GET - Retrieve
        if request.method == 'GET':
            # Check permissions - creator, staff, or target user can view
            if not (request.user == event.created_by or
                    event.staff_members.filter(user=request.user).exists() or
                    invite.target_user == request.user or
                    request.user.is_staff or request.user.is_superuser):
                return Response(
                    {'detail': 'You do not have permission to view this invite.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            serializer = EventStaffInviteSerializer(invite, context={'request': request, 'event': event.url_safe_title})
            return Response(serializer.data)
        
        # PUT/PATCH - Update
        elif request.method in ['PUT', 'PATCH']:
            # Check permissions - only creator or staff can update
            if not (request.user == event.created_by or
                    event.staff_members.filter(user=request.user).exists() or
                    request.user.is_staff or request.user.is_superuser):
                return Response(
                    {'detail': 'You do not have permission to update this invite.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            partial = request.method == 'PATCH'
            serializer = EventStaffInviteSerializer(
                invite, data=request.data, partial=partial,
                context={'request': request, 'event': event.url_safe_title}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        
        # DELETE
        elif request.method == 'DELETE':
            # Check permissions - only creator or staff can delete
            if not (request.user == event.created_by or
                    event.staff_members.filter(user=request.user).exists() or
                    request.user.is_staff or request.user.is_superuser):
                return Response(
                    {'detail': 'You do not have permission to delete this invite.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Soft delete
            invite.is_active = False
            invite.save()
            return Response(status=status.HTTP_204_NO_CONTENT)
    
    @extend_schema(
        summary="Accept Event Staff Invite",
        description=(
            "**Accept Staff Invitation and Join Event Team**\n\n"
            "This endpoint allows a user to accept a staff invitation they received for an event. "
            "Accepting the invite automatically adds the user to the event's staff team and marks the invite as processed.\n\n"
            "**Workflow:**\n"
            "1. User receives a staff invite (created via POST /staff-invites/)\n"
            "2. User can view their pending invites via GET /staff-invites/ or my-invites action\n"
            "3. User accepts invite by calling this endpoint\n"
            "4. System validates the invite is still valid\n"
            "5. System creates EventStaff record for the user\n"
            "6. Invite is marked as accepted and deactivated\n"
            "7. User now has staff permissions for the event\n\n"
            "**Permissions:**\n"
            "Only the target user specified in the invite can accept it. The system validates:\n"
            "- The authenticated user matches the invite's target_user\n"
            "- The invite is still active and not deactivated\n"
            "- The invite has not already been accepted\n"
            "- The invite has not expired (if expiry date was set)\n"
            "- The user is not already a staff member for this event\n\n"
            "**Validation Checks:**\n"
            "- **Active Status**: Invite must be active (is_active=True)\n"
            "- **Acceptance Status**: Invite must not be already accepted\n"
            "- **Expiry Date**: If set, expires_at must be in the future\n"
            "- **Target User**: Authenticated user must be the invite target\n"
            "- **Duplicate Staff**: User cannot already be an event staff member\n\n"
            "**Success Response:**\n"
            "Returns a success message and the newly created EventStaff object with:\n"
            "- Staff member ID and role information\n"
            "- Event details\n"
            "- User information\n"
            "- Timestamps (joined date)\n"
            "- HATEOAS links for staff management\n\n"
            "**Atomic Operation:**\n"
            "The acceptance process is atomic - either both the EventStaff record is created AND the invite is marked "
            "as accepted, or neither happens. This prevents data inconsistencies."
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='url_safe_title',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description='UUID of the event for which the invite was sent',
                required=True
            ),
            OpenApiParameter(
                name='invite_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the specific staff invite to accept',
                required=True
            ),
        ],
        request=None,  # POST with no body
        responses={
            200: OpenApiResponse(
                response={
                    'type': 'object',
                    'properties': {
                        'message': {
                            'type': 'string',
                            'example': 'Invite accepted successfully. You are now an event staff member.',
                            'description': 'Success confirmation message'
                        },
                        'staff': {
                            'type': 'object',
                            'description': 'The newly created EventStaff object with complete details'
                        }
                    }
                },
                description=(
                    'Invite successfully accepted. User has been added to the event staff team. '
                    'Returns a success message and the EventStaff object containing: '
                    'staff ID, event details, user information, role, join date, and management links'
                )
            ),
            400: OpenApiResponse(
                description=(
                    'Bad request - invite is not valid for acceptance. Common causes:\n'
                    '- Invite has already been accepted (accepted=True)\n'
                    '- Invite has been deactivated (is_active=False)\n'
                    '- Invite has expired (expires_at in the past)\n'
                    '- User is already an event staff member\n'
                    '- Invite is in an invalid state\n\n'
                    'Error response includes a specific message explaining why the invite cannot be accepted'
                )
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in to accept invites'
            ),
            403: OpenApiResponse(
                description=(
                    'Permission denied. The authenticated user is not the target user of this invite. '
                    'Users can only accept invites that were sent to them specifically'
                )
            ),
            404: OpenApiResponse(
                description=(
                    'Not found. Either:\n'
                    '- The event does not exist with the specified event_id\n'
                    '- The invite does not exist with the specified invite_id\n'
                    '- The invite exists but is not associated with this event'
                )
            )
        }
    )
    @action(detail=True, methods=['post'], url_path='staff-invites/(?P<invite_id>[^/.]+)/accept',
            permission_classes=[permissions.IsAuthenticated])
    def accept_invite(self, request, url_safe_title=None, invite_id=None):
        """Accept a staff invite for this event."""
        event = self.get_object()
        
        try:
            invite = EventStaffInvite.objects.get(id=invite_id, event=event)
        except EventStaffInvite.DoesNotExist:
            return Response(
                {'detail': 'Staff invite not found for this event.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError:
            return Response(
                {'detail': 'Invalid invite ID format.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Only the target user can accept their invite
        if invite.target_user != request.user:
            return Response(
                {'detail': 'You can only accept invites sent to you.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if invite is valid
        if not invite.is_valid:
            error_msg = 'This invite is no longer valid.'
            if not invite.is_active:
                error_msg = 'This invite has been deactivated.'
            elif invite.accepted:
                error_msg = 'This invite has already been accepted.'
            elif invite.expires_at and invite.expires_at < timezone.now():
                error_msg = 'This invite has expired.'
            
            return Response(
                {'error': error_msg},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Accept the invite (creates EventStaff record)
            staff = invite.accept_invite()
            
            serializer = EventStaffSerializer(staff, context={'request': request})
            return Response(
                {
                    'message': 'Invite accepted successfully. You are now an event staff member.',
                    'staff': serializer.data
                },
                status=status.HTTP_200_OK
            )
        
        except ValueError as e:
            return Response(
                {'error': f'Failed to accept invite: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


@extend_schema_view(
    list=extend_schema(
        summary="List Event Settings",
        description=(
            "Retrieve a paginated list of all event settings across the system. "
            "Event settings control various aspects of event behavior including product selling, "
            "order approval requirements, and booking configurations. Primarily used for administrative oversight."
        ),
        tags=["Event Settings"],
    ),
    retrieve=extend_schema(
        summary="Get Event Settings",
        description=(
            "Retrieve detailed settings for a specific event including all configuration options. "
            "Settings control product selling options, order approval workflows, booking behavior, and other event-specific preferences."
        ),
        tags=["Event Settings"],
    ),
    create=extend_schema(
        summary="Create Event Settings",
        description=(
            "Create new settings for an event with specified configuration options. "
            "Typically created automatically when an event is created. "
            "Only event managers and administrators can create settings."
        ),
        tags=["Event Settings"],
    ),
    update=extend_schema(
        summary="Update Event Settings",
        description=(
            "Update all settings for an event. Requires complete payload with all fields. "
            "Use PATCH for partial updates of individual settings. "
            "Only event managers and administrators can update settings."
        ),
        tags=["Event Settings"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Settings",
        description=(
            "Partially update event settings without providing complete payload. "
            "Allows updating individual configuration options independently. "
            "Only event managers and administrators can update settings."
        ),
        tags=["Event Settings"],
    ),
    destroy=extend_schema(
        summary="Delete Event Settings",
        description=(
            "Delete event settings. Use with caution as this affects event functionality. "
            "Only administrators should delete event settings. "
            "Consider updating instead of deleting to preserve configuration history."
        ),
        tags=["Event Settings"],
    )
)
class EventSettingsViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event settings and configurations.
    
    Provides CRUD operations for event settings including:
    - Product selling options
    - Order approval requirements
    - Booking configurations
    - Custom event preferences
    
    Settings are typically created automatically when events are created and
    control various aspects of event behavior and functionality.
    """
    queryset = EventSettings.objects.all()
    serializer_class = EventSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination


@extend_schema_view(
    list=extend_schema(
        summary="List Event Authorizations",
        description=(
            "Retrieve a paginated list of event authorizations with comprehensive filtering options. "
            "Authorizations track approval status for events requiring review before publication. "
            "Supports filtering by event, status, and reviewer. Useful for administrative workflows."
        ),
        tags=["Event Authorizations"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event ID'),
            OpenApiParameter(name='status', type=OpenApiTypes.STR, description='Filter by authorization status'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Authorization Details",
        description=(
            "Retrieve detailed information about a specific event authorization including review status, "
            "reviewer details, timestamps, and associated event information."
        ),
        tags=["Event Authorizations"],
    ),
    create=extend_schema(
        summary="Create Event Authorization",
        description=(
            "Create a new event authorization for review and approval workflow. "
            "Automatically assigns the authenticated user as the reviewer. "
            "Only administrators can create authorizations."
        ),
        tags=["Event Authorizations"],
    ),
    update=extend_schema(
        summary="Update Event Authorization",
        description=(
            "Update an event authorization with complete payload including status and review comments. "
            "Use PATCH for partial updates. Only reviewers and administrators can update authorizations."
        ),
        tags=["Event Authorizations"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Authorization",
        description=(
            "Partially update an event authorization such as changing status or adding review notes. "
            "Only reviewers and administrators can update authorizations."
        ),
        tags=["Event Authorizations"],
    ),
    destroy=extend_schema(
        summary="Delete Event Authorization",
        description=(
            "Delete an event authorization record. Use with caution as this removes approval history. "
            "Only administrators should delete authorizations."
        ),
        tags=["Event Authorizations"],
    )
)
class EventAuthorizationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event authorizations and approval workflows.
    
    Handles authorization processes for events requiring review before publication.
    Tracks approval status, reviewer information, and review timestamps.
    """
    queryset = EventAuthorization.objects.select_related('event', 'reviewed_by').all()
    serializer_class = EventAuthorizationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventAuthorizationFilterSet
    ordering_fields = ['reviewed_at']
    ordering = ['-reviewed_at']
    
    def perform_create(self, serializer):
        serializer.save(reviewed_by=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List Event Permissions",
        description=(
            "Retrieve a paginated list of all available event permissions that can be assigned to users. "
            "Permissions define specific actions users can perform within events such as managing staff, resources, or settings. "
            "Supports filtering by category and searching by name or code."
        ),
        tags=["Event Permissions"],
        parameters=[
            OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Filter by category'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Permission Details",
        description=(
            "Retrieve detailed information about a specific event permission including name, code, "
            "category, description, and scope of the permission."
        ),
        tags=["Event Permissions"],
    ),
    create=extend_schema(
        summary="Create Event Permission",
        description=(
            "Create a new event permission with specified name, code, and category. "
            "Only administrators can create new permissions. "
            "Permissions define granular access controls for event operations."
        ),
        tags=["Event Permissions"],
    ),
    update=extend_schema(
        summary="Update Event Permission",
        description=(
            "Update an event permission with complete payload. "
            "Use PATCH for partial updates. Only administrators can update permissions."
        ),
        tags=["Event Permissions"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Permission",
        description=(
            "Partially update an event permission such as changing description or category. "
            "Only administrators can update permissions."
        ),
        tags=["Event Permissions"],
    ),
    destroy=extend_schema(
        summary="Delete Event Permission",
        description=(
            "Delete an event permission. Use with caution as this affects all assignments using this permission. "
            "Only administrators should delete permissions."
        ),
        tags=["Event Permissions"],
    )
)
class EventPermissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event permissions and access control definitions.
    
    Provides CRUD operations for event permissions that define what actions
    users can perform within events. Permissions are assigned to users through
    EventPermissionAssignment.
    """
    queryset = EventPermission.objects.all().order_by('name')
    serializer_class = EventPermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category']
    search_fields = ['name', 'code']


@extend_schema_view(
    list=extend_schema(
        summary="List Event Permission Assignments",
        description=(
            "Retrieve a paginated list of event permission assignments showing which users have which permissions for which events. "
            "Includes details about assigned user, permission, event, and the administrator who made the assignment. "
            "Supports filtering by event, user, and permission for targeted queries."
        ),
        tags=["Event Permission Assignments"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='user', type=OpenApiTypes.INT, description='Filter by user ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Permission Assignment Details",
        description=(
            "Retrieve detailed information about a specific permission assignment including "
            "user details, permission details, event context, assignment timestamp, and who made the assignment."
        ),
        tags=["Event Permission Assignments"],
    ),
    create=extend_schema(
        summary="Assign Event Permission",
        description=(
            "Assign a specific permission to a user for an event, granting them access to perform specific actions. "
            "Automatically records the authenticated user as the assigner. "
            "Only event managers and administrators can assign permissions."
        ),
        tags=["Event Permission Assignments"],
    ),
    update=extend_schema(
        summary="Update Event Permission Assignment",
        description=(
            "Update a permission assignment with complete payload. "
            "Use with caution as changing assignments affects user access. "
            "Only event managers and administrators can update assignments."
        ),
        tags=["Event Permission Assignments"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Permission Assignment",
        description=(
            "Partially update a permission assignment. "
            "Only event managers and administrators can update assignments."
        ),
        tags=["Event Permission Assignments"],
    ),
    destroy=extend_schema(
        summary="Remove Event Permission Assignment",
        description=(
            "Remove a permission assignment, revoking the user's access to perform the specific action. "
            "Immediately affects user's permissions for the event. "
            "Only event managers and administrators can remove assignments."
        ),
        tags=["Event Permission Assignments"],
    )
)
class EventPermissionAssignmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event permission assignments linking users, events, and permissions.
    
    Handles the assignment and revocation of permissions to users for specific events.
    Tracks who assigned the permission and when for audit purposes.
    """
    queryset = EventPermissionAssignment.objects.select_related(
        'event', 'user', 'permission', 'assigned_by'
    ).all()
    serializer_class = EventPermissionAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated, CannotTargetEventCreator]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = EventPermissionAssignmentFilterSet

    def perform_create(self, serializer):
        event = serializer.validated_data.get('event')
        user = serializer.validated_data.get('user')
        if event and user and user.id == event.created_by_id:
            raise PermissionDenied(CannotTargetEventCreator.message)
        serializer.save(assigned_by=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List Event Roles",
        description=(
            "Retrieve a paginated list of all available event roles that can be assigned to users. "
            "Roles group multiple permissions together for easier management and represent positions like organizer, volunteer, or coordinator. "
            "Supports filtering by category and searching by name or code."
        ),
        tags=["Event Roles"],
        parameters=[
            OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Filter by category'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Role Details",
        description=(
            "Retrieve detailed information about a specific event role including name, code, "
            "category, description, and associated permissions."
        ),
        tags=["Event Roles"],
    ),
    create=extend_schema(
        summary="Create Event Role",
        description=(
            "Create a new event role with specified name, code, category, and permissions. "
            "Only administrators can create new roles. "
            "Roles simplify permission management by grouping related permissions."
        ),
        tags=["Event Roles"],
    ),
    update=extend_schema(
        summary="Update Event Role",
        description=(
            "Update an event role with complete payload including permissions. "
            "Use PATCH for partial updates. Only administrators can update roles."
        ),
        tags=["Event Roles"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Role",
        description=(
            "Partially update an event role such as changing description or adding permissions. "
            "Only administrators can update roles."
        ),
        tags=["Event Roles"],
    ),
    destroy=extend_schema(
        summary="Delete Event Role",
        description=(
            "Delete an event role. Use with caution as this affects all assignments using this role. "
            "Only administrators should delete roles."
        ),
        tags=["Event Roles"],
    )
)
class EventRoleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event roles and role definitions.
    
    Provides CRUD operations for event roles that group permissions together.
    Roles represent positions or responsibilities within events and simplify
    permission management.
    """
    queryset = EventRole.objects.all()
    serializer_class = EventRoleSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category']
    search_fields = ['name', 'code']


@extend_schema_view(
    list=extend_schema(
        summary="List Event Role Assignments",
        description=(
            "Retrieve a paginated list of event role assignments showing which users have which roles for which events. "
            "Includes details about assigned user, role, event, and the administrator who made the assignment. "
            "Supports filtering by event, user, and role for targeted queries."
        ),
        tags=["Event Role Assignments"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='user', type=OpenApiTypes.INT, description='Filter by user ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Role Assignment Details",
        description=(
            "Retrieve detailed information about a specific role assignment including "
            "user details, role details with permissions, event context, assignment timestamp, and who made the assignment."
        ),
        tags=["Event Role Assignments"],
    ),
    create=extend_schema(
        summary="Assign Event Role",
        description=(
            "Assign a specific role to a user for an event, granting them all permissions associated with that role. "
            "Automatically records the authenticated user as the assigner. "
            "Only event managers and administrators can assign roles."
        ),
        tags=["Event Role Assignments"],
    ),
    update=extend_schema(
        summary="Update Event Role Assignment",
        description=(
            "Update a role assignment with complete payload. "
            "Use with caution as changing assignments affects user access. "
            "Only event managers and administrators can update assignments."
        ),
        tags=["Event Role Assignments"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Role Assignment",
        description=(
            "Partially update a role assignment. "
            "Only event managers and administrators can update assignments."
        ),
        tags=["Event Role Assignments"],
    ),
    destroy=extend_schema(
        summary="Remove Event Role Assignment",
        description=(
            "Remove a role assignment, revoking all permissions associated with that role for the user. "
            "Immediately affects user's permissions for the event. "
            "Only event managers and administrators can remove assignments."
        ),
        tags=["Event Role Assignments"],
    )
)
class EventRoleAssignmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event role assignments linking users, events, and roles.
    
    Handles the assignment and revocation of roles to users for specific events.
    Tracks who assigned the role and when for audit purposes.
    """
    queryset = EventRoleAssignment.objects.select_related(
        'event', 'user', 'role', 'assigned_by'
    ).all()
    serializer_class = EventRoleAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated, CannotTargetEventCreator]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = EventRoleAssignmentFilterSet

    def perform_create(self, serializer):
        event = serializer.validated_data.get('event')
        user = serializer.validated_data.get('user')
        if event and user and user.id == event.created_by_id:
            raise PermissionDenied(CannotTargetEventCreator.message)
        serializer.save(assigned_by=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List Event Staff",
        description=(
            "Retrieve a paginated list of event staff members across events. "
            "Includes user details, assignment information, availability, and role details. "
            "Supports filtering by event and user to find specific staff assignments."
        ),
        tags=["Event Staff"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Staff Details",
        description=(
            "Retrieve detailed information about a specific staff member including "
            "user profile, assignment details, availability windows, notes, and who assigned them."
        ),
        tags=["Event Staff"],
    ),
    create=extend_schema(
        summary="Add Staff Member to Event",
        description=(
            "Add a new staff member to an event with specified user and optional notes. "
            "Automatically records the authenticated user as the assigner. "
            "Only event managers and administrators can add staff members."
        ),
        tags=["Event Staff"],
    ),
    update=extend_schema(
        summary="Update Event Staff Member",
        description=(
            "Update a staff member's information with complete payload including notes and availability. "
            "Use PATCH for partial updates. Only event managers and administrators can update staff."
        ),
        tags=["Event Staff"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Staff Member",
        description=(
            "Partially update a staff member's information such as notes or availability. "
            "Only event managers and administrators can update staff."
        ),
        tags=["Event Staff"],
    ),
    destroy=extend_schema(
        summary="Remove Staff Member from Event",
        description=(
            "Remove a staff member from an event, revoking their staff status. "
            "Consider soft deletion if historical records are important. "
            "Only event managers and administrators can remove staff."
        ),
        tags=["Event Staff"],
    )
)
class EventStaffViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event staff assignments.
    
    Handles staff member assignments to events including availability tracking,
    role assignments, and notes. Provides comprehensive staff management for events.
    """
    queryset = EventStaff.objects.select_related(
        'event', 'user', 'assigned_by'
    ).prefetch_related('availabilities').all()
    serializer_class = EventStaffSerializer
    permission_classes = [permissions.IsAuthenticated, CannotTargetEventCreator]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = EventStaffFilterSet

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)

    def perform_destroy(self, instance):
        super().perform_destroy(instance)

        # also remove admin roles
        EventRoleAssignment.objects.filter(
            event=instance.event,
            user=instance.user
        ).delete()

        # also remove admin roles
        EventRoleAssignment.objects.filter(
            event=instance.event,
            user=instance.user
        ).delete()


@extend_schema_view(
    list=extend_schema(
        summary="List Event Staff Availability",
        description=(
            "Retrieve a paginated list of staff availability records defining when staff members are available. "
            "Each record specifies time windows when specific staff members can work. "
            "Supports filtering by staff member to view individual availability schedules."
        ),
        tags=["Event Staff Availability"],
        parameters=[
            OpenApiParameter(name='staff', type=OpenApiTypes.UUID, description='Filter by staff ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Staff Availability Details",
        description=(
            "Retrieve detailed information about a specific staff availability record including "
            "start and end times, staff member details, and any notes or constraints."
        ),
        tags=["Event Staff Availability"],
    ),
    create=extend_schema(
        summary="Create Staff Availability",
        description=(
            "Create a new staff availability record specifying when a staff member is available to work. "
            "Used for scheduling and resource allocation. "
            "Only event managers and administrators can create availability records."
        ),
        tags=["Event Staff Availability"],
    ),
    update=extend_schema(
        summary="Update Staff Availability",
        description=(
            "Update a staff availability record with complete payload including all time windows. "
            "Use PATCH for partial updates. Only event managers and administrators can update availability."
        ),
        tags=["Event Staff Availability"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Staff Availability",
        description=(
            "Partially update a staff availability record such as adjusting time windows. "
            "Only event managers and administrators can update availability."
        ),
        tags=["Event Staff Availability"],
    ),
    destroy=extend_schema(
        summary="Delete Staff Availability",
        description=(
            "Delete a staff availability record, removing the scheduled availability window. "
            "Affects scheduling and resource allocation. "
            "Only event managers and administrators can delete availability."
        ),
        tags=["Event Staff Availability"],
    )
)
class EventStaffAvailabilityViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event staff availability schedules.
    
    Tracks when staff members are available to work at events. Used for
    scheduling, shift planning, and resource allocation.
    """
    queryset = EventStaffAvailability.objects.select_related('staff').all()
    serializer_class = EventStaffAvailabilitySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['staff']


@extend_schema_view(
    list=extend_schema(
        operation_id='event_staff_invites_global_list',
        summary="List All Event Staff Invites",
        description=(
            "Retrieve a paginated list of all event staff invites across all events. "
            "This endpoint is primarily for administrative purposes and viewing invites globally. "
            "Users can filter to see only their own invites using the my-invites action."
        ),
        tags=["Event Staff Invites"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='target_user', type=OpenApiTypes.INT, description='Filter by target user ID'),
            OpenApiParameter(name='accepted', type=OpenApiTypes.BOOL, description='Filter by acceptance status'),
            OpenApiParameter(name='is_valid', type=OpenApiTypes.BOOL, description='Filter by validity status'),
        ]
    ),
)
class EventStaffInviteViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing event staff invites globally.
    
    Provides endpoints to view staff invites across all events with filtering capabilities.
    Includes special action for users to view their own pending invites.
    """
    queryset = EventStaffInvite.objects.select_related(
        'event', 'target_user', 'invited_by'
    ).all()
    serializer_class = EventStaffInviteListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = EventStaffInviteFilterSet
    search_fields = ['target_user__email', 'target_user__first_name', 'target_user__last_name']

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()
        
        # Non-staff users can only see their own invites
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            queryset = queryset.filter(target_user=self.request.user)
        
        # Apply is_valid filter if provided
        is_valid_param = self.request.query_params.get('is_valid')
        if is_valid_param is not None:
            if is_valid_param.lower() in ['true', '1', 'yes']:
                queryset = queryset.filter(
                    is_active=True,
                    accepted=False
                ).filter(
                    Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
                )
            else:
                # Invalid invites
                queryset = queryset.filter(
                    Q(is_active=False) | 
                    Q(accepted=True) | 
                    Q(expires_at__lt=timezone.now())
                )
        
        return queryset.order_by('-added_at')
    
    @extend_schema(
        operation_id='event_staff_invites_my_invites',
        summary="Get My Event Staff Invites",
        description=(
            "Retrieve all event staff invites for the authenticated user across all events. "
            "This endpoint allows users to see all events they've been invited to staff.\n\n"
            "**Filtering Options:**\n"
            "- `accepted`: Filter by acceptance status (true/false)\n"
            "- `is_valid`: Filter by validity status - valid invites are active, not expired, and not accepted\n\n"
            "**Common Use Cases:**\n"
            "- Get pending invites: `?is_valid=true&accepted=false`\n"
            "- Get accepted invites: `?accepted=true`\n"
            "- Get all invites: no filters\n\n"
            "Results include:\n"
            "- Event details (title, display code, dates)\n"
            "- Invite status (active, accepted, expired)\n"
            "- Inviter information\n"
            "- Expiry date (if applicable)\n"
            "- HATEOAS links for acceptance and viewing event details"
        ),
        tags=["Event Staff Invites"],
        parameters=[
            OpenApiParameter(
                name='accepted',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter by acceptance status. true=accepted, false=not accepted',
                required=False
            ),
            OpenApiParameter(
                name='is_valid',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description=(
                    'Filter by validity status. Valid invites are: active, not expired, and not yet accepted. '
                    'Use true to get only valid (pending) invites, false to get invalid invites'
                ),
                required=False
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Page number for pagination',
                required=False
            ),
            OpenApiParameter(
                name='page_size',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Number of results per page (default: 20)',
                required=False
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=EventStaffInviteListSerializer(many=True),
                description=(
                    'Successfully retrieved list of invites. Returns paginated results with invite summaries for all events.'
                )
            ),
            401: OpenApiResponse(
                description='Authentication required. User must be logged in to view their invites'
            ),
        }
    )
    @action(detail=False, methods=['get'], url_path='my-invites',
            permission_classes=[permissions.IsAuthenticated])
    def my_invites(self, request):
        """Get all staff invites for the authenticated user across all events."""
        queryset = EventStaffInvite.objects.filter(
            target_user=request.user
        ).select_related('event', 'invited_by').order_by('-added_at')
        
        # Apply filters
        accepted = request.query_params.get('accepted')
        if accepted is not None:
            queryset = queryset.filter(accepted=accepted.lower() in ['true', '1', 'yes'])
        
        is_valid_param = request.query_params.get('is_valid')
        if is_valid_param is not None:
            if is_valid_param.lower() in ['true', '1', 'yes']:
                queryset = queryset.filter(
                    is_active=True,
                    accepted=False
                ).filter(
                    Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
                )
            else:
                # Invalid invites
                queryset = queryset.filter(
                    Q(is_active=False) | 
                    Q(accepted=True) | 
                    Q(expires_at__lt=timezone.now())
                )
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EventStaffInviteListSerializer(
                page, many=True, 
                context={'request': request}
            )
            return self.get_paginated_response(serializer.data)
        
        serializer = EventStaffInviteListSerializer(
            queryset, many=True,
            context={'request': request}
        )
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="List Event Reviews",
        description=(
            "Retrieve a paginated list of event reviews submitted by attendees. "
            "Reviews include ratings, comments, and approval status for moderation. "
            "Supports filtering by event and approval status to manage review visibility."
        ),
        tags=["Event Reviews"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='approved', type=OpenApiTypes.BOOL, description='Filter by approval status'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Review Details",
        description=(
            "Retrieve detailed information about a specific event review including "
            "rating, comment, reviewer details, submission time, and approval status."
        ),
        tags=["Event Reviews"],
    ),
    create=extend_schema(
        summary="Create Event Review",
        description=(
            "Create a new event review with rating and optional comment. "
            "Reviews require approval before being publicly visible. "
            "Only authenticated users who attended the event can create reviews."
        ),
        tags=["Event Reviews"],
    ),
    update=extend_schema(
        summary="Update Event Review",
        description=(
            "Update an event review with complete payload including rating and comment. "
            "Use PATCH for partial updates. Only the review author can update their review."
        ),
        tags=["Event Reviews"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Review",
        description=(
            "Partially update an event review such as changing rating or editing comment. "
            "Only the review author can update their review."
        ),
        tags=["Event Reviews"],
    ),
    destroy=extend_schema(
        summary="Delete Event Review",
        description=(
            "Delete an event review permanently. "
            "Only the review author or administrators can delete reviews."
        ),
        tags=["Event Reviews"],
    )
)
class EventReviewViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event reviews and ratings.
    
    Handles review submission, moderation, and publication. Reviews require
    approval before being publicly visible to maintain content quality.
    """
    queryset = EventReview.objects.select_related('event', 'user').all()
    serializer_class = EventReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventReviewFilterSet
    ordering_fields = ['created_at', 'rating']
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(approved=True)
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @extend_schema(
        summary="Approve Event Review",
        description=(
            "Approve a specific review making it publicly visible. "
            "Only staff and administrators can approve reviews. "
            "Approved reviews are displayed on event pages and contribute to event ratings."
        ),
        tags=["Event Reviews"],
        responses={
            200: EventReviewSerializer,
        }
    )
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        review = self.get_object()
        review.approved = True
        review.save()
        serializer = self.get_serializer(review)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="List Event Questions",
        description=(
            "Retrieve a paginated list of event questions used for registration forms and surveys. "
            "Questions can be various types (text, multiple choice, rating, etc.) and are displayed to attendees during registration. "
            "Supports filtering by event, question type, required status, and public visibility. Ordered by question order."
        ),
        tags=["Event Questions"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='question_type', type=OpenApiTypes.STR, description='Filter by question type'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Question Details",
        description=(
            "Retrieve detailed information about a specific event question including "
            "question text, type, options, validation rules, and display settings."
        ),
        tags=["Event Questions"],
    ),
    create=extend_schema(
        summary="Create Event Question",
        description=(
            "Create a new event question for registration forms or surveys. "
            "Specify question type, text, required status, and options if applicable. "
            "Only event managers and administrators can create questions."
        ),
        tags=["Event Questions"],
    ),
    update=extend_schema(
        summary="Update Event Question",
        description=(
            "Update an event question with complete payload including all options. "
            "Use PATCH for partial updates. Only event managers and administrators can update questions."
        ),
        tags=["Event Questions"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question",
        description=(
            "Partially update an event question such as changing text or required status. "
            "Only event managers and administrators can update questions."
        ),
        tags=["Event Questions"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question",
        description=(
            "Delete an event question. Use with caution as this removes all associated answers. "
            "Only event managers and administrators can delete questions."
        ),
        tags=["Event Questions"],
    )
)
class EventQuestionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event questions for registration forms and surveys.
    
    Provides CRUD operations for creating custom questions that attendees
    answer during registration. Supports various question types and validation.
    """
    queryset = EventQuestion.objects.select_related('event').prefetch_related('options').all()
    serializer_class = EventQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventQuestionFilterSet
    ordering_fields = ['order', 'created_at']
    ordering = ['order']
    
    def perform_create(self, serializer):
        """Create question and broadcast to WebSocket clients."""
        from apps.events.utils.websocket import broadcast_question_event_sync
        from apps.events.api.serializers import EventQuestionSerializer
        import logging
        import json
        from django.core.serializers.json import DjangoJSONEncoder
        
        logger = logging.getLogger(__name__)
        
        # Save the question
        instance = serializer.save()
        
        # Get actor object (not just email)
        actor = None
        if self.request.user and self.request.user.is_authenticated:
            actor = {
                'id': self.request.user.id,
                'email': self.request.user.email,
                'name': getattr(self.request.user, 'get_full_name', lambda: None)() or self.request.user.email
            }
        
        logger.info(f"[EventQuestionViewSet] Created question {instance.id} by {actor.get('email') if actor else 'unknown'}")
        
        # Serialize for broadcast (refetch to include options)
        instance.refresh_from_db()
        broadcast_serializer = EventQuestionSerializer(instance)
        question_data = json.loads(json.dumps(broadcast_serializer.data, cls=DjangoJSONEncoder))
        
        # Broadcast to WebSocket clients
        broadcast_question_event_sync(
            event_id=str(instance.event.event_id),
            event_type="question.created",
            question_data=question_data,
            actor=actor
        )
        
        logger.info(f"[EventQuestionViewSet] Broadcasted question.created for {instance.id} with actor: {actor}")
        
    def perform_update(self, serializer):
        """Update question and broadcast to WebSocket clients."""
        from apps.events.utils.websocket import broadcast_question_event_sync
        from apps.events.api.serializers import EventQuestionSerializer
        import logging
        import json
        from django.core.serializers.json import DjangoJSONEncoder
        
        logger = logging.getLogger(__name__)
        
        # Save the question
        instance = serializer.save()
        
        # Get actor object (not just email)
        actor = None
        if self.request.user and self.request.user.is_authenticated:
            actor = {
                'id': self.request.user.id,
                'email': self.request.user.email,
                'name': getattr(self.request.user, 'get_full_name', lambda: None)() or self.request.user.email
            }
        
        logger.info(f"[EventQuestionViewSet] Updated question {instance.id} by {actor.get('email') if actor else 'unknown'}")
        
        # Serialize for broadcast (refetch to include options)
        instance.refresh_from_db()
        broadcast_serializer = EventQuestionSerializer(instance)
        question_data = json.loads(json.dumps(broadcast_serializer.data, cls=DjangoJSONEncoder))
        
        # Broadcast to WebSocket clients
        broadcast_question_event_sync(
            event_id=str(instance.event.event_id),
            event_type="question.updated",
            question_data=question_data,
            actor=actor
        )
        
        logger.info(f"[EventQuestionViewSet] Broadcasted question.updated for {instance.id} with actor: {actor}")
    
    def perform_destroy(self, instance):
        """Delete question and broadcast to WebSocket clients."""
        from apps.events.utils.websocket import broadcast_question_event_sync
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Get data before deletion
        event_id = str(instance.event.event_id)
        question_id = str(instance.id)
        
        # Get actor object (not just email)
        actor = None
        if self.request.user and self.request.user.is_authenticated:
            actor = {
                'id': self.request.user.id,
                'email': self.request.user.email,
                'name': getattr(self.request.user, 'get_full_name', lambda: None)() or self.request.user.email
            }
        
        logger.info(f"[EventQuestionViewSet] Deleting question {question_id} by {actor.get('email') if actor else 'unknown'}")
        
        # Delete the question
        instance.delete()
        
        # Broadcast deletion
        broadcast_question_event_sync(
            event_id=event_id,
            event_type="question.deleted",
            question_data={
                "id": question_id,
                "event": event_id,
            },
            actor=actor
        )        
        logger.info(f"[EventQuestionViewSet] Broadcasted question.deleted for {question_id} with actor: {actor}")
        
    @extend_schema(
        summary="Bulk Create Questions",
        description=(
            "Create multiple event questions in a single request with nested options. "
            "All questions are validated before any are created (all-or-nothing). "
            "Useful for importing pre-built forms or creating entire sections at once. "
            "\n\n**Features:**\n"
            "- Atomic transaction: all questions created or none\n"
            "- Supports nested options for choice questions\n"
            "- Validates all questions before creating any\n"
            "- Returns all created questions with IDs\n"
            "\n\n**Request Format:**\n"
            "Array of question objects, each with:\n"
            "- event: Event UUID\n"
            "- question_title: String\n"
            "- question_body: String\n"
            "- question_type: Choice type\n"
            "- required: Boolean (optional)\n"
            "- order: Integer (optional)\n"
            "- options: Array of {option_text, order} (for choice questions)\n"
        ),
        tags=["Event Questions"],
        request={
            'application/json': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'event': {'type': 'string', 'format': 'uuid'},
                        'question_title': {'type': 'string'},
                        'question_body': {'type': 'string'},
                        'question_type': {'type': 'string'},
                        'required': {'type': 'boolean'},
                        'order': {'type': 'integer'},
                        'options': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'option_text': {'type': 'string'},
                                    'order': {'type': 'integer'}
                                }
                            }
                        }
                    }
                }
            }
        },
        responses={
            201: EventQuestionSerializer(many=True),
            400: OpenApiResponse(description='Validation errors in one or more questions')
        }
    )
    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        """
        Bulk create multiple questions with nested options atomically.
        """
        from django.db import transaction
        
        if not isinstance(request.data, list):
            return Response(
                {'detail': 'Request data must be an array of questions'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate all questions first
        serializers_list = []
        for question_data in request.data:
            serializer = EventQuestionSerializer(data=question_data, context={'request': request})
            if not serializer.is_valid():
                return Response(
                    {
                        'detail': 'Validation failed',
                        'errors': serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            serializers_list.append(serializer)
        
        # All valid - create atomically
        created_questions = []
        with transaction.atomic():
            for serializer in serializers_list:
                question = serializer.save()
                created_questions.append(question)
        
        # Return all created questions
        output_serializer = EventQuestionSerializer(
            created_questions,
            many=True,
            context={'request': request}
        )
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Reorder Questions",
        description=(
            "Update the display order of multiple questions in a single atomic operation. "
            "Useful for drag-and-drop reordering in form builders. "
            "\n\n**Features:**\n"
            "- Atomic transaction: all orders updated or none\n"
            "- Validates all question IDs exist and belong to same event\n"
            "- Handles unique constraint by updating in correct sequence\n"
            "- Broadcasts update via WebSocket after success\n"
            "\n\n**Request Format:**\n"
            "```json\n"
            "{\n"
            '  "questions": [\n'
            '    {"id": "uuid1", "order": 0},\n'
            '    {"id": "uuid2", "order": 1},\n'
            '    {"id": "uuid3", "order": 2}\n'
            "  ]\n"
            "}\n"
            "```"
        ),
        tags=["Event Questions"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'questions': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'string', 'format': 'uuid'},
                                'order': {'type': 'integer'}
                            },
                            'required': ['id', 'order']
                        }
                    }
                },
                'required': ['questions']
            }
        },
        responses={
            200: OpenApiResponse(description='Questions reordered successfully'),
            400: OpenApiResponse(description='Validation errors')
        }
    )
    @action(detail=False, methods=['post'], url_path='reorder')
    def reorder(self, request):
        """
        Reorder questions atomically.
        """
        from django.db import transaction
        from apps.events.utils.websocket import broadcast_question_event_sync
        import uuid
        
        questions_data = request.data.get('questions', [])
        
        if not questions_data:
            return Response(
                {'detail': 'questions array is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Extract and validate question IDs
            question_ids = [item['id'] for item in questions_data]
            
            # Fetch all questions
            questions = EventQuestion.objects.filter(id__in=question_ids)
            
            if questions.count() != len(question_ids):
                return Response(
                    {'detail': 'One or more question IDs not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Verify all questions belong to the same event
            event_ids = questions.values_list('event_id', flat=True).distinct()
            if len(event_ids) > 1:
                return Response(
                    {'detail': 'All questions must belong to the same event'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get event for broadcasting
            event_id = str(event_ids[0]) if event_ids else None
            
            # Update orders atomically
            with transaction.atomic():
                # Create a mapping of ID to order
                order_map = {item['id']: item['order'] for item in questions_data}
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[EventQuestionViewSet] Reordering questions for event {event_id} with order map: {order_map}")
                # Update each question's order
                for question in questions:
                    question.order = order_map[str(question.id)]
                    question.save(update_fields=['order'])
            
            # Broadcast reorder event to WebSocket clients
            if event_id:
                actor = None
                if request.user and request.user.is_authenticated:
                    actor = {
                        'id': request.user.id,
                        'email': request.user.email,
                        'name': request.user.get_full_name() or request.user.email,
                    }
                
                broadcast_question_event_sync(
                    event_id=event_id,
                    event_type='question.reordered',
                    question_data={'question_ids': question_ids},
                    actor=actor
                )
            
            return Response({'message': 'Questions reordered successfully'})
        
        except KeyError as e:
            return Response(
                {'detail': f'Missing required field: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'detail': f'Error reordering questions: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema_view(
    list=extend_schema(
        summary="List Event Question Options",
        description=(
            "Retrieve a paginated list of question options for multiple choice and dropdown questions. "
            "Options define the available choices attendees can select when answering questions. "
            "Supports filtering by question to view all options for a specific question."
        ),
        tags=["Event Question Options"],
        parameters=[
            OpenApiParameter(name='question', type=OpenApiTypes.UUID, description='Filter by question ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Question Option Details",
        description=(
            "Retrieve detailed information about a specific question option including "
            "option text, value, display order, and associated question."
        ),
        tags=["Event Question Options"],
    ),
    create=extend_schema(
        summary="Create Event Question Option",
        description=(
            "Create a new option for a multiple choice or dropdown question. "
            "Specify option text, value, and display order. "
            "Only event managers and administrators can create options."
        ),
        tags=["Event Question Options"],
    ),
    update=extend_schema(
        summary="Update Event Question Option",
        description=(
            "Update a question option with complete payload. "
            "Use PATCH for partial updates. Only event managers and administrators can update options."
        ),
        tags=["Event Question Options"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question Option",
        description=(
            "Partially update a question option such as changing text or order. "
            "Only event managers and administrators can update options."
        ),
        tags=["Event Question Options"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question Option",
        description=(
            "Delete a question option. Affects questions using this option. "
            "Only event managers and administrators can delete options."
        ),
        tags=["Event Question Options"],
    )
)
class EventQuestionOptionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event question options for multiple choice questions.
    
    Provides CRUD operations for creating and managing options that attendees
    can select when answering multiple choice or dropdown questions.
    """
    queryset = EventQuestionOption.objects.select_related('question').all()
    serializer_class = EventQuestionOptionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['question']


@extend_schema_view(
    list=extend_schema(
        summary="List Event Question Answers",
        description=(
            "Retrieve a paginated list of answers submitted by attendees for event questions. "
            "Answers can be text responses, numeric values, or multiple choice selections. "
            "Supports filtering by question and attendee to view specific responses."
        ),
        tags=["Event Question Answers"],
        parameters=[
            OpenApiParameter(name='question', type=OpenApiTypes.UUID, description='Filter by question ID'),
            OpenApiParameter(name='attendee', type=OpenApiTypes.INT, description='Filter by attendee ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Question Answer Details",
        description=(
            "Retrieve detailed information about a specific answer including "
            "answer text, numeric value, selected options, attendee details, and submission time."
        ),
        tags=["Event Question Answers"],
    ),
    create=extend_schema(
        summary="Submit Event Question Answer",
        description=(
            "Submit a new answer to an event question during registration or survey completion. "
            "Answer format depends on question type (text, number, multiple choice, etc.). "
            "Validates answer against question requirements and constraints."
        ),
        tags=["Event Question Answers"],
    ),
    update=extend_schema(
        summary="Update Event Question Answer",
        description=(
            "Update an existing answer with complete payload. "
            "Use PATCH for partial updates. Attendees can update their own answers."
        ),
        tags=["Event Question Answers"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question Answer",
        description=(
            "Partially update an answer such as changing text or selection. "
            "Attendees can update their own answers."
        ),
        tags=["Event Question Answers"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question Answer",
        description=(
            "Delete an answer. Use with caution as this removes attendee response data. "
            "Only attendees or administrators can delete answers."
        ),
        tags=["Event Question Answers"],
    )
)
class EventQuestionAnswerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event question answers submitted by attendees.
    
    Handles answer submission, updates, and retrieval. Validates answers
    against question constraints and supports various answer types.
    """
    queryset = EventQuestionAnswer.objects.select_related(
        'question', 'attendee'
    ).prefetch_related('selected_options').all()
    serializer_class = EventQuestionAnswerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = EventQuestionAnswerFilterSet

    @extend_schema(
        summary="Upload Event Question File",
        description=(
            "Upload a file or image to be used as an answer for upload-type event questions. "
            "This endpoint stores the upload as a generic Resource linked to the event and "
            "returns the resource reference for use in checkout payloads. "
            "Use the returned resource ID in checkout as upload_resource_id."
        ),
        tags=["Event Question Answers"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'event_id': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'Event UUID the upload belongs to'
                    },
                    'name': {
                        'type': 'string',
                        'description': 'Optional name for the resource (defaults to file name)'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Optional description for the upload'
                    },
                    'resource_type': {
                        'type': 'string',
                        'enum': ['DOCUMENT', 'IMAGE', 'OTHER'],
                        'description': 'Resource type (DOCUMENT for files, IMAGE for images)'
                    },
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'File upload for DOCUMENT/OTHER types'
                    },
                    'image': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Image upload for IMAGE type'
                    }
                },
                'required': ['event_id']
            }
        },
        responses={
            201: ResourceSerializer,
            400: OpenApiResponse(description='Validation errors'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(
        detail=False,
        methods=['post'],
        url_path='upload',
        permission_classes=[permissions.IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser]
    )
    def upload(self, request):
        event_id = request.data.get('event_id')
        if not event_id:
            return Response(
                {'detail': 'event_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event = get_object_or_404(Event, event_id=event_id)

        resource_type = request.data.get('resource_type', 'DOCUMENT')
        resource_type = resource_type.upper()
        if resource_type not in ['DOCUMENT', 'IMAGE', 'OTHER']:
            return Response(
                {'detail': 'resource_type must be DOCUMENT, IMAGE, or OTHER'},
                status=status.HTTP_400_BAD_REQUEST
            )

        upload_file = request.FILES.get('file')
        upload_image = request.FILES.get('image')

        if resource_type == 'IMAGE' and not upload_image:
            return Response(
                {'detail': 'image file is required for IMAGE resource type'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if resource_type in ['DOCUMENT', 'OTHER'] and not upload_file:
            return Response(
                {'detail': 'file is required for DOCUMENT/OTHER resource types'},
                status=status.HTTP_400_BAD_REQUEST
            )

        name = request.data.get('name')
        if not name:
            name = upload_image.name if upload_image else upload_file.name

        serializer_data = {
            'name': name,
            'description': request.data.get('description', ''),
            'resource_type': resource_type,
            'public': False,
        }

        if upload_image:
            serializer_data['image'] = upload_image
        if upload_file:
            serializer_data['file'] = upload_file

        serializer = ResourceSerializer(data=serializer_data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        content_type = ContentType.objects.get_for_model(Event)
        resource = serializer.save(
            target_type=content_type,
            target_id=event.id,
            added_by=request.user,
            tag='QUESTION_UPLOAD'
        )

        return Response(
            ResourceSerializer(resource, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )
    
    @extend_schema(
        summary="Submit Form (Batch Answers)",
        description=(
            "Submit all answers for a registration form in a single atomic transaction. "
            "Validates that all required questions are answered and creates all answers atomically. "
            "\n\n**Features:**\n"
            "- Atomic transaction: all answers created or none\n"
            "- Validates all required questions are answered\n"
            "- Supports text answers and option selections\n"
            "- Bulk creates all answers and choices\n"
            "- Returns complete submission with any validation errors\n"
            "\n\n**Request Format:**\n"
            "```json\n"
            "{\n"
            '  "attendee": 123,\n'
            '  "answers": [\n'
            "    {\n"
            '      "question": "uuid1",\n'
            '      "answer_text": "My answer",\n'
            '      "selected_option_ids": []\n'
            "    },\n"
            "    {\n"
            '      "question": "uuid2",\n'
            '      "answer_text": "",\n'
            '      "selected_option_ids": [1, 2]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
        ),
        tags=["Event Question Answers"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'attendee': {'type': 'integer'},
                    'answers': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'question': {'type': 'string', 'format': 'uuid'},
                                'answer_text': {'type': 'string'},
                                'selected_option_ids': {
                                    'type': 'array',
                                    'items': {'type': 'integer'}
                                }
                            },
                            'required': ['question']
                        }
                    }
                },
                'required': ['attendee', 'answers']
            }
        },
        responses={
            201: EventQuestionAnswerSerializer(many=True),
            400: OpenApiResponse(description='Validation errors or missing required answers')
        }
    )
    @action(detail=False, methods=['post'], url_path='submit-form')
    def submit_form(self, request):
        """
        Submit all form answers in a single atomic transaction.
        """
        from django.db import transaction
        
        attendee_id = request.data.get('attendee')
        answers_data = request.data.get('answers', [])
        
        if not attendee_id:
            return Response(
                {'detail': 'attendee is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not answers_data:
            return Response(
                {'detail': 'answers array is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get all question IDs from answers
            question_ids = [answer['question'] for answer in answers_data]
            
            # Fetch all questions
            questions = EventQuestion.objects.filter(id__in=question_ids).prefetch_related('options')
            questions_dict = {str(q.id): q for q in questions}
            
            # Check if all questions exist
            if len(questions_dict) != len(question_ids):
                missing = set(question_ids) - set(questions_dict.keys())
                return Response(
                    {'detail': f'Questions not found: {missing}'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get event from first question (all should be same event)
            first_question = next(iter(questions_dict.values()))
            event = first_question.event
            
            # Get all required questions for this event
            all_event_questions = event.questions.all()
            required_question_ids = set(
                str(q.id) for q in all_event_questions if q.required
            )
            answered_question_ids = set(question_ids)
            
            # Check if all required questions are answered
            missing_required = required_question_ids - answered_question_ids
            if missing_required:
                return Response(
                    {
                        'detail': 'Missing required questions',
                        'missing_question_ids': list(missing_required)
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate all answers
            validated_answers = []
            for answer_data in answers_data:
                # Add attendee to each answer
                answer_data['attendee'] = attendee_id
                
                serializer = EventQuestionAnswerSerializer(
                    data=answer_data,
                    context={'request': request}
                )
                
                if not serializer.is_valid():
                    return Response(
                        {
                            'detail': 'Validation failed',
                            'errors': serializer.errors,
                            'question': answer_data.get('question')
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                validated_answers.append(serializer)
            
            # All valid - create atomically
            created_answers = []
            with transaction.atomic():
                for serializer in validated_answers:
                    answer = serializer.save()
                    created_answers.append(answer)
            
            # Return all created answers
            output_serializer = EventQuestionAnswerSerializer(
                created_answers,
                many=True,
                context={'request': request}
            )
            return Response(output_serializer.data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response(
                {'detail': f'Error submitting form: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema_view(
    list=extend_schema(
        summary="List Event Question Answer Choices",
        description=(
            "Retrieve a paginated list of answer choices representing specific option selections for multiple choice answers. "
            "Each choice links an answer to a specific option that was selected. "
            "Used for tracking individual selections in multi-select questions."
        ),
        tags=["Event Question Answer Choices"],
    ),
    retrieve=extend_schema(
        summary="Get Event Question Answer Choice Details",
        description=(
            "Retrieve detailed information about a specific answer choice including "
            "the answer, selected option, and related question context."
        ),
        tags=["Event Question Answer Choices"],
    ),
    create=extend_schema(
        summary="Create Event Question Answer Choice",
        description=(
            "Create a new answer choice linking an answer to a selected option. "
            "Used when attendees select options in multiple choice questions. "
            "Automatically validated against available options."
        ),
        tags=["Event Question Answer Choices"],
    ),
    update=extend_schema(
        summary="Update Event Question Answer Choice",
        description=(
            "Update an answer choice. Rarely used as choices are typically created or deleted. "
            "Use with caution as this affects attendee responses."
        ),
        tags=["Event Question Answer Choices"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question Answer Choice",
        description=(
            "Partially update an answer choice. "
            "Use with caution as this affects attendee responses."
        ),
        tags=["Event Question Answer Choices"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question Answer Choice",
        description=(
            "Delete an answer choice, removing an option selection from an answer. "
            "Used when attendees change their multiple choice selections."
        ),
        tags=["Event Question Answer Choices"],
    )
)
class EventQuestionAnswerChoiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event question answer choices for multiple choice answers.
    
    Handles the individual option selections within multiple choice answers.
    Each choice represents one selected option in a multiple choice question.
    """
    queryset = EventQuestionAnswerChoice.objects.select_related('answer', 'option').all()
    serializer_class = EventQuestionAnswerChoiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['answer']


@extend_schema_view(
    list=extend_schema(
        summary="List Event Venues",
        description=(
            "Retrieve a paginated list of all event-venue associations showing which venues host which events. "
            "Includes venue details, points of interest, and event information. "
            "Supports filtering by event or venue and searching by event title or venue name."
        ),
        tags=["Event Venues"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='venue', type=OpenApiTypes.INT, description='Filter by venue ID'),
            OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search by event title or venue name'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Venue Details",
        description=(
            "Retrieve detailed information about a specific event-venue association including "
            "venue facilities, location, capacity, and event-specific venue configurations."
        ),
        tags=["Event Venues"],
    ),
    create=extend_schema(
        summary="Create Event Venue Association",
        description=(
            "Associate a venue with an event, specifying where the event will be held. "
            "Can include event-specific venue details and configurations. "
            "Only event managers and administrators can create venue associations."
        ),
        tags=["Event Venues"],
    ),
    update=extend_schema(
        summary="Update Event Venue Association",
        description=(
            "Update an event-venue association with complete payload. "
            "Use PATCH for partial updates. Only event managers and administrators can update associations."
        ),
        tags=["Event Venues"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Venue Association",
        description=(
            "Partially update an event-venue association such as changing configurations. "
            "Only event managers and administrators can update associations."
        ),
        tags=["Event Venues"],
    ),
    destroy=extend_schema(
        summary="Delete Event Venue Association",
        description=(
            "Remove a venue association from an event. "
            "Use when changing event location or removing venue assignment. "
            "Only event managers and administrators can delete associations."
        ),
        tags=["Event Venues"],
    )
)
class EventVenueViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing EventVenue associations linking events to physical venues.
    
    Provides CRUD operations for associating venues with events and managing
    venue-specific configurations for events.
    """
    queryset = EventVenue.objects.select_related(
        'event', 'venue', 'venue__poi'
    ).all()
    serializer_class = EventVenueSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventVenueFilterSet
    search_fields = ['event__title', 'event__display_code', 'venue__poi__name', 'venue__poi__city']
    ordering_fields = ['event__start_datetime', 'venue__poi__name']
    ordering = ['-event__start_datetime']
    lookup_field = 'event_venue_id'

