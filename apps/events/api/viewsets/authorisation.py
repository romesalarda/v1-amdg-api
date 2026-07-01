from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, filters
from apps.events.api.pagination import StandardPagination

from apps.events.models import EventAuthorization
from apps.events.api.serializers import EventAuthorizationSerializer
from apps.events.api.filtersets import EventAuthorizationFilterSet

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

    def perform_update(self, serializer):
        previous_status = serializer.instance.status
        new_status = serializer.validated_data.get('status', previous_status)

        serializer.save(reviewed_by=self.request.user)

        if (
            previous_status != new_status and 
            previous_status in EventAuthorization.OPEN_STATUS_CHOICES and
            new_status in EventAuthorization.CLOSED_STATUS_CHOICES
        ):
            serializer.instance.event.force_close()
            