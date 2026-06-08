from rest_framework import viewsets, filters
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.attendee.models import AttendeeMessage
from apps.attendee.api.serializers import (
    AttendeeMessageListSerializer, AttendeeMessageDetailSerializer,
    AttendeeMessageCreateSerializer, AttendeeMessageUpdateSerializer,

)
from apps.attendee.api.filtersets import AttendeeMessageFilterSet
from apps.attendee.api.permissions import CanAccessMessages
from apps.common.pagination import StandardPagination

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Messages",
        description=(
            "Retrieve a list of messages sent to or from attendees. "
            "Messages can be inquiries, requests, or communications between attendees and staff. "
            "Supports filtering by priority (low, medium, high) and response status."
        ),
        tags=['Attendee Messages']
    ),
    retrieve=extend_schema(
        summary="Get Message Details",
        description=(
            "Retrieve full details of a specific attendee message including subject, message content, "
            "priority level, submission timestamp, response details, and staff notes. "
            "Shows complete message thread with any staff responses."
        ),
        tags=['Attendee Messages']
    ),
    create=extend_schema(
        summary="Create Message",
        description=(
            "Create a new message from or about an attendee. "
            "Messages can be submitted by attendees with questions or requests, or by staff for record-keeping. "
            "Priority levels (low, medium, high) help staff prioritize responses."
        ),
        tags=['Attendee Messages']
    ),
    update=extend_schema(
        summary="Update Message",
        description=(
            "Update a message, primarily used by staff to add responses or administrative notes. "
            "Can update priority level, response content, and internal staff notes. "
            "Response timestamp is automatically recorded when staff responds."
        ),
        tags=['Attendee Messages']
    ),
    partial_update=extend_schema(
        summary="Partially Update Message",
        description=(
            "Partially update message fields such as priority, response, or admin notes "
            "without providing the complete message payload."
        ),
        tags=['Attendee Messages']
    )
)
class AttendeeMessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeMessage records.
    
    Handles communication between attendees and event staff including:
    - Inquiries and requests from attendees
    - Staff responses and internal notes
    - Priority management for message triage
    - Message threading and history
    """
    
    queryset = AttendeeMessage.objects.select_related('attendee', 'responsed_by').all()
    permission_classes = [CanAccessMessages]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeMessageFilterSet
    ordering_fields = ['submitted_at', 'priority']
    ordering = ['-submitted_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AttendeeMessageListSerializer
        elif self.action == 'create':
            return AttendeeMessageCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AttendeeMessageUpdateSerializer
        return AttendeeMessageDetailSerializer