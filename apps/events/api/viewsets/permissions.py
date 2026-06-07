from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from apps.events.models import EventPermission
from apps.events.api.serializers import EventPermissionSerializer
from apps.events.api.pagination import StandardPagination

from apps.events.api.serializers import (EventPermissionSerializer,EventPermissionAssignmentSerializer )
from apps.events.models import EventPermission, EventPermissionAssignment
from apps.events.api.filtersets import EventPermissionAssignmentFilterSet
from apps.events.api.permissions import CannotTargetEventCreator
from rest_framework.exceptions import PermissionDenied

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