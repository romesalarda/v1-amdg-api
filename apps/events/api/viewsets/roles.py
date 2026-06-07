from rest_framework import viewsets, permissions, filters
from rest_framework.exceptions import PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes

from apps.events.models import EventRole, EventRoleAssignment
from apps.events.api.serializers import EventRoleSerializer,EventRoleAssignmentSerializer

from apps.events.api.filtersets import EventRoleAssignmentFilterSet
from apps.events.api.pagination import StandardPagination
from apps.events.api.permissions import CannotTargetEventCreator



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