from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.attendee.models import AttendeeAction
from apps.attendee.api.serializers import AttendeeActionSerializer
from apps.attendee.api.filtersets import AttendeeActionFilterSet
from apps.attendee.api.permissions import IsEventStaffOrReadOnly
from apps.common.pagination import StandardPagination

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Actions",
        description=(
            "Retrieve an audit log of actions performed on attendees. "
            "Tracks check-ins, check-outs, registrations, and other attendee-related events. "
            "Useful for compliance, reporting, and activity monitoring."
        ),
        tags=['Attendee Actions']
    ),
    retrieve=extend_schema(
        summary="Get Action Details",
        description=(
            "Retrieve detailed information about a specific attendee action including "
            "the action type, performer, timestamp, and associated attendee."
        ),
        tags=['Attendee Actions']
    ),
    create=extend_schema(
        summary="Create Attendee Action",
        description=(
            "Log a new action performed on an attendee such as check-in, check-out, or status change. "
            "Creates an immutable audit trail entry for compliance and tracking purposes."
        ),
        tags=['Attendee Actions']
    )
)
class AttendeeActionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeAction records.
    
    Provides an audit trail of actions performed on attendees throughout their lifecycle.
    Actions are immutable once created (no update/delete) to maintain audit integrity.
    Restricted to event staff for action creation.
    """
    
    queryset = AttendeeAction.objects.select_related('attendee', 'performed_by').all()
    serializer_class = AttendeeActionSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeActionFilterSet
    ordering_fields = ['performed_at']
    ordering = ['-performed_at']
    http_method_names = ['get', 'post', 'head', 'options']  # No update/delete
