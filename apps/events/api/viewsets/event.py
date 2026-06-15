"""
Event viewsets — core CRUD and composition.

The EventViewSet is assembled from domain-specific action mixins.
Each mixin lives in its own module (_staff_actions, _sponsor_actions, etc.)
and contains only the @action methods and their @extend_schema decorators.

This file retains:
  - EventTypeViewSet
  - EventViewSet core (queryset, serializer selection, CRUD overrides,
    upcoming / ongoing / event_settings / ws_token / soft_delete / restore)
"""
import logging

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.events.models import Event, EventType, EventStatusChoices
from apps.events.api.serializers import (
    EventTypeSerializer,
    EventListSerializer,
    EventDetailSerializer,
    EventCreateUpdateSerializer,
    EventSettingsSerializer,
)
from apps.events.api.filtersets import EventFilterSet
from apps.events.api.pagination import StandardPagination
from apps.events.api.permissions import (
    IsEventOwnerOrDjangoStaff,
    IsEventOwnerOrEventStaffOrDjangoStaff,
)
from apps.events.services.notifications import (
    create_notification,
    NotificationTypeChoices,
    NotificationPriorityChoices,
)
from apps.events.services.websocket_token import WebSocketTokenService

# Domain-specific action mixins
from apps.events.api.viewsets.mixins.staff_actions import EventStaffActionsMixin
from apps.events.api.viewsets.mixins.sponsor_actions import EventSponsorActionsMixin
from apps.events.api.viewsets.mixins.resource_actions import EventResourceActionsMixin
from apps.events.api.viewsets.mixins.availability_actions import EventAvailabilityActionsMixin
from apps.events.api.viewsets.mixins.invite_actions import EventInviteActionsMixin
from apps.events.api.viewsets.mixins.permission_actions import EventPermissionActionsMixin
from apps.events.api.viewsets.mixins.payment_actions import EventPaymentActionsMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EventTypeViewSet
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(
        summary="List Event Types",
        description=(
            "Retrieve a paginated list of all event types available in the system. "
            "Event types categorize events by their nature such as conferences, workshops, "
            "retreats, seminars, etc. Supports search functionality by title, code, and "
            "description for easy discovery."
        ),
        tags=["Event Types"],
        parameters=[
            OpenApiParameter(name="search", type=OpenApiTypes.STR, description="Search by title or code"),
        ],
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
            "Requires authentication and appropriate permissions."
        ),
        tags=["Event Types"],
    ),
    update=extend_schema(
        summary="Update Event Type",
        description="Update all fields of an existing event type. Use PATCH for partial updates.",
        tags=["Event Types"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Type",
        description="Partially update an event type without providing complete payload.",
        tags=["Event Types"],
    ),
    destroy=extend_schema(
        summary="Delete Event Type",
        description="Delete an event type category. Use with caution if events are associated with this type.",
        tags=["Event Types"],
    ),
)
class EventTypeViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Event Types."""

    queryset = EventType.objects.all()
    serializer_class = EventTypeSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "code", "description"]
    ordering_fields = ["title", "created_at"]
    ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# EventViewSet — composed from mixins + core actions
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(
        summary="List Events",
        description=(
            "Retrieve a paginated list of all events with comprehensive filtering and search "
            "capabilities. Non-staff users only see published and active events, while staff "
            "can view all events including drafts."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name="status", type=OpenApiTypes.STR, description="Filter by status (DRAFT, PUBLISHED, OPEN, etc.)"),
            OpenApiParameter(name="event_type", type=OpenApiTypes.INT, description="Filter by event type ID"),
            OpenApiParameter(name="event_type_code", type=OpenApiTypes.STR, description="Filter by event type code"),
            OpenApiParameter(name="event_type_title", type=OpenApiTypes.STR, description="Filter by event type title"),
            OpenApiParameter(name="organisation", type=OpenApiTypes.INT, description="Filter by organisation ID"),
            OpenApiParameter(name="organisation_name", type=OpenApiTypes.STR, description="Filter by organisation name"),
            OpenApiParameter(name="location", type=OpenApiTypes.INT, description="Filter by location (area) ID"),
            OpenApiParameter(name="area", type=OpenApiTypes.INT, description="Filter by area ID"),
            OpenApiParameter(name="area_name", type=OpenApiTypes.STR, description="Filter by area name"),
            OpenApiParameter(name="chapter", type=OpenApiTypes.INT, description="Filter by chapter ID"),
            OpenApiParameter(name="chapter_name", type=OpenApiTypes.STR, description="Filter by chapter name"),
            OpenApiParameter(name="venue", type=OpenApiTypes.INT, description="Filter by venue ID"),
            OpenApiParameter(name="venue_name", type=OpenApiTypes.STR, description="Filter by venue POI name"),
            OpenApiParameter(name="venue_address", type=OpenApiTypes.STR, description="Filter by venue POI address"),
            OpenApiParameter(name="venue_city", type=OpenApiTypes.STR, description="Filter by venue city"),
            OpenApiParameter(name="venue_postcode", type=OpenApiTypes.STR, description="Filter by venue postcode"),
            OpenApiParameter(name="theme", type=OpenApiTypes.STR, description="Filter by event theme"),
            OpenApiParameter(name="anchor_verse", type=OpenApiTypes.STR, description="Filter by anchor verse"),
            OpenApiParameter(name="start_after", type=OpenApiTypes.DATETIME, description="Filter by start datetime >="),
            OpenApiParameter(name="start_before", type=OpenApiTypes.DATETIME, description="Filter by start datetime <="),
            OpenApiParameter(name="end_after", type=OpenApiTypes.DATETIME, description="Filter by end datetime >="),
            OpenApiParameter(name="end_before", type=OpenApiTypes.DATETIME, description="Filter by end datetime <="),
            OpenApiParameter(name="search", type=OpenApiTypes.STR, description="Standard text search"),
            OpenApiParameter(name="fuzzy_search", type=OpenApiTypes.STR, description="Postgres trigram fuzzy search"),
            OpenApiParameter(name="fuzzy_threshold", type=OpenApiTypes.FLOAT, description="Fuzzy similarity threshold (default 0.2)"),
        ],
    ),
    retrieve=extend_schema(
        summary="Get Event Details",
        description=(
            "Retrieve comprehensive details about a specific event including all metadata, "
            "dates, registration information, settings, staff, resources, reviews, and "
            "associated content."
        ),
        tags=["Events"],
    ),
    create=extend_schema(
        summary="Create Event",
        description=(
            "Create a new event. Automatically assigns the authenticated user as the event creator "
            "and generates a unique display code for identification."
        ),
        tags=["Events"],
    ),
    update=extend_schema(
        summary="Update Event",
        description="Update all fields of an existing event. Use PATCH for partial updates.",
        tags=["Events"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event",
        description="Partially update an event without providing complete payload.",
        tags=["Events"],
    ),
    destroy=extend_schema(
        summary="Delete Event",
        description=(
            "Soft delete an event by marking it as deleted without permanent removal. "
            "Soft-deleted events are hidden from public view but retained for audit purposes."
        ),
        tags=["Events"],
    ),
)
class EventViewSet(
    EventStaffActionsMixin,
    EventSponsorActionsMixin,
    EventResourceActionsMixin,
    EventAvailabilityActionsMixin,
    EventInviteActionsMixin,
    EventPermissionActionsMixin,
    EventPaymentActionsMixin,
    viewsets.ModelViewSet,
):
    """
    ViewSet for comprehensive event management.

    Core CRUD and a small set of first-class actions live here.
    All domain-specific actions are provided by the mixin classes above.
    """

    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventFilterSet
    search_fields = ["title", "short_description", "long_description", "display_code"]
    ordering_fields = ["title", "start_datetime", "created_at"]
    ordering = ["-start_datetime"]
    lookup_field = "url_safe_title"

    # ------------------------------------------------------------------
    # Queryset / serializer
    # ------------------------------------------------------------------

    def get_queryset(self):
        queryset = Event.objects.select_related(
            "event_type", "organisation", "created_by"
        ).prefetch_related("settings")

        user = self.request.user
        if user.is_authenticated and not user.is_staff:
            queryset = queryset.filter(
                Q(created_by=user)
                | Q(staff_members__user=user)
                | Q(
                    status__in=[
                        EventStatusChoices.PUBLISHED,
                        EventStatusChoices.OPEN,
                        EventStatusChoices.POSTPONED,
                        EventStatusChoices.IN_PROGRESS,
                        EventStatusChoices.COMPLETED,
                    ]
                )
            ).distinct()
        elif not user.is_authenticated:
            queryset = queryset.filter(
                status__in=[
                    EventStatusChoices.PUBLISHED,
                    EventStatusChoices.OPEN,
                    EventStatusChoices.POSTPONED,
                    EventStatusChoices.IN_PROGRESS,
                    EventStatusChoices.COMPLETED,
                ]
            )

        return queryset

    def get_non_restrictive_object(self):
        """
        Return the event without applying public-status filters.

        Used by actions that event creators/staff should be able to call even
        on draft or soft-deleted events (e.g. restore, accept_invite).
        """
        obj = get_object_or_404(
            Event.objects.select_related(
                "event_type", "organisation", "created_by"
            ).prefetch_related("settings"),
            url_safe_title=self.kwargs["url_safe_title"],
        )
        self.check_object_permissions(self.request, obj)
        return obj

    def get_serializer_class(self):
        if self.action == "list":
            return EventListSerializer
        if self.action in ("create", "update", "partial_update"):
            return EventCreateUpdateSerializer
        return EventDetailSerializer

    # ------------------------------------------------------------------
    # CRUD overrides
    # ------------------------------------------------------------------

    def perform_destroy(self, instance):
        return instance.soft_delete()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):

        old_event = self.get_non_restrictive_object()

        new_event = serializer.save()
        if old_event.status != new_event.status:
            create_notification(
                event=new_event,
                message=(
                    f"{self.request.user} changed the status of the event "
                    f"'{new_event.title}' from {old_event.status} to {new_event.status}"
                ),
                notification_type=NotificationTypeChoices.GENERAL,
                priority=NotificationPriorityChoices.HIGH,
                force_create=True,
            )

        return new_event

    # ------------------------------------------------------------------
    # upcoming / ongoing  (read-only, no permission class needed)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get Upcoming Events",
        description=(
            "Retrieve all upcoming events that haven't started yet, ordered by start date."
        ),
        tags=["Events"],
        responses={200: EventListSerializer(many=True)},
        parameters=[
            OpenApiParameter(name="page", type=OpenApiTypes.INT, description="Page number"),
            OpenApiParameter(name="page_size", type=OpenApiTypes.INT, description="Number of results per page"),
        ],
    )
    @action(detail=False, methods=["get"])
    def upcoming(self, request):
        queryset = self.get_queryset().filter(start_datetime__gte=timezone.now())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EventListSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = EventListSerializer(queryset, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        summary="Get Ongoing Events",
        description="Retrieve all currently active events that have started but not yet ended.",
        tags=["Events"],
        responses={200: EventListSerializer(many=True)},
        parameters=[
            OpenApiParameter(name="page", type=OpenApiTypes.INT, description="Page number"),
            OpenApiParameter(name="page_size", type=OpenApiTypes.INT, description="Number of results per page"),
        ],
    )
    @action(detail=False, methods=["get"])
    def ongoing(self, request):
        now = timezone.now()
        queryset = self.get_queryset().filter(
            start_datetime__lte=now, end_datetime__gte=now
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EventListSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = EventListSerializer(queryset, many=True, context={"request": request})
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # event_settings  (read-only)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get Event Settings",
        description=(
            "Retrieve configuration settings for a specific event including product selling options, "
            "order approval requirements, booking configuration, and other event-specific preferences."
        ),
        tags=["Events"],
        responses={
            200: EventSettingsSerializer,
            404: OpenApiResponse(description="Settings not found for this event"),
        },
    )
    @action(detail=True, methods=["get"], url_path="settings")
    def event_settings(self, request, url_safe_title=None):
        event = self.get_object()
        event_settings = getattr(event, "settings", None)
        if not event_settings:
            return Response(
                {"detail": "Settings not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = EventSettingsSerializer(event_settings)
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # soft_delete_event / restore_event
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Soft Delete Event",
        description=(
            "Soft delete an event by marking it as deleted without permanent removal. "
            "Only event creators and superusers can soft delete events."
        ),
        tags=["Events"],
        responses={
            200: OpenApiResponse(description="Event soft deleted successfully"),
            400: OpenApiResponse(description="Event is already deleted"),
            403: OpenApiResponse(description="Permission denied"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="soft-delete",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def soft_delete_event(self, request, url_safe_title=None):
        event = self.get_object()
        try:
            event.soft_delete()
            event.deleted_by = request.user
            event.save(update_fields=["deleted_by"])
            return Response(
                {
                    "detail": "Event soft deleted successfully",
                    "deleted_at": event.deleted_at.isoformat() if event.deleted_at else None,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Restore Soft-Deleted Event",
        description=(
            "Restore a previously soft-deleted event back to active status. "
            "Only event creators and superusers can restore events."
        ),
        tags=["Events"],
        responses={
            200: OpenApiResponse(description="Event restored successfully"),
            400: OpenApiResponse(description="Event is not deleted"),
            403: OpenApiResponse(description="Permission denied"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="restore",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def restore_event(self, request, url_safe_title=None):
        event = Event.all_objects.get(url_safe_title=url_safe_title)
        # Manual object-level permission check since we bypass get_object()
        self.check_object_permissions(request, event)
        if not (
            request.user.is_staff
            or request.user.is_superuser
            or event.created_by == request.user
        ):
            return Response(
                {"detail": "You don't have permission to restore this event"},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            event.restore()
            event.deleted_by = None
            event.save(update_fields=["deleted_by"])
            return Response({"detail": "Event restored successfully"}, status=status.HTTP_200_OK)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # ws_token  — WebSocket authentication
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get WebSocket Token",
        description=(
            "Exchange a valid HTTP JWT for a short-lived WebSocket-specific JWT token. "
            "This token is required to establish WebSocket connections for real-time updates.\n\n"
            "**Security:**\n"
            "- Token expires in 5 minutes\n"
            "- Token type='websocket' to prevent cross-use with HTTP endpoints\n"
            "- User must be the event creator, an event staff member, or a platform admin\n\n"
            "**Usage:**\n"
            "1. Call this endpoint with valid HTTP authentication\n"
            "2. Receive short-lived WebSocket token\n"
            "3. Connect to WebSocket using the returned URL\n"
            "4. Token must be refreshed every 5 minutes for ongoing connections\n"
        ),
        tags=["Events", "WebSocket"],
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "token": {"type": "string", "description": "WebSocket-specific JWT (5-minute expiry)"},
                        "expires_in": {"type": "integer", "description": "Token lifetime in seconds (300)"},
                        "ws_url": {"type": "string", "description": "WebSocket URL to connect to"},
                    },
                },
                description="WebSocket token successfully generated",
            ),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Event not found"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="ws-token",
        permission_classes=[IsEventOwnerOrEventStaffOrDjangoStaff],
    )
    def ws_token(self, request, *args, **kwargs):
        """
        Generate a short-lived WebSocket-specific JWT for the authenticated user.

        Delegates entirely to WebSocketTokenService so token generation logic
        is isolated and independently testable.
        """
        event = self.get_object()
        token_data = WebSocketTokenService.generate(user=request.user, event=event)
        ws_url = WebSocketTokenService.build_ws_url(
            request=request, event=event, token=token_data["token"]
        )
        return Response(
            {
                "token": token_data["token"],
                "expires_in": token_data["expires_in"],
                "ws_url": ws_url,
            }
        )
