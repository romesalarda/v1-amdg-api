"""
Production-grade viewsets for the bookings app.

Provides comprehensive viewsets for booking management with proper validation,
business logic separation, schema configuration, nested routes, and permission classes.

ViewSets:
    - BookingViewSet: Full CRUD for bookings with nested attendees and tickets routes
    - TicketTypeViewSet: Manage ticket types
    - TicketViewSet: Read-only ticket viewing (tickets created server-side)
    - BookingPackageViewSet: Manage booking packages with eligibility checks
    - EventAlternativeSigninViewSet: Admin-only management of event alternative signins
    - AttendeeAlternativeSigninViewSet: Admin-only management of attendee alternative signins

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any

from apps.bookings.models import (
    Booking, BookingIntent, BookingIntentStatusChoices,
    BookingPackage, BookingPackageRule,
    TicketType, Ticket,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
)
from .serializers import (
    BookingListSerializer, BookingDetailSerializer, BookingCreateSerializer, BookingUpdateSerializer,
    BookingIntentListSerializer, BookingIntentDetailSerializer, BookingIntentCreateSerializer, BookingIntentUpdateSerializer,
    TicketTypeListSerializer, TicketTypeDetailSerializer, TicketTypeCreateUpdateSerializer,
    TicketListSerializer, TicketDetailSerializer,
    BookingPackageListSerializer, BookingPackageDetailSerializer, BookingPackageCreateUpdateSerializer,
    BookingPackageRuleSerializer, BookingPackageRuleCreateUpdateSerializer,
    EventAlternativeSigninListSerializer, EventAlternativeSigninDetailSerializer, EventAlternativeSigninCreateUpdateSerializer,
    AttendeeAlternativeSigninListSerializer, AttendeeAlternativeSigninDetailSerializer, AttendeeAlternativeSigninCreateUpdateSerializer,
)
from .filtersets import (
    BookingFilterSet, BookingIntentFilterSet,
    TicketFilterSet, TicketTypeFilterSet, BookingPackageFilterSet,
    EventAlternativeSigninFilterSet, AttendeeAlternativeSigninFilterSet,
)
from .permissions import (
    IsAdministrativeStaff, IsAdministrativeStaffOnly, IsBookingOwnerOrAdministrative,
    IsTicketOwnerOrAdministrative, IsReadOnly,
)


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration for booking endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================================
# BOOKING VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List bookings",
        description="Retrieve a paginated list of bookings. Users see their own bookings, admins see all.",
        tags=["Bookings"],
    ),
    retrieve=extend_schema(
        summary="Retrieve booking details",
        description="Get detailed information about a specific booking including attendees, tickets, and payments.",
        tags=["Bookings"],
    ),
    create=extend_schema(
        summary="Create booking",
        description="Create a new booking for an event. Booking reference is auto-generated. Requires a valid booking intent ID passed as query parameter 'intent'. The intent must be pending, not expired, and belong to the requesting user. Admin users can bypass this requirement.",
        tags=["Bookings"],
        parameters=[
            OpenApiParameter(
                name='intent',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='UUID of the booking intent. Required for non-admin users.',
                required=False,
            ),
        ],
    ),
    update=extend_schema(
        summary="Update booking",
        description="Update an existing booking. Only certain fields can be modified.",
        tags=["Bookings"],
    ),
    partial_update=extend_schema(
        summary="Partially update booking",
        description="Partially update a booking. Only certain fields can be modified.",
        tags=["Bookings"],
    ),
    destroy=extend_schema(
        summary="Delete booking",
        description="Delete a booking. Only allowed if no tickets have been issued.",
        tags=["Bookings"],
    ),
)
class BookingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing bookings.
    
    Provides:
    - List/Retrieve: Users see their own bookings, admins see all
    - Create: Create new bookings (auto-generates reference)
    - Nested routes: /bookings/{id}/attendees/ and /bookings/{id}/tickets/
    
    Permissions:
    - List/Create: Authenticated users
    - Retrieve/Update/Delete: Booking owner or administrative staff
    """
    
    queryset = Booking.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingFilterSet
    search_fields = ['booking_reference', 'attendees__first_name', 'attendees__last_name', 'attendees__email']
    ordering_fields = ['booked_at', 'booking_reference']
    ordering = ['-booked_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return BookingListSerializer
        elif self.action == 'create':
            return BookingCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BookingUpdateSerializer
        return BookingDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action == 'create':
            return [permissions.IsAuthenticated()]
        elif self.action in ['retrieve', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsBookingOwnerOrAdministrative()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions.
        
        Regular users see only their own bookings.
        Admins see all bookings.
        """
        user = self.request.user
        queryset = super().get_queryset()
        
        # Optimize with select_related and prefetch_related
        queryset = queryset.select_related('event', 'made_by').prefetch_related('attendees')
        
        # If user is superuser or staff, return all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_events = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)
        
        # Return bookings made by user or for events they administer
        return queryset.filter(
            Q(made_by=user) |
            Q(attendees__user=user) |
            Q(event_id__in=admin_events)
        ).distinct()
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.event
            except:
                pass
        return context
    
    def perform_create(self, serializer):
        """
        Create booking with intent validation.
        
        Validates that a valid booking intent is provided (unless user is admin).
        The intent must be:
        - Pending status
        - Not expired
        - Belonging to the requesting user
        - For the same event as the booking
        - Have sufficient capacity
        
        After successful creation, marks the intent as completed.
        """
        user = self.request.user
        intent_id = self.request.query_params.get('intent')
        
        # Admin bypass: superusers and staff can create bookings without intent
        is_admin = user.is_superuser or user.is_staff
        
        if not is_admin:
            # Non-admin users must provide a valid intent
            if not intent_id:
                raise ValidationError({
                    'intent': 'A valid booking intent is required to create a booking. Please create a booking intent first.'
                })
            
            # Validate and retrieve the intent
            try:
                intent = BookingIntent.objects.get(booking_intent_id=intent_id)
            except BookingIntent.DoesNotExist:
                raise ValidationError({
                    'intent': f'Booking intent with ID {intent_id} does not exist.'
                })
            
            # Validate intent status
            if intent.status != BookingIntentStatusChoices.PENDING:
                raise ValidationError({
                    'intent': f'Booking intent must be in PENDING status. Current status: {intent.get_status_display()}.'
                })
            
            # Validate intent is not expired
            if intent.is_expired:
                raise ValidationError({
                    'intent': 'Booking intent has expired. Please create a new intent.'
                })
            
            # Validate intent belongs to user
            if intent.made_by != user:
                raise ValidationError({
                    'intent': 'This booking intent does not belong to you.'
                })
            
            # Get event from intent
            event = intent.event
            
            # Validate intent event matches booking event (if event provided in body)
            if 'event' in serializer.validated_data and serializer.validated_data['event'] != event:
                raise ValidationError({
                    'intent': f'Booking intent is for event "{event.title}" but booking is for a different event.'
                })
            
            # Set event from intent
            serializer.validated_data['event'] = event
            
            # Validate capacity using intent's can_create_booking method
            if not intent.can_create_booking():
                raise ValidationError({
                    'intent': 'Cannot create booking from this intent. Capacity may have been exhausted or intent is not valid.'
                })
            
            # Create the booking
            booking = serializer.save()
            
            # Mark intent as completed
            intent.mark_completed(save=True)
        else:
            # Admin users: if event not provided in body, check if intent is provided
            if 'event' not in serializer.validated_data or not serializer.validated_data['event']:
                if intent_id:
                    # Try to use intent if provided
                    try:
                        intent = BookingIntent.objects.get(booking_intent_id=intent_id)
                        serializer.validated_data['event'] = intent.event
                        booking = serializer.save()
                        intent.mark_completed(save=True)
                    except BookingIntent.DoesNotExist:
                        raise ValidationError({
                            'event': 'Event is required when no valid intent is provided.'
                        })
                else:
                    raise ValidationError({
                        'event': 'Event is required for admin bookings without an intent.'
                    })
            else:
                # Admin with event provided
                booking = serializer.save()
                
                # If intent provided, mark it as completed
                if intent_id:
                    try:
                        intent = BookingIntent.objects.get(booking_intent_id=intent_id)
                        intent.mark_completed(save=True)
                    except BookingIntent.DoesNotExist:
                        pass  # Intent not found, ignore for admin users
    
    @extend_schema(
        summary="List attendees for booking",
        description="Retrieve all attendees associated with this booking.",
        tags=["Bookings"],
        responses={200: OpenApiResponse(description="List of attendees")},
        operation_id="bookings_booking_attendees_list",
    )
    @action(detail=True, methods=['get'], url_path='attendees')
    def attendees(self, request, pk=None):
        """Return all attendees for this booking."""
        booking = self.get_object()
        from apps.attendee.api.serializers import AttendeeListSerializer
        
        attendees = booking.attendees.all()
        serializer = AttendeeListSerializer(attendees, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="List tickets for booking",
        description="Retrieve all tickets across all attendees for this booking.",
        tags=["Bookings"],
        responses={200: TicketListSerializer(many=True)},
        operation_id="bookings_booking_tickets_list",
    )
    @action(detail=True, methods=['get'], url_path='tickets')
    def tickets(self, request, pk=None):
        """Return all tickets for all attendees in this booking."""
        booking = self.get_object()
        
        # Get all tickets through attendees
        tickets = Ticket.objects.filter(
            attendee__booking=booking
        ).select_related('attendee', 'ticket_type', 'package', 'payment')
        
        serializer = TicketListSerializer(tickets, many=True, context={'request': request, 'event': booking.event})
        return Response(serializer.data)


# ============================================================================
# BOOKING INTENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List booking intents",
        description="Retrieve a paginated list of booking intents. Users see only their own intents, admins see all.",
        tags=["Booking Intents"],
        parameters=[
            OpenApiParameter(
                name='is_active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter by active status (pending and not expired)',
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve booking intent details",
        description="Get detailed information about a specific booking intent.",
        tags=["Booking Intents"],
    ),
    create=extend_schema(
        summary="Create booking intent",
        description="Create a new booking intent to reserve capacity for event tickets. Intent expires after 20 minutes.",
        tags=["Booking Intents"],
    ),
    update=extend_schema(
        summary="Update booking intent",
        description="Update an existing booking intent. Only ticket count can be modified and only for pending intents.",
        tags=["Booking Intents"],
    ),
    partial_update=extend_schema(
        summary="Partially update booking intent",
        description="Partially update a booking intent. Only ticket count can be modified and only for pending intents.",
        tags=["Booking Intents"],
    ),
    destroy=extend_schema(
        summary="Delete booking intent",
        description="Delete a booking intent. Only allowed for pending intents.",
        tags=["Booking Intents"],
    ),
)
class BookingIntentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing booking intents.
    
    Booking intents reserve capacity before payment to prevent race conditions.
    They expire after 20 minutes and are cleaned up by background tasks.
    
    Provides:
    - List/Retrieve: Users see their own intents, admins see all
    - Create: Reserve capacity for tickets (max 20 tickets per intent)
    - Update: Modify ticket count (only for pending intents)
    - Cancel: Release reserved capacity
    - Delete: Remove intent (only pending intents)
    
    Permissions:
    - List/Create: Authenticated users
    - Retrieve/Update/Delete/Cancel: Intent creator or administrative staff
    """
    
    queryset = BookingIntent.objects.select_related('event', 'made_by').all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingIntentFilterSet
    search_fields = ['booking_intent_id', 'event__title', 'event__display_code']
    ordering_fields = ['created_at', 'expires_at', 'status']
    ordering = ['-created_at']
    lookup_field = 'booking_intent_id'
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action in ['list', 'create']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            # For retrieve, update, partial_update, destroy, cancel
            permission_classes = [permissions.IsAuthenticated, IsBookingOwnerOrAdministrative]
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()
        
        # Non-admin users only see their own intents
        if not self.request.user.is_staff:
            queryset = queryset.filter(made_by=self.request.user)
        
        # Exclude soft-deleted intents from list view
        if self.action == 'list':
            queryset = queryset.filter(deleted_at__isnull=True)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return BookingIntentListSerializer
        elif self.action == 'retrieve':
            return BookingIntentDetailSerializer
        elif self.action == 'create':
            return BookingIntentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BookingIntentUpdateSerializer
        return BookingIntentDetailSerializer
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.event
            except:
                pass
        return context
    
    def perform_create(self, serializer):
        """Create booking intent with authenticated user."""
        serializer.save(made_by=self.request.user)
    
    def perform_destroy(self, instance):
        """Only allow deletion of pending intents."""
        if instance.status != BookingIntentStatusChoices.PENDING:
            raise ValidationError("Cannot delete a non-pending booking intent.")
        instance.delete()
    
    @extend_schema(
        summary="Cancel booking intent",
        description="Cancel a pending booking intent, releasing the reserved capacity. Cannot be undone.",
        tags=["Booking Intents"],
        request=None,
        responses={
            200: OpenApiResponse(
                description="Intent successfully cancelled",
                response=BookingIntentDetailSerializer
            ),
            400: OpenApiResponse(description="Intent cannot be cancelled (not pending)"),
            404: OpenApiResponse(description="Intent not found"),
        },
        operation_id="bookings_intent_cancel",
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, booking_intent_id=None):
        """Cancel a booking intent."""
        intent = self.get_object()
        
        if intent.status != BookingIntentStatusChoices.PENDING:
            return Response(
                {'detail': 'Only pending intents can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if intent.is_expired:
            return Response(
                {'detail': 'Cannot cancel an expired intent.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Cancel the intent
        intent.cancel(save=True)
        
        serializer = self.get_serializer(intent)
        return Response(serializer.data)


# ============================================================================
# TICKET TYPE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List ticket types",
        description="Retrieve a list of ticket types. Filter by event, scope, or validity.",
        tags=["Ticket Types"],
    ),
    retrieve=extend_schema(
        summary="Retrieve ticket type details",
        description="Get detailed information about a specific ticket type.",
        tags=["Ticket Types"],
    ),
    create=extend_schema(
        summary="Create ticket type",
        description="Create a new ticket type for an event. Requires administrative access.",
        tags=["Ticket Types"],
    ),
    update=extend_schema(
        summary="Update ticket type",
        description="Update an existing ticket type. Requires administrative access.",
        tags=["Ticket Types"],
    ),
    partial_update=extend_schema(
        summary="Partially update ticket type",
        description="Partially update a ticket type. Requires administrative access.",
        tags=["Ticket Types"],
    ),
    destroy=extend_schema(
        summary="Delete ticket type",
        description="Delete a ticket type. Requires administrative access.",
        tags=["Ticket Types"],
    ),
)
class TicketTypeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing ticket types.
    
    Provides:
    - List/Retrieve: Any authenticated user can view ticket types
    - Create/Update/Delete: Administrative staff only
    
    Permissions:
    - List/Retrieve: Authenticated + ReadOnly
    - Create/Update/Delete: Administrative staff
    """
    
    queryset = TicketType.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TicketTypeFilterSet
    search_fields = ['title', 'code']
    ordering_fields = ['created_at', 'title', 'valid_from']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return TicketTypeListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return TicketTypeCreateUpdateSerializer
        return TicketTypeDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated(), IsReadOnly()]
        return [permissions.IsAuthenticated(), IsAdministrativeStaff()]
    
    def get_queryset(self):
        """Optimize queryset with select_related."""
        return super().get_queryset().select_related('event', 'created_by')
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.event
            except:
                pass
        return context
    
    def perform_create(self, serializer):
        """Set created_by when creating ticket type."""
        serializer.save(created_by=self.request.user)


# ============================================================================
# TICKET VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List tickets",
        description="Retrieve a list of tickets. Filter by status, attendee, booking, or type.",
        tags=["Tickets"],
    ),
    retrieve=extend_schema(
        summary="Retrieve ticket details",
        description="Get detailed information about a specific ticket.",
        tags=["Tickets"],
    ),
)
class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for tickets.
    
    Tickets are created automatically server-side when payments are completed.
    Users can view their own tickets, admins can view all tickets.
    
    Permissions:
    - List/Retrieve: Ticket owner or administrative staff
    """
    
    queryset = Ticket.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TicketFilterSet
    search_fields = ['ticket_code', 'attendee__first_name', 'attendee__last_name']
    ordering_fields = ['issued_at', 'status']
    ordering = ['-issued_at']
    lookup_field = 'ticket_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return TicketListSerializer
        return TicketDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        return [permissions.IsAuthenticated(), IsTicketOwnerOrAdministrative()]
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions.
        
        Regular users see only their own tickets.
        Admins see all tickets.
        """
        user = self.request.user
        queryset = super().get_queryset()
        
        # Optimize with select_related
        queryset = queryset.select_related('attendee', 'ticket_type', 'package', 'payment')
        
        # If user is superuser or staff, return all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_events = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)
        
        # Return tickets for user's attendees or events they administer
        return queryset.filter(
            Q(attendee__user=user) |
            Q(attendee__booking__made_by=user) |
            Q(ticket_type__event_id__in=admin_events)
        ).distinct()
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.ticket_type.event if obj.ticket_type else None
            except:
                pass
        return context


# ============================================================================
# BOOKING PACKAGE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List booking packages",
        description="Retrieve a list of booking packages. Filter by event, ticket type, or eligibility.",
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='eligible_for_attendee',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Filter packages eligible for specific attendee UUID',
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve booking package details",
        description="Get detailed information about a specific booking package including rules.",
        tags=["Booking Packages"],
    ),
    create=extend_schema(
        summary="Create booking package",
        description="Create a new booking package with optional rules. Requires administrative access.",
        tags=["Booking Packages"],
    ),
    update=extend_schema(
        summary="Update booking package",
        description="Update an existing booking package. Requires administrative access.",
        tags=["Booking Packages"],
    ),
    partial_update=extend_schema(
        summary="Partially update booking package",
        description="Partially update a booking package. Requires administrative access.",
        tags=["Booking Packages"],
    ),
    destroy=extend_schema(
        summary="Delete booking package",
        description="Delete a booking package. Requires administrative access.",
        tags=["Booking Packages"],
    ),
)
class BookingPackageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing booking packages.
    
    Provides:
    - List/Retrieve: Any authenticated user can view packages
    - Create/Update/Delete: Administrative staff only
    - Eligibility filtering: Check if packages apply to specific attendees
    
    Permissions:
    - List/Retrieve: Authenticated users
    - Create/Update/Delete: Administrative staff
    """
    
    queryset = BookingPackage.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingPackageFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name', 'base_amount']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return BookingPackageListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return BookingPackageCreateUpdateSerializer
        return BookingPackageDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdministrativeStaff()]
    
    def get_queryset(self):
        """Optimize queryset with select_related and prefetch rules."""
        return super().get_queryset().select_related(
            'event', 'ticket_type', 'created_by'
        ).prefetch_related('rules')
    
    @extend_schema(
        summary="List rules for booking package",
        description="Retrieve all rules associated with this booking package.",
        tags=["Booking Packages"],
        responses={200: BookingPackageRuleSerializer(many=True)},
        operation_id="bookings_package_rules_list",
    )
    @action(detail=True, methods=['get'], url_path='rules')
    def rules(self, request, pk=None):
        """Return all rules for this booking package."""
        package = self.get_object()
        rules = package.rules.filter(active=True)
        serializer = BookingPackageRuleSerializer(rules, many=True, context={'request': request})
        return Response(serializer.data)


# ============================================================================
# ALTERNATIVE SIGNIN VIEWSETS (ADMIN ONLY)
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List event alternative signin identifiers",
        description="Retrieve event alternative signin identifiers. Admin only.",
        tags=["Alternative Signins"],
    ),
    retrieve=extend_schema(
        summary="Retrieve event alternative signin details",
        description="Get detailed information about an event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    create=extend_schema(
        summary="Create event alternative signin",
        description="Create a new event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    update=extend_schema(
        summary="Update event alternative signin",
        description="Update an existing event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    partial_update=extend_schema(
        summary="Partially update event alternative signin",
        description="Partially update an event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    destroy=extend_schema(
        summary="Delete event alternative signin",
        description="Delete an event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
)
class EventAlternativeSigninViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event alternative signin identifiers.
    
    Admin-only access for managing alternative check-in methods.
    
    Permissions:
    - All actions: Administrative staff only
    """
    
    queryset = EventAlternativeSigninIdentifier.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventAlternativeSigninFilterSet
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'title']
    ordering = ['-created_at']
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventAlternativeSigninListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventAlternativeSigninCreateUpdateSerializer
        return EventAlternativeSigninDetailSerializer
    
    def get_queryset(self):
        """Optimize queryset with select_related."""
        return super().get_queryset().select_related(
            'event', 'verified_by', 'processed_by'
        )


@extend_schema_view(
    list=extend_schema(
        summary="List attendee alternative signin identifiers",
        description="Retrieve attendee alternative signin identifiers. Admin only.",
        tags=["Alternative Signins"],
    ),
    retrieve=extend_schema(
        summary="Retrieve attendee alternative signin details",
        description="Get detailed information about an attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    create=extend_schema(
        summary="Create attendee alternative signin",
        description="Create a new attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    update=extend_schema(
        summary="Update attendee alternative signin",
        description="Update an existing attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    partial_update=extend_schema(
        summary="Partially update attendee alternative signin",
        description="Partially update an attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    destroy=extend_schema(
        summary="Delete attendee alternative signin",
        description="Delete an attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
)
class AttendeeAlternativeSigninViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing attendee alternative signin identifiers.
    
    Admin-only access for linking alternative IDs to attendee tickets.
    
    Permissions:
    - All actions: Administrative staff only
    """
    
    queryset = AttendeeAlternativeSigninIdentifier.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AttendeeAlternativeSigninFilterSet
    search_fields = ['identifier', 'attendee__first_name', 'attendee__last_name']
    ordering_fields = ['defined_at', 'identifier']
    ordering = ['-defined_at']
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    lookup_field = 'sign_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AttendeeAlternativeSigninListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return AttendeeAlternativeSigninCreateUpdateSerializer
        return AttendeeAlternativeSigninDetailSerializer
    
    def get_queryset(self):
        """Optimize queryset with select_related."""
        return super().get_queryset().select_related(
            'attendee', 'ticket', 'event_alternative_signin', 'defined_by'
        )
