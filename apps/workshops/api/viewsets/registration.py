from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.common.pagination import StandardPagination
from apps.workshops.models.registration import WorkshopRegistration, WorkshopRegistrationStatus
from apps.workshops.api.serializers import (
    WorkshopRegistrationListSerializer,
    WorkshopRegistrationDetailSerializer,
    WorkshopRegistrationCreateSerializer,
)
from apps.workshops.api.filtersets import WorkshopRegistrationFilterSet
from apps.workshops.api.permissions import IsWorkshopEventStaffOrReadOnly, CanManageWorkshopAllocations
from apps.workshops import services


@extend_schema_view(
    list=extend_schema(
        summary="List Workshop Registrations",
        description="Retrieve a paginated list of workshop registrations with filtering by workshop, attendee, and status.",
        tags=["Workshop Registrations"],
    ),
    retrieve=extend_schema(
        summary="Get Registration Details",
        description="Retrieve full details of a single workshop registration.",
        tags=["Workshop Registrations"],
    ),
    create=extend_schema(
        summary="Create Registration",
        description=(
            "Create a new workshop registration. For FCFS workshops the status is set automatically "
            "(CONFIRMED or WAITLISTED). For other modes use PENDING_ALLOCATION."
        ),
        tags=["Workshop Registrations"],
    ),
    update=extend_schema(
        summary="Update Registration",
        description="Replace all registration fields. Use PATCH for partial updates.",
        tags=["Workshop Registrations"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Registration",
        description="Update individual registration fields (e.g. notes).",
        tags=["Workshop Registrations"],
    ),
    destroy=extend_schema(
        summary="Delete Registration",
        description="Permanently delete a registration. Prefer the cancel action for audit purposes.",
        tags=["Workshop Registrations"],
    ),
)
class WorkshopRegistrationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing workshop registrations.

    Custom actions:
    - confirm: manually confirm a PENDING_ALLOCATION or WAITLISTED registration
    - cancel: cancel a registration (promotes next waitlisted attendee automatically)
    - promote_from_waitlist: promote the next WAITLISTED registration for a workshop
    """

    queryset = WorkshopRegistration.objects.select_related('workshop', 'attendee', 'allocated_by').all()
    pagination_class = StandardPagination
    permission_classes = [IsWorkshopEventStaffOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = WorkshopRegistrationFilterSet
    ordering_fields = ['registered_at', 'status']
    ordering = ['-registered_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return WorkshopRegistrationCreateSerializer
        if self.action == 'retrieve':
            return WorkshopRegistrationDetailSerializer
        return WorkshopRegistrationListSerializer

    def perform_create(self, serializer):
        from apps.workshops.models.workshop import AllocationMode
        workshop = serializer.validated_data['workshop']
        attendee = serializer.validated_data['attendee']

        if workshop.allocation_mode == AllocationMode.FCFS:
            services.register_fcfs(workshop, attendee, allocated_by=self.request.user)
        else:
            serializer.save(
                status=WorkshopRegistrationStatus.PENDING_ALLOCATION,
                allocation_method=workshop.allocation_mode,
            )

    # ------------------------------------------------------------------
    # Allocation management actions
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Confirm Registration",
        description="Manually confirm a PENDING_ALLOCATION or WAITLISTED registration. Only event staff may confirm.",
        tags=["Workshop Registrations"],
        responses={200: WorkshopRegistrationDetailSerializer},
    )
    @action(detail=True, methods=['post'], permission_classes=[CanManageWorkshopAllocations])
    def confirm(self, request, pk=None):
        registration = self.get_object()
        if registration.status == WorkshopRegistrationStatus.CONFIRMED:
            return Response({'detail': 'Registration is already confirmed.'}, status=status.HTTP_400_BAD_REQUEST)
        if registration.status == WorkshopRegistrationStatus.CANCELLED:
            return Response({'detail': 'Cannot confirm a cancelled registration.'}, status=status.HTTP_400_BAD_REQUEST)
        services.manual_allocate(
            workshop=registration.workshop,
            attendee=registration.attendee,
            allocated_by=request.user,
            notes=request.data.get('notes'),
        )
        registration.refresh_from_db()
        return Response(WorkshopRegistrationDetailSerializer(registration, context={'request': request}).data)

    @extend_schema(
        summary="Cancel Registration",
        description=(
            "Cancel a workshop registration. If a CONFIRMED spot is freed, the earliest "
            "WAITLISTED attendee is automatically promoted."
        ),
        tags=["Workshop Registrations"],
        responses={200: WorkshopRegistrationDetailSerializer},
    )
    @action(detail=True, methods=['post'], permission_classes=[CanManageWorkshopAllocations])
    def cancel(self, request, pk=None):
        registration = self.get_object()
        try:
            services.cancel_registration(registration, cancelled_by=request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        registration.refresh_from_db()
        return Response(WorkshopRegistrationDetailSerializer(registration, context={'request': request}).data)

    @extend_schema(
        summary="Promote from Waitlist",
        description="Promote the earliest WAITLISTED attendee for this registration's workshop to CONFIRMED.",
        tags=["Workshop Registrations"],
        responses={
            200: WorkshopRegistrationDetailSerializer,
            204: OpenApiResponse(description="No waitlisted attendees to promote."),
        },
    )
    @action(detail=True, methods=['post'], url_path='promote-waitlist',
            permission_classes=[CanManageWorkshopAllocations])
    def promote_from_waitlist(self, request, pk=None):
        registration = self.get_object()
        promoted = services.promote_from_waitlist(registration.workshop)
        if promoted is None:
            return Response({'detail': 'No waitlisted attendees to promote.'}, status=status.HTTP_204_NO_CONTENT)
        return Response(WorkshopRegistrationDetailSerializer(promoted, context={'request': request}).data)
