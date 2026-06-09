from drf_spectacular.utils import extend_schema, extend_schema_view

from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from apps.common.pagination import StandardPagination
from apps.workshops.models.staff import WorkshopStaff
from apps.workshops.api.serializers import WorkshopStaffSerializer, WorkshopStaffCreateSerializer
from apps.workshops.api.permissions import IsWorkshopEventStaffOrReadOnly


@extend_schema_view(
    list=extend_schema(
        summary="List Workshop Staff",
        description="Retrieve a paginated list of staff assignments for workshops.",
        tags=["Workshop Staff"],
    ),
    retrieve=extend_schema(
        summary="Get Workshop Staff Member",
        description="Retrieve details of a single staff assignment for a workshop.",
        tags=["Workshop Staff"],
    ),
    create=extend_schema(
        summary="Assign Staff to Workshop",
        description=(
            "Assign an event staff member to a workshop with a specified role. "
            "The staff member must already be assigned to the parent event."
        ),
        tags=["Workshop Staff"],
    ),
    update=extend_schema(
        summary="Update Staff Assignment",
        description="Replace all fields of a workshop staff assignment.",
        tags=["Workshop Staff"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Staff Assignment",
        description="Update individual fields of a workshop staff assignment (e.g. role or notes).",
        tags=["Workshop Staff"],
    ),
    destroy=extend_schema(
        summary="Remove Staff from Workshop",
        description="Remove a staff assignment from a workshop.",
        tags=["Workshop Staff"],
    ),
)
class WorkshopStaffViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing staff assignments on workshops.

    Staff must first be assigned to the parent event via EventStaff before they
    can be added to individual workshops.
    """

    queryset = WorkshopStaff.objects.select_related('workshop', 'event_staff', 'added_by').all()
    pagination_class = StandardPagination
    permission_classes = [IsWorkshopEventStaffOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['workshop', 'role']
    ordering_fields = ['added_at', 'role']
    ordering = ['-added_at']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return WorkshopStaffCreateSerializer
        return WorkshopStaffSerializer

    def perform_create(self, serializer):
        serializer.save(added_by=self.request.user)
