"""
Event-venue-scoped floor plan viewsets.

These viewsets expose FloorPlan, FloorPlanAnnotation, and
FloorPlanAnnotationMetadata resources nested under an EventVenue (UUID
primary key).  Floor plans are resolved by:

  1. Floor plans directly linked to the EventVenue via FloorPlan.event_venue.
  2. Floor plans of the underlying global Venue (FloorPlan.venue_id ==
     event_venue.source_venue_id) that have not yet been migrated (i.e.
     event_venue is NULL on the floor-plan record).  This provides
     backwards-compatibility until full migration is complete.

When creating a new floor plan through this endpoint the EventVenue is
automatically set on the record (FloorPlan.event_venue).  The required
FloorPlan.venue FK is satisfied by the event venue's source global venue; if
no source venue is linked, the caller must supply ``venue`` explicitly.

URL patterns (registered in apps/events/urls.py):
  /api/events/event-venues/<event_venue_pk>/floor-plans/
  /api/events/event-venues/<event_venue_pk>/floor-plans/<pk>/
  /api/events/event-venues/<event_venue_pk>/floor-plans/<floor_plan_pk>/annotations/
  /api/events/event-venues/<event_venue_pk>/floor-plans/<floor_plan_pk>/annotations/<pk>/
  /api/events/event-venues/<event_venue_pk>/floor-plans/<floor_plan_pk>/annotations/<annotation_pk>/metadata/
  /api/events/event-venues/<event_venue_pk>/floor-plans/<floor_plan_pk>/annotations/<annotation_pk>/metadata/<pk>/
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import filters, permissions, serializers as drf_serializers, viewsets
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.events.models import EventVenue
from apps.locations.models import (
    FloorPlan,
    FloorPlanAnnotation,
    FloorPlanAnnotationMetadata,
    Venue,
)
from apps.locations.api.serializers import (
    FloorPlanAnnotationMetadataSerializer,
    FloorPlanAnnotationSerializer,
    FloorPlanCreateUpdateSerializer,
    FloorPlanDetailSerializer,
    FloorPlanListSerializer,
)
from apps.locations.api.viewsets import StandardPagination
from .permissions import CanManageEventVenueFloorPlans


# ---------------------------------------------------------------------------
# Serializer variant: venue is optional (injected from event_venue.source)
# ---------------------------------------------------------------------------

class EventVenueFloorPlanCreateSerializer(FloorPlanCreateUpdateSerializer):
    """
    Like FloorPlanCreateUpdateSerializer but ``venue`` is optional.

    When the EventVenue has a source_venue_id the endpoint automatically
    resolves the global Venue; callers only need to supply ``venue`` when no
    source venue is linked to the event venue.
    """

    venue = drf_serializers.PrimaryKeyRelatedField(
        queryset=Venue.objects.all(),
        required=False,
        allow_null=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _floor_plan_q_for_event_venue(event_venue: EventVenue) -> Q:
    """Return a Q object matching floor plans that belong to *event_venue*."""
    q = Q(event_venue_id=event_venue.event_venue_id)
    if event_venue.source_venue_id:
        # Include legacy floor plans on the source venue not yet migrated
        q |= Q(venue_id=event_venue.source_venue_id, event_venue__isnull=True)
    return q


# ---------------------------------------------------------------------------
# Floor Plan ViewSet
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(
        summary="List floor plans for an event venue",
        description=(
            "Returns floor plans directly linked to the EventVenue plus "
            "floor plans inherited from the underlying global Venue (when a "
            "source_venue_id is set and the floor plan has not yet been "
            "migrated to reference the EventVenue directly)."
        ),
        tags=["Event Floor Plans"],
    ),
    retrieve=extend_schema(
        summary="Retrieve an event-venue floor plan",
        tags=["Event Floor Plans"],
    ),
    create=extend_schema(
        summary="Upload a floor plan for an event venue",
        description=(
            "Creates a new FloorPlan linked to the EventVenue.  The global "
            "Venue FK is resolved automatically from event_venue.source_venue_id "
            "unless ``venue`` is supplied explicitly."
        ),
        tags=["Event Floor Plans"],
    ),
    update=extend_schema(summary="Update a floor plan", tags=["Event Floor Plans"]),
    partial_update=extend_schema(summary="Partially update a floor plan", tags=["Event Floor Plans"]),
    destroy=extend_schema(summary="Delete a floor plan", tags=["Event Floor Plans"]),
)
class EventVenueFloorPlanViewSet(viewsets.ModelViewSet):
    """Floor plans scoped to an EventVenue (UUID)."""

    pagination_class = StandardPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["level", "name", "added_at"]
    ordering = ["level", "name"]

    # ── Permissions ───────────────────────────────────────────────────────

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [CanManageEventVenueFloorPlans()]

    # ── Queryset ──────────────────────────────────────────────────────────

    def _get_event_venue(self) -> EventVenue:
        return get_object_or_404(
            EventVenue.objects.select_related("event"),
            event_venue_id=self.kwargs["event_venue_pk"],
        )

    def get_queryset(self):
        try:
            ev = EventVenue.objects.get(event_venue_id=self.kwargs["event_venue_pk"])
        except EventVenue.DoesNotExist:
            return FloorPlan.objects.none()

        return (
            FloorPlan.objects.filter(_floor_plan_q_for_event_venue(ev))
            .select_related("venue__poi", "added_by")
            .prefetch_related("annotations__metadata", "annotations__room_venue")
        )

    # ── Serializer ────────────────────────────────────────────────────────

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EventVenueFloorPlanCreateSerializer
        if self.action == "retrieve":
            return FloorPlanDetailSerializer
        return FloorPlanListSerializer

    # ── Write helpers ─────────────────────────────────────────────────────

    def perform_create(self, serializer):
        ev = self._get_event_venue()
        extra: dict = {"event_venue": ev}

        # Resolve venue from source if not explicitly supplied
        supplied_venue = serializer.validated_data.get("venue")
        if supplied_venue is None:
            if ev.source_venue_id:
                try:
                    extra["venue"] = Venue.objects.get(pk=ev.source_venue_id)
                except Venue.DoesNotExist:
                    pass
            if "venue" not in extra:
                raise drf_serializers.ValidationError(
                    {
                        "venue": (
                            "This event venue has no linked global venue. "
                            "Please supply 'venue' explicitly."
                        )
                    }
                )

        serializer.save(**extra)


# ---------------------------------------------------------------------------
# Annotation ViewSet
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List annotations for a floor plan", tags=["Event Floor Plans"]),
    retrieve=extend_schema(summary="Retrieve an annotation", tags=["Event Floor Plans"]),
    create=extend_schema(summary="Create an annotation", tags=["Event Floor Plans"]),
    update=extend_schema(summary="Update an annotation", tags=["Event Floor Plans"]),
    partial_update=extend_schema(summary="Partially update an annotation", tags=["Event Floor Plans"]),
    destroy=extend_schema(summary="Delete an annotation", tags=["Event Floor Plans"]),
)
class EventVenueFloorPlanAnnotationViewSet(viewsets.ModelViewSet):
    """
    Annotations scoped to a floor plan under an EventVenue.

    Nested under:
      /api/events/event-venues/{event_venue_pk}/floor-plans/{floor_plan_pk}/annotations/
    """

    serializer_class = FloorPlanAnnotationSerializer
    pagination_class = StandardPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["label", "added_at"]
    ordering = ["label"]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [CanManageEventVenueFloorPlans()]

    def _get_floor_plan(self) -> FloorPlan:
        """Return the floor plan, validated as belonging to the event venue."""
        event_venue_pk = self.kwargs["event_venue_pk"]
        floor_plan_pk = self.kwargs["floor_plan_pk"]

        try:
            ev = EventVenue.objects.get(event_venue_id=event_venue_pk)
        except EventVenue.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Event venue not found.")

        fp = get_object_or_404(
            FloorPlan.objects.filter(_floor_plan_q_for_event_venue(ev)),
            pk=floor_plan_pk,
        )
        return fp

    def get_queryset(self):
        event_venue_pk = self.kwargs["event_venue_pk"]
        floor_plan_pk = self.kwargs["floor_plan_pk"]

        try:
            ev = EventVenue.objects.get(event_venue_id=event_venue_pk)
        except EventVenue.DoesNotExist:
            return FloorPlanAnnotation.objects.none()

        # Confirm the floor plan belongs to this event venue
        if not FloorPlan.objects.filter(
            _floor_plan_q_for_event_venue(ev), pk=floor_plan_pk
        ).exists():
            return FloorPlanAnnotation.objects.none()

        return (
            FloorPlanAnnotation.objects.filter(floor_plan_id=floor_plan_pk)
            .select_related("room_venue", "added_by")
            .prefetch_related("metadata")
        )

    def perform_create(self, serializer):
        floor_plan = self._get_floor_plan()
        serializer.save(floor_plan=floor_plan, added_by=self.request.user)


# ---------------------------------------------------------------------------
# Annotation Metadata ViewSet
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List metadata for an annotation", tags=["Event Floor Plans"]),
    retrieve=extend_schema(summary="Retrieve annotation metadata", tags=["Event Floor Plans"]),
    create=extend_schema(summary="Add metadata to an annotation", tags=["Event Floor Plans"]),
    update=extend_schema(summary="Update annotation metadata", tags=["Event Floor Plans"]),
    partial_update=extend_schema(summary="Partially update annotation metadata", tags=["Event Floor Plans"]),
    destroy=extend_schema(summary="Delete annotation metadata", tags=["Event Floor Plans"]),
)
class EventVenueFloorPlanAnnotationMetadataViewSet(viewsets.ModelViewSet):
    """
    Metadata entries scoped to an annotation.

    Nested under:
      .../annotations/{annotation_pk}/metadata/
    """

    serializer_class = FloorPlanAnnotationMetadataSerializer
    pagination_class = StandardPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["label", "added_at"]
    ordering = ["label"]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [CanManageEventVenueFloorPlans()]

    def get_queryset(self):
        annotation_pk = self.kwargs["annotation_pk"]
        return FloorPlanAnnotationMetadata.objects.filter(
            annotation_id=annotation_pk,
        ).select_related("added_by")

    def perform_create(self, serializer):
        annotation_pk = self.kwargs["annotation_pk"]
        annotation = get_object_or_404(FloorPlanAnnotation, pk=annotation_pk)
        serializer.save(annotation=annotation, added_by=self.request.user)
