from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse

from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.common.pagination import StandardPagination
from apps.workshops.models.interest import WorkshopInterestSubmission
from apps.workshops.api.serializers import (
    WorkshopInterestSubmissionSerializer,
    WorkshopInterestSubmissionCreateSerializer,
)
from apps.workshops.api.filtersets import WorkshopInterestSubmissionFilterSet
from apps.workshops.api.permissions import IsWorkshopEventStaffOrReadOnly


@extend_schema_view(
    list=extend_schema(
        summary="List Interest Submissions",
        description=(
            "Retrieve a paginated list of workshop interest submissions. "
            "Each submission represents an attendee's ranked preferences across workshops for an event."
        ),
        tags=["Workshop Interest"],
    ),
    retrieve=extend_schema(
        summary="Get Interest Submission",
        description="Retrieve a single interest submission including all ranked entries.",
        tags=["Workshop Interest"],
    ),
    create=extend_schema(
        summary="Submit Interest Rankings",
        description=(
            "Create a new interest submission with an ordered list of workshop ranks. "
            "One submission per attendee per event. Finalise before allocation runs."
        ),
        tags=["Workshop Interest"],
    ),
    update=extend_schema(
        summary="Update Interest Submission",
        description="Replace all ranks in an interest submission. Submission must not be finalised.",
        tags=["Workshop Interest"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Interest Submission",
        description="Update individual fields. Ranks replacement supported via full ranks array.",
        tags=["Workshop Interest"],
    ),
    destroy=extend_schema(
        summary="Delete Interest Submission",
        description="Delete a draft interest submission. Finalised submissions cannot be deleted.",
        tags=["Workshop Interest"],
    ),
)
class WorkshopInterestSubmissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for workshop interest ranking submissions.

    Custom actions:
    - finalise: lock the submission for allocation processing
    - unfinalize: reopen a finalised submission for editing (staff only)
    """

    queryset = WorkshopInterestSubmission.objects.prefetch_related('ranks__workshop').all()
    pagination_class = StandardPagination
    permission_classes = [IsWorkshopEventStaffOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = WorkshopInterestSubmissionFilterSet
    ordering_fields = ['submitted_at', 'updated_at']
    ordering = ['-submitted_at']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return WorkshopInterestSubmissionCreateSerializer
        return WorkshopInterestSubmissionSerializer

    def destroy(self, request, *args, **kwargs):
        submission = self.get_object()
        if submission.is_finalised:
            return Response(
                {'detail': 'Cannot delete a finalised interest submission.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    # ------------------------------------------------------------------
    # Finalise / unfinalize
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Finalise Submission",
        description=(
            "Lock an interest submission so it can be included in the next allocation run. "
            "Once finalised, ranks can no longer be modified."
        ),
        tags=["Workshop Interest"],
        responses={200: WorkshopInterestSubmissionSerializer},
    )
    @action(detail=True, methods=['post'])
    def finalise(self, request, pk=None):
        submission = self.get_object()
        if submission.is_finalised:
            return Response({'detail': 'Submission is already finalised.'}, status=status.HTTP_400_BAD_REQUEST)
        if not submission.ranks.exists():
            return Response({'detail': 'Cannot finalise an empty submission.'}, status=status.HTTP_400_BAD_REQUEST)
        submission.is_finalised = True
        submission.save(update_fields=['is_finalised'])
        return Response(WorkshopInterestSubmissionSerializer(submission, context={'request': request}).data)

    @extend_schema(
        summary="Unfinalize Submission",
        description="Reopen a finalised submission for editing. Only event staff may unfinalize.",
        tags=["Workshop Interest"],
        responses={200: WorkshopInterestSubmissionSerializer},
    )
    @action(detail=True, methods=['post'], url_path='unfinalize',
            permission_classes=[permissions.IsAuthenticated])
    def unfinalize(self, request, pk=None):
        submission = self.get_object()
        if not request.user.is_staff and not request.user.is_superuser:
            # Check event staff
            from apps.workshops.api.permissions import _is_event_staff_or_owner
            if not _is_event_staff_or_owner(request.user, submission.event):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('Only event staff may unfinalize a submission.')
        if not submission.is_finalised:
            return Response({'detail': 'Submission is not finalised.'}, status=status.HTTP_400_BAD_REQUEST)
        submission.is_finalised = False
        submission.save(update_fields=['is_finalised'])
        return Response(WorkshopInterestSubmissionSerializer(submission, context={'request': request}).data)
