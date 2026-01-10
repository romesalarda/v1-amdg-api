from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
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
    EventStaff, EventStaffAvailability,
    EventReview,
    EventQuestion, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice
)
from .serializers import (
    EventTypeSerializer, EventListSerializer, EventDetailSerializer,
    EventCreateUpdateSerializer, EventSettingsSerializer,
    EventAuthorizationSerializer, EventPermissionSerializer,
    EventPermissionAssignmentSerializer, EventRoleSerializer,
    EventRoleAssignmentSerializer, EventStaffSerializer,
    EventStaffAvailabilitySerializer, EventReviewSerializer,
    EventQuestionSerializer, EventQuestionOptionSerializer,
    EventQuestionAnswerSerializer, EventQuestionAnswerChoiceSerializer
)


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema_view(
    list=extend_schema(
        summary="List event types",
        description="Retrieve a paginated list of all event types",
        parameters=[
            OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search by title or code'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get event type details",
        description="Retrieve detailed information about a specific event type"
    ),
    create=extend_schema(
        summary="Create event type",
        description="Create a new event type"
    ),
    update=extend_schema(
        summary="Update event type",
        description="Update an existing event type"
    ),
    partial_update=extend_schema(
        summary="Partially update event type",
        description="Partially update an existing event type"
    ),
    destroy=extend_schema(
        summary="Delete event type",
        description="Delete an event type"
    )
)
class EventTypeViewSet(viewsets.ModelViewSet):
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
        summary="List events",
        description="Retrieve a paginated list of all events with filtering and search capabilities",
        parameters=[
            OpenApiParameter(name='status', type=OpenApiTypes.STR, description='Filter by status'),
            OpenApiParameter(name='event_type', type=OpenApiTypes.INT, description='Filter by event type ID'),
            OpenApiParameter(name='organisation', type=OpenApiTypes.INT, description='Filter by organisation ID'),
            OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search by title or description'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get event details",
        description="Retrieve comprehensive details about a specific event"
    ),
    create=extend_schema(
        summary="Create event",
        description="Create a new event"
    ),
    update=extend_schema(
        summary="Update event",
        description="Update an existing event"
    ),
    partial_update=extend_schema(
        summary="Partially update event",
        description="Partially update an existing event"
    ),
    destroy=extend_schema(
        summary="Delete event",
        description="Soft delete an event"
    )
)
class EventViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'event_type', 'organisation']
    search_fields = ['title', 'short_description', 'long_description', 'display_code']
    ordering_fields = ['title', 'start_datetime', 'created_at']
    ordering = ['-start_datetime']
    lookup_field = 'event_id'
    
    def get_queryset(self):
        queryset = Event.objects.select_related(
            'event_type', 'organisation', 'created_by'
        ).prefetch_related('settings')
        
        if not self.request.user.is_staff:
            queryset = queryset.filter(status__in=[
                EventStatusChoices.PUBLISHED,
                EventStatusChoices.OPEN,
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
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @extend_schema(
        summary="Get upcoming events",
        description="Retrieve all upcoming events that haven't started yet"
    )
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        from django.utils import timezone
        queryset = self.get_queryset().filter(start_datetime__gt=timezone.now())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EventListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = EventListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Get ongoing events",
        description="Retrieve all currently ongoing events"
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
        summary="Get event settings",
        description="Retrieve settings for a specific event"
    )
    @action(detail=True, methods=['get'], url_path='settings')
    def event_settings(self, request, event_id=None):
        event = self.get_object()
        event_settings = getattr(event, 'settings', None)
        if not event_settings:
            return Response(
                {"detail": "Settings not found for this event"},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = EventSettingsSerializer(event_settings)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Add staff to event",
        description="Add a user as staff member to the event",
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
    def add_staff(self, request, event_id=None):
        from django.contrib.auth import get_user_model
        from .permissions import IsEventOwnerOrStaffMember
        
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
        summary="Remove staff from event",
        description="Remove a staff member from the event",
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
    def remove_staff(self, request, event_id=None):
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
        
        staff_member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @extend_schema(
        summary="List event staff",
        description="Get all staff members for the event",
        responses={200: EventStaffSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='staff-list')
    def staff_list(self, request, event_id=None):
        event = self.get_object()
        staff_members = event.staff_members.select_related('user', 'assigned_by').all()
        serializer = EventStaffSerializer(staff_members, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Assign permission to user",
        description="Assign a specific permission to a user for this event",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'User ID'},
                    'permission_id': {'type': 'integer', 'description': 'Permission ID'}
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
            defaults={'assigned_by': request.user}
        )
        
        if not created:
            return Response(
                {"detail": "This permission is already assigned to the user for this event"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = EventPermissionAssignmentSerializer(assignment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Revoke permission from user",
        description="Revoke a specific permission from a user for this event",
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
    def revoke_permission(self, request, event_id=None):
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
        summary="Check user permissions",
        description="Check what permissions a user has for this event",
        parameters=[
            OpenApiParameter(name='user_id', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
                           description='User ID to check permissions for. If not provided, checks current user.')
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer'},
                    'is_owner': {'type': 'boolean'},
                    'is_staff_member': {'type': 'boolean'},
                    'permissions': {
                        'type': 'array',
                        'items': {'type': 'object'}
                    }
                }
            }
        }
    )
    @action(detail=True, methods=['get'], url_path='check-permissions')
    def check_user_permissions(self, request, event_id=None):
        from django.contrib.auth import get_user_model
        
        event = self.get_object()
        
        user_id = request.query_params.get('user_id')
        if user_id:
            User = get_user_model()
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            user = request.user
        
        is_owner = event.created_by == user
        is_staff_member = event.staff_members.filter(user=user).exists()
        
        permission_assignments = EventPermissionAssignment.objects.filter(
            event=event, user=user
        ).select_related('permission')
        
        permissions_data = EventPermissionAssignmentSerializer(permission_assignments, many=True).data
        
        return Response({
            'user_id': user.id,
            'user_email': user.email,
            'is_owner': is_owner,
            'is_staff_member': is_staff_member,
            'permissions': permissions_data
        })


@extend_schema_view(
    list=extend_schema(
        summary="List event settings",
        description="Retrieve a list of all event settings"
    ),
    retrieve=extend_schema(
        summary="Get event settings",
        description="Retrieve settings for a specific event"
    ),
    create=extend_schema(
        summary="Create event settings",
        description="Create settings for an event"
    ),
    update=extend_schema(
        summary="Update event settings",
        description="Update settings for an event"
    ),
    partial_update=extend_schema(
        summary="Partially update event settings",
        description="Partially update settings for an event"
    )
)
class EventSettingsViewSet(viewsets.ModelViewSet):
    queryset = EventSettings.objects.all()
    serializer_class = EventSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination


@extend_schema_view(
    list=extend_schema(
        summary="List event authorizations",
        description="Retrieve a list of event authorizations with filtering",
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
            OpenApiParameter(name='status', type=OpenApiTypes.STR, description='Filter by authorization status'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get authorization details",
        description="Retrieve details of a specific authorization"
    ),
    create=extend_schema(
        summary="Create authorization",
        description="Create a new event authorization"
    ),
    update=extend_schema(
        summary="Update authorization",
        description="Update an event authorization"
    ),
    partial_update=extend_schema(
        summary="Partially update authorization",
        description="Partially update an event authorization"
    )
)
class EventAuthorizationViewSet(viewsets.ModelViewSet):
    queryset = EventAuthorization.objects.select_related('event', 'reviewed_by').all()
    serializer_class = EventAuthorizationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['event', 'status', 'reviewed_by']
    ordering_fields = ['reviewed_at']
    ordering = ['-reviewed_at']
    
    def perform_create(self, serializer):
        serializer.save(reviewed_by=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List event permissions",
        description="Retrieve a list of all event permissions",
        parameters=[
            OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Filter by category'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get permission details",
        description="Retrieve details of a specific permission"
    ),
    create=extend_schema(
        summary="Create permission",
        description="Create a new event permission"
    ),
    update=extend_schema(
        summary="Update permission",
        description="Update an event permission"
    ),
    partial_update=extend_schema(
        summary="Partially update permission",
        description="Partially update an event permission"
    )
)
class EventPermissionViewSet(viewsets.ModelViewSet):
    queryset = EventPermission.objects.all().order_by('name')
    serializer_class = EventPermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category']
    search_fields = ['name', 'code']


@extend_schema_view(
    list=extend_schema(
        summary="List permission assignments",
        description="Retrieve a list of event permission assignments",
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
            OpenApiParameter(name='user', type=OpenApiTypes.INT, description='Filter by user ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get permission assignment",
        description="Retrieve details of a specific permission assignment"
    ),
    create=extend_schema(
        summary="Assign permission",
        description="Assign a permission to a user for an event"
    ),
    destroy=extend_schema(
        summary="Remove permission assignment",
        description="Remove a permission assignment"
    )
)
class EventPermissionAssignmentViewSet(viewsets.ModelViewSet):
    queryset = EventPermissionAssignment.objects.select_related(
        'event', 'user', 'permission', 'assigned_by'
    ).all()
    serializer_class = EventPermissionAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event', 'user', 'permission']
    
    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List event roles",
        description="Retrieve a list of all event roles",
        parameters=[
            OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Filter by category'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get role details",
        description="Retrieve details of a specific role"
    ),
    create=extend_schema(
        summary="Create role",
        description="Create a new event role"
    ),
    update=extend_schema(
        summary="Update role",
        description="Update an event role"
    ),
    partial_update=extend_schema(
        summary="Partially update role",
        description="Partially update an event role"
    )
)
class EventRoleViewSet(viewsets.ModelViewSet):
    queryset = EventRole.objects.all()
    serializer_class = EventRoleSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category']
    search_fields = ['name', 'code']


@extend_schema_view(
    list=extend_schema(
        summary="List role assignments",
        description="Retrieve a list of event role assignments",
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
            OpenApiParameter(name='user', type=OpenApiTypes.INT, description='Filter by user ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get role assignment",
        description="Retrieve details of a specific role assignment"
    ),
    create=extend_schema(
        summary="Assign role",
        description="Assign a role to a user for an event"
    ),
    destroy=extend_schema(
        summary="Remove role assignment",
        description="Remove a role assignment"
    )
)
class EventRoleAssignmentViewSet(viewsets.ModelViewSet):
    queryset = EventRoleAssignment.objects.select_related(
        'event', 'user', 'role', 'assigned_by'
    ).all()
    serializer_class = EventRoleAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event', 'user', 'role']
    
    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List event staff",
        description="Retrieve a list of event staff members",
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get staff details",
        description="Retrieve details of a specific staff member"
    ),
    create=extend_schema(
        summary="Add staff member",
        description="Add a staff member to an event"
    ),
    update=extend_schema(
        summary="Update staff member",
        description="Update a staff member's information"
    ),
    partial_update=extend_schema(
        summary="Partially update staff member",
        description="Partially update a staff member's information"
    ),
    destroy=extend_schema(
        summary="Remove staff member",
        description="Remove a staff member from an event"
    )
)
class EventStaffViewSet(viewsets.ModelViewSet):
    queryset = EventStaff.objects.select_related(
        'event', 'user', 'assigned_by'
    ).prefetch_related('availabilities').all()
    serializer_class = EventStaffSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event', 'user']
    
    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List staff availability",
        description="Retrieve a list of staff availability records",
        parameters=[
            OpenApiParameter(name='staff', type=OpenApiTypes.UUID, description='Filter by staff ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get availability details",
        description="Retrieve details of a specific availability record"
    ),
    create=extend_schema(
        summary="Create availability",
        description="Create a new staff availability record"
    ),
    update=extend_schema(
        summary="Update availability",
        description="Update a staff availability record"
    ),
    partial_update=extend_schema(
        summary="Partially update availability",
        description="Partially update a staff availability record"
    ),
    destroy=extend_schema(
        summary="Delete availability",
        description="Delete a staff availability record"
    )
)
class EventStaffAvailabilityViewSet(viewsets.ModelViewSet):
    queryset = EventStaffAvailability.objects.select_related('staff').all()
    serializer_class = EventStaffAvailabilitySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['staff']


@extend_schema_view(
    list=extend_schema(
        summary="List event reviews",
        description="Retrieve a list of event reviews",
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
            OpenApiParameter(name='approved', type=OpenApiTypes.BOOL, description='Filter by approval status'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get review details",
        description="Retrieve details of a specific review"
    ),
    create=extend_schema(
        summary="Create review",
        description="Create a new event review"
    ),
    update=extend_schema(
        summary="Update review",
        description="Update an event review"
    ),
    partial_update=extend_schema(
        summary="Partially update review",
        description="Partially update an event review"
    ),
    destroy=extend_schema(
        summary="Delete review",
        description="Delete an event review"
    )
)
class EventReviewViewSet(viewsets.ModelViewSet):
    queryset = EventReview.objects.select_related('event', 'user').all()
    serializer_class = EventReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['event', 'approved', 'rating']
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
        summary="Approve reviews",
        description="Approve selected reviews (staff only)"
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
        summary="List event questions",
        description="Retrieve a list of event questions",
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
            OpenApiParameter(name='question_type', type=OpenApiTypes.STR, description='Filter by question type'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get question details",
        description="Retrieve details of a specific question"
    ),
    create=extend_schema(
        summary="Create question",
        description="Create a new event question"
    ),
    update=extend_schema(
        summary="Update question",
        description="Update an event question"
    ),
    partial_update=extend_schema(
        summary="Partially update question",
        description="Partially update an event question"
    ),
    destroy=extend_schema(
        summary="Delete question",
        description="Delete an event question"
    )
)
class EventQuestionViewSet(viewsets.ModelViewSet):
    queryset = EventQuestion.objects.select_related('event').prefetch_related('options').all()
    serializer_class = EventQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['event', 'question_type', 'required', 'public']
    ordering_fields = ['order', 'created_at']
    ordering = ['order']


@extend_schema_view(
    list=extend_schema(
        summary="List question options",
        description="Retrieve a list of question options",
        parameters=[
            OpenApiParameter(name='question', type=OpenApiTypes.UUID, description='Filter by question ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get option details",
        description="Retrieve details of a specific option"
    ),
    create=extend_schema(
        summary="Create option",
        description="Create a new question option"
    ),
    update=extend_schema(
        summary="Update option",
        description="Update a question option"
    ),
    partial_update=extend_schema(
        summary="Partially update option",
        description="Partially update a question option"
    ),
    destroy=extend_schema(
        summary="Delete option",
        description="Delete a question option"
    )
)
class EventQuestionOptionViewSet(viewsets.ModelViewSet):
    queryset = EventQuestionOption.objects.select_related('question').all()
    serializer_class = EventQuestionOptionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['question']


@extend_schema_view(
    list=extend_schema(
        summary="List question answers",
        description="Retrieve a list of question answers",
        parameters=[
            OpenApiParameter(name='question', type=OpenApiTypes.UUID, description='Filter by question ID'),
            OpenApiParameter(name='attendee', type=OpenApiTypes.INT, description='Filter by attendee ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get answer details",
        description="Retrieve details of a specific answer"
    ),
    create=extend_schema(
        summary="Submit answer",
        description="Submit a new question answer"
    ),
    update=extend_schema(
        summary="Update answer",
        description="Update a question answer"
    ),
    partial_update=extend_schema(
        summary="Partially update answer",
        description="Partially update a question answer"
    ),
    destroy=extend_schema(
        summary="Delete answer",
        description="Delete a question answer"
    )
)
class EventQuestionAnswerViewSet(viewsets.ModelViewSet):
    queryset = EventQuestionAnswer.objects.select_related(
        'question', 'attendee'
    ).prefetch_related('selected_options').all()
    serializer_class = EventQuestionAnswerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['question', 'attendee']


@extend_schema_view(
    list=extend_schema(
        summary="List answer choices",
        description="Retrieve a list of answer choices"
    ),
    retrieve=extend_schema(
        summary="Get choice details",
        description="Retrieve details of a specific choice"
    ),
    create=extend_schema(
        summary="Create choice",
        description="Create a new answer choice"
    ),
    destroy=extend_schema(
        summary="Delete choice",
        description="Delete an answer choice"
    )
)
class EventQuestionAnswerChoiceViewSet(viewsets.ModelViewSet):
    queryset = EventQuestionAnswerChoice.objects.select_related('answer', 'option').all()
    serializer_class = EventQuestionAnswerChoiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['answer']
