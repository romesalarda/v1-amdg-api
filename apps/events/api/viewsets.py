from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from django.contrib.contenttypes.models import ContentType
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
    EventQuestionAnswer, EventQuestionAnswerChoice, EventVenue
)
from apps.common.models import AvailabilityWindow, Resource
from apps.common.api.serializers import (
    AvailabilityWindowSerializer,
    ResourceSerializer
)
from .serializers import (
    EventTypeSerializer, EventListSerializer, EventDetailSerializer,
    EventCreateUpdateSerializer, EventSettingsSerializer,
    EventAuthorizationSerializer, EventPermissionSerializer,
    EventPermissionAssignmentSerializer, EventRoleSerializer,
    EventRoleAssignmentSerializer, EventStaffSerializer,
    EventStaffAvailabilitySerializer, EventReviewSerializer,
    EventQuestionSerializer, EventQuestionOptionSerializer,
    EventQuestionAnswerSerializer, EventQuestionAnswerChoiceSerializer,
    EventVenueSerializer
)

from apps.events.api.pagination import StandardPagination

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
        - resources / add_resource / remove_resource: Resource management
        - landing_images / add_landing_image: Landing page image management
        - assign_permission: Assign permissions to users
    """
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
        queryset = self.get_queryset().filter(start_datetime__gt=timezone.now())
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
    def staff_list(self, request, event_id=None):
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
    def soft_delete_event(self, request, event_id=None):
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
    def restore_event(self, request, event_id=None):
        event = Event.all_objects.get(event_id=event_id)
        
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
    def availability_windows(self, request, event_id=None):
        event = self.get_object()
        windows = event.availability_windows.all()
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
    def add_availability_window(self, request, event_id=None):
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
    def remove_availability_window(self, request, event_id=None):
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
    def resources(self, request, event_id=None):
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
    def add_resource(self, request, event_id=None):
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
    def add_landing_image(self, request, event_id=None):
        event = self.get_object()
        
        # Check permission
        if not (request.user.is_staff or request.user.is_superuser or event.created_by == request.user):
            return Response(
                {"detail": "You don't have permission to add landing images to this event"},
                status=status.HTTP_403_FORBIDDEN
            )
        
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
    def remove_resource(self, request, event_id=None):
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
    def landing_images(self, request, event_id=None):
        event = self.get_object()
        images = event.landing_images.all()
        serializer = ResourceSerializer(images, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Assign Permission to User",
        description=(
            "Assign a specific permission to a user for this event, granting them access to perform specific actions. "
            "Creates an EventPermissionAssignment linking user, event, and permission. "
            "Prevents duplicate assignments to the same user for the same permission. "
            "Only event creators, staff, and superusers can assign permissions."
        ),
        tags=["Events"],
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
        summary="Check User Permissions",
        description=(
            "Check what permissions a user has for this event including ownership status, staff membership, and assigned permissions. "
            "Returns a comprehensive overview of user's access rights for the event. "
            "If no user_id is provided, checks permissions for the currently authenticated user."
        ),
        tags=["Events"],
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
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
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
    filterset_fields = ['event', 'status', 'reviewed_by']
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
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
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
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event', 'user', 'permission']
    
    def perform_create(self, serializer):
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
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
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
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event', 'user', 'role']
    
    def perform_create(self, serializer):
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
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
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
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event', 'user']
    
    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


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
        summary="List Event Reviews",
        description=(
            "Retrieve a paginated list of event reviews submitted by attendees. "
            "Reviews include ratings, comments, and approval status for moderation. "
            "Supports filtering by event and approval status to manage review visibility."
        ),
        tags=["Event Reviews"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
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
            OpenApiParameter(name='event', type=OpenApiTypes.INT, description='Filter by event ID'),
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
    filterset_fields = ['event', 'question_type', 'required', 'public']
    ordering_fields = ['order', 'created_at']
    ordering = ['order']


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
    filterset_fields = ['question', 'attendee']


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
            OpenApiParameter(name='event', type=OpenApiTypes.UUID, description='Filter by event ID (UUID)'),
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
    filterset_fields = ['event', 'venue']
    search_fields = ['event__title', 'event__display_code', 'venue__poi__name', 'venue__poi__city']
    ordering_fields = ['event__start_datetime', 'venue__poi__name']
    ordering = ['-event__start_datetime']
    lookup_field = 'event_venue_id'
