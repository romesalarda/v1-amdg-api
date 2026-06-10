from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.common.pagination import StandardPagination
from apps.workshops.models.workshop import Workshop, WorkshopStatus, AllocationMode
from apps.workshops.models.registration import WorkshopRegistration
from apps.workshops.api.serializers import (
    WorkshopListSerializer,
    WorkshopDetailSerializer,
    WorkshopCreateUpdateSerializer,
    WorkshopRegistrationListSerializer,
)
from apps.workshops.api.filtersets import WorkshopFilterSet
from apps.workshops.api.permissions import IsWorkshopEventStaffOrReadOnly, CanManageWorkshopAllocations
from apps.workshops import services


@extend_schema_view(
    list=extend_schema(
        summary="List Workshops",
        description=(
            "Retrieve a paginated list of workshops. Supports filtering by event, status, "
            "allocation mode, and date range. Open workshops are visible to all authenticated users; "
            "draft/closed workshops are accessible to event staff only."
        ),
        tags=["Workshops"],
    ),
    retrieve=extend_schema(
        summary="Get Workshop Details",
        description="Retrieve full details for a single workshop including capacity and registration statistics.",
        tags=["Workshops"],
    ),
    create=extend_schema(
        summary="Create Workshop",
        description="Create a new workshop for an event. Only event staff may create workshops.",
        tags=["Workshops"],
    ),
    update=extend_schema(
        summary="Update Workshop",
        description="Replace all workshop fields. Use PATCH for partial updates.",
        tags=["Workshops"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Workshop",
        description="Update individual workshop fields.",
        tags=["Workshops"],
    ),
    destroy=extend_schema(
        summary="Delete Workshop",
        description="Delete a workshop. All registrations and interest submissions will also be removed.",
        tags=["Workshops"],
    ),
)
class WorkshopViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing workshops within events.

    Custom actions:
    - open_registrations: transition status → OPEN
    - close_registrations: transition status → CLOSED
    - run_allocation: trigger the workshop's configured allocation mode
    - registrations: list all registrations for this workshop
    """

    queryset = Workshop.objects.select_related('event', 'venue', 'room').all()
    pagination_class = StandardPagination
    permission_classes = [IsWorkshopEventStaffOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = WorkshopFilterSet
    search_fields = ['title', 'description']
    ordering_fields = ['date', 'title', 'status']
    ordering = ['date']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return WorkshopCreateUpdateSerializer
        if self.action == 'retrieve':
            return WorkshopDetailSerializer
        return WorkshopListSerializer

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Open Registrations",
        description="Transition the workshop status to OPEN, allowing attendees to register.",
        tags=["Workshops"],
        responses={200: WorkshopDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='open-registrations',
            permission_classes=[CanManageWorkshopAllocations])
    def open_registrations(self, request, pk=None):
        workshop = self.get_object()
        if workshop.status == WorkshopStatus.CANCELLED:
            return Response({'detail': 'Cannot open a cancelled workshop.'}, status=status.HTTP_400_BAD_REQUEST)
        workshop.status = WorkshopStatus.OPEN
        workshop.save(update_fields=['status'])
        return Response(WorkshopDetailSerializer(workshop, context={'request': request}).data)

    @extend_schema(
        summary="Close Registrations",
        description="Transition the workshop status to CLOSED. New registrations will no longer be accepted.",
        tags=["Workshops"],
        responses={200: WorkshopDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='close-registrations',
            permission_classes=[CanManageWorkshopAllocations])
    def close_registrations(self, request, pk=None):
        workshop = self.get_object()
        if workshop.status not in (WorkshopStatus.OPEN, WorkshopStatus.DRAFT):
            return Response({'detail': 'Workshop is not in a closeable state.'}, status=status.HTTP_400_BAD_REQUEST)
        workshop.status = WorkshopStatus.CLOSED
        workshop.save(update_fields=['status'])
        return Response(WorkshopDetailSerializer(workshop, context={'request': request}).data)

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Run Allocation",
        description=(
            "Trigger allocation for the workshop based on its configured allocation_mode.\n\n"
            "- **FCFS**: No-op (registrations are confirmed at creation time).\n"
            "- **RANDOM**: Randomly confirm PENDING_ALLOCATION registrations up to capacity.\n"
            "- **INTEREST_RANKING**: Run the greedy rank-based allocation across the entire event "
            "(honours finalised interest submissions).\n"
            "- **MANUAL**: No-op (staff must use the confirm action on individual registrations).\n\n"
            "Only event staff may trigger allocation."
        ),
        tags=["Workshops"],
        responses={200: OpenApiResponse(description="Allocation result message or updated workshop details.")},
    )
    @action(detail=True, methods=['post'], url_path='run-allocation',
            permission_classes=[CanManageWorkshopAllocations])
    def run_allocation(self, request, pk=None):
        workshop = self.get_object()
        mode = workshop.allocation_mode

        if mode == AllocationMode.FCFS:
            return Response({'detail': 'FCFS mode allocates at registration time — nothing to do.'})

        if mode == AllocationMode.MANUAL:
            return Response({'detail': 'Manual mode — use the confirm action on individual registrations.'})

        if mode == AllocationMode.RANDOM:
            result = services.run_random_allocation(workshop, allocated_by=request.user)
            return Response(result)

        if mode == AllocationMode.INTEREST_RANKING:
            # Interest ranking is an event-wide operation — always run across all
            # workshops so that fallback ranks from attendee submissions are honoured.
            result = services.run_interest_ranking_allocation(
                event=workshop.event,
                workshops=None,
                allocated_by=request.user,
            )
            return Response(result)

        return Response({'detail': 'Unknown allocation mode.'}, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # Nested registrations read
    # ------------------------------------------------------------------

    @extend_schema(
        summary="List Workshop Registrations",
        description="List all registrations for this workshop with status filtering.",
        tags=["Workshops"],
        parameters=[
            OpenApiParameter('registration_status', OpenApiTypes.STR, description='Filter by registration status (CONFIRMED, WAITLISTED, CANCELLED, PENDING_ALLOCATION)'),
        ],
        responses={200: WorkshopRegistrationListSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='registrations')
    def registrations(self, request, pk=None):
        workshop = self.get_object()
        qs = workshop.registrations.select_related('attendee').all()
        status_filter = request.query_params.get('registration_status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = WorkshopRegistrationListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = WorkshopRegistrationListSerializer(qs, many=True, context={'request': request})
        return Response(serializer.data)
