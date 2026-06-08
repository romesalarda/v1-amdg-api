from rest_framework import viewsets, status, permissions, filters
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
# Import models
from apps.bookings.models.ticket import Ticket
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.bookings.models import TicketType, Ticket
from apps.bookings.api.serializers import (
    TicketTypeListSerializer, TicketTypeDetailSerializer, TicketTypeCreateUpdateSerializer,
    TicketListSerializer, TicketDetailSerializer,
)
from apps.bookings.api.filtersets import (
    TicketFilterSet, TicketTypeFilterSet,
)
from apps.bookings.api.permissions import (IsAdministrativeStaff,IsTicketOwnerOrAdministrative, IsReadOnly)
from apps.bookings.api.pagination import StandardPagination

import logging
logger = logging.getLogger(__name__)

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
    
    def destroy(self, request, *args, **kwargs):
        """Override destroy to prevent deletion if tickets exist for this type."""
        instance = self.get_object()
        if instance.can_delete is False:
            return Response(
                {'detail': 'Cannot delete ticket type with existing tickets.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        """Set created_by when creating ticket type."""
        serializer.save(created_by=self.request.user)

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