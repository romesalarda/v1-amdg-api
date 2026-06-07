from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.utils import timezone

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.events.models import (
    EventPermissionAssignment,EventRoleAssignment,
    EventStaff, EventStaffAvailability, EventStaffInvite,
)

from apps.events.api.serializers import (EventStaffSerializer,
    EventStaffAvailabilitySerializer, EventStaffInviteListSerializer,
    
)

from apps.events.api.filtersets import (
    EventStaffFilterSet,
    EventStaffInviteFilterSet,
)

from apps.events.api.pagination import StandardPagination

from apps.events.api.permissions import (CannotTargetEventCreator)


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
        # Remove all permission assignments for this user on this event
        EventPermissionAssignment.objects.filter(
            event=instance.event,
            user=instance.user
        ).delete()

        # Remove all role assignments for this user on this event
        EventRoleAssignment.objects.filter(
            event=instance.event,
            user=instance.user
        ).delete()

        super().perform_destroy(instance)


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