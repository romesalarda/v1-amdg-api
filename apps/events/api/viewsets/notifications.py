from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes
from django.db.models import Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action

from apps.events.models import (EventNotification,)
from apps.events.api.serializers import EventNotificationSerializer
from apps.events.api.filtersets import EventNotificationFilterSet

from apps.events.api.pagination import StandardPagination

from apps.events.api.permissions import (
    IsEventOwnerOrStaffMember,
)


@extend_schema_view(
    list=extend_schema(
        summary="List Event Notifications",
        description=(
            "Retrieve a paginated list of event notifications. "
            "Notifications are system-generated and cannot be created or updated via the API. "
            "Only event staff, creators, and Django admins can view notifications. "
            "Supports filtering by event, type, priority, read status, and related objects."
        ),
        tags=["Event Notifications"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.INT, description='Filter by event ID'),
            OpenApiParameter(name='notification_type', type=OpenApiTypes.STR, description='Filter by notification type (multi-value)'),
            OpenApiParameter(name='priority', type=OpenApiTypes.STR, description='Filter by priority (multi-value)'),
            OpenApiParameter(name='is_read', type=OpenApiTypes.BOOL, description='Filter by read status'),
            OpenApiParameter(name='related_payment', type=OpenApiTypes.INT, description='Filter by related payment ID'),
            OpenApiParameter(name='related_order', type=OpenApiTypes.INT, description='Filter by related order ID'),
            OpenApiParameter(name='related_booking', type=OpenApiTypes.INT, description='Filter by related booking ID'),
            OpenApiParameter(name='created_after', type=OpenApiTypes.DATETIME, description='Filter notifications created after this datetime'),
            OpenApiParameter(name='created_before', type=OpenApiTypes.DATETIME, description='Filter notifications created before this datetime'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Notification",
        description="Retrieve details of a specific event notification.",
        tags=["Event Notifications"],
    ),
    destroy=extend_schema(
        summary="Delete Event Notification",
        description=(
            "Permanently delete an event notification. "
            "Only event staff, creators, and Django admins can delete notifications."
        ),
        tags=["Event Notifications"],
    ),
)
class EventNotificationViewSet(viewsets.GenericViewSet,
                               viewsets.mixins.ListModelMixin,
                               viewsets.mixins.RetrieveModelMixin,
                               viewsets.mixins.DestroyModelMixin):
    """
    ViewSet for EventNotification.

    - List / Retrieve / Delete are supported.
    - Create and Update are intentionally disabled; notifications are system-generated.
    - The mark_read action allows marking a single notification as read.
    - The mark_all_read action bulk-marks notifications as read (filtered queryset).
    """

    permission_classes = [permissions.IsAuthenticated, IsEventOwnerOrStaffMember]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventNotificationFilterSet
    ordering_fields = ['created_at', 'priority', 'notification_type']
    ordering = ['-created_at']

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EventNotification.objects.none()
        user = self.request.user
        qs = EventNotification.objects.select_related(
            'event', 'related_payment', 'related_order', 'related_booking', 'created_by'
        )
        if user.is_staff or user.is_superuser:
            return qs.all()
        # Restrict to events where the user is creator or assigned staff
        return qs.filter(
            Q(event__created_by=user) |
            Q(event__staff_members__user=user)
        ).distinct()

    def get_serializer_class(self):
        return EventNotificationSerializer

    @extend_schema(
        summary="Mark Notification as Read",
        description="Mark a single event notification as read. Sets is_read=True and records read_at timestamp.",
        request=None,
        responses={200: EventNotificationSerializer},
        tags=["Event Notifications"],
    )
    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.mark_as_read()
        serializer = self.get_serializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Mark All Notifications as Read",
        description=(
            "Bulk-mark notifications as read. Applies the current query filters so you can, "
            "for example, mark all unread notifications for a specific event as read. "
            "Returns the count of notifications updated."
        ),
        request=None,
        responses={200: {'type': 'object', 'properties': {'marked_read': {'type': 'integer'}}}},
        tags=["Event Notifications"],
    )
    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        now = timezone.now()
        qs = self.filter_queryset(self.get_queryset()).filter(is_read=False)
        count = qs.update(is_read=True, read_at=now)
        return Response({'marked_read': count}, status=status.HTTP_200_OK)
