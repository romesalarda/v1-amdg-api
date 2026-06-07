from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes
from apps.events.models import EventReview
from apps.events.api.serializers import EventReviewSerializer
from apps.events.api.filtersets import EventReviewFilterSet
from apps.events.api.pagination import StandardPagination

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
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
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
    filterset_class = EventReviewFilterSet
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