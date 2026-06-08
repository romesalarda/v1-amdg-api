

from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
# Import models
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.bookings.models import (
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
)
from apps.bookings.api.serializers import (
    EventAlternativeSigninListSerializer, EventAlternativeSigninDetailSerializer, EventAlternativeSigninCreateUpdateSerializer,
    AttendeeAlternativeSigninListSerializer, AttendeeAlternativeSigninDetailSerializer, AttendeeAlternativeSigninCreateUpdateSerializer,
)

from apps.bookings.api.filtersets import (
    EventAlternativeSigninFilterSet, AttendeeAlternativeSigninFilterSet,
)
from apps.bookings.api.permissions import IsAdministrativeStaffOnly
from apps.bookings.api.pagination import StandardPagination

import logging
logger = logging.getLogger(__name__)

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
