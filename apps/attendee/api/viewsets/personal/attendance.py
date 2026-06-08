from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.attendee.models import EventAttendance
from apps.attendee.api.serializers import EventAttendanceSerializer
from apps.attendee.api.filtersets import EventAttendanceFilterSet
from apps.attendee.api.permissions import IsEventStaffOrReadOnly
from apps.common.pagination import StandardPagination

@extend_schema_view(
    list=extend_schema(
        summary="List Event Attendances",
        description=(
            "Retrieve a list of event attendance records tracking attendee check-ins and check-outs. "
            "Shows who attended events, arrival and departure times, and staff who processed check-in/check-out. "
            "Useful for attendance reporting, capacity monitoring, and event analytics. "
            "Supports filtering by event, attendee, and date ranges."
        ),
        tags=['Event Attendance']
    ),
    retrieve=extend_schema(
        summary="Get Attendance Details",
        description=(
            "Retrieve detailed information about a specific attendance record including "
            "event details, attendee information, check-in and check-out timestamps, and processing staff members."
        ),
        tags=['Event Attendance']
    ),
    create=extend_schema(
        summary="Create Attendance Record",
        description=(
            "Create a new attendance record when an attendee arrives at an event. "
            "Records check-in time and staff member who processed the check-in. "
            "Enables real-time event capacity monitoring and attendance tracking."
        ),
        tags=['Event Attendance']
    ),
    update=extend_schema(
        summary="Update Attendance Record",
        description=(
            "Update an attendance record, typically to record check-out when an attendee leaves. "
            "Can also be used to correct check-in times or update processing staff information. "
            "Records check-out timestamp and staff member who processed departure."
        ),
        tags=['Event Attendance']
    ),
    partial_update=extend_schema(
        summary="Partially Update Attendance Record",
        description="Partially update attendance details such as check-out time without providing complete payload.",
        tags=['Event Attendance']
    ),
    destroy=extend_schema(
        summary="Delete Attendance Record",
        description="Delete an attendance record (use with caution as this affects attendance history).",
        tags=['Event Attendance']
    )
)
class EventAttendanceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing EventAttendance records.
    
    Tracks attendee presence at events with check-in and check-out functionality.
    Supports real-time attendance monitoring, capacity management, and event analytics.
    Records staff responsible for processing attendance for audit purposes.
    """
    
    queryset = EventAttendance.objects.select_related('event', 'attendee', 'check_in_by', 'check_out_by').all()
    serializer_class = EventAttendanceSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventAttendanceFilterSet
    ordering_fields = ['check_in_time', 'check_out_time']
    ordering = ['-check_in_time']
