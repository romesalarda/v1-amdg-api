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
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
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
    Booking, BookingPackage, BookingPackageRule,
    TicketType, Ticket,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
)
from .serializers import (
    BookingListSerializer, BookingDetailSerializer, BookingCreateSerializer, BookingUpdateSerializer,
    TicketTypeListSerializer, TicketTypeDetailSerializer, TicketTypeCreateUpdateSerializer,
    TicketListSerializer, TicketDetailSerializer,
    BookingPackageListSerializer, BookingPackageDetailSerializer, BookingPackageCreateUpdateSerializer,
    BookingPackageRuleSerializer, BookingPackageRuleCreateUpdateSerializer,
    EventAlternativeSigninListSerializer, EventAlternativeSigninDetailSerializer, EventAlternativeSigninCreateUpdateSerializer,
    AttendeeAlternativeSigninListSerializer, AttendeeAlternativeSigninDetailSerializer, AttendeeAlternativeSigninCreateUpdateSerializer,
)
from .filtersets import (
    BookingFilterSet, TicketFilterSet, TicketTypeFilterSet, BookingPackageFilterSet,
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
        description="Create a new booking for an event. Booking reference is auto-generated.",
        tags=["Bookings"],
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
