from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes

from apps.events.models import (EventVenue, EventVenueRoom, EventVenueContact, EventVenueMetadata)
from apps.events.api.serializers import (EventVenueSerializer, EventVenueRoomSerializer, EventVenueContactSerializer, EventVenueMetadataSerializer)
from apps.events.api.filtersets import (EventVenueFilterSet)
from apps.events.api.pagination import StandardPagination


@extend_schema_view(
    list=extend_schema(
        summary="List Event Venues",
        description=(
            "Retrieve a paginated list of all event-scoped venue snapshots. "
            "Each record is a self-contained copy of venue data owned by its event. "
            "Supports filtering by event and searching by name, city, or display code."
        ),
        tags=["Event Venues"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.STR, description='Alias: filter by event URL-safe title'),
            OpenApiParameter(name='source_venue_id', type=OpenApiTypes.INT, description='Filter by source global venue ID'),
            OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search by name, city, or event display code'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Venue Details",
        description=(
            "Retrieve a specific event-scoped venue snapshot including all inline venue data, "
            "rooms, contacts, and metadata — in a single API call."
        ),
        tags=["Event Venues"],
    ),
    create=extend_schema(
        summary="Create Event Venue Snapshot",
        description=(
            "Create an event-scoped venue snapshot. Supply ``source_venue_id`` to clone all "
            "fields from an existing global Venue record (rooms, contacts, and metadata are "
            "copied automatically). Omit ``source_venue_id`` and provide inline fields directly "
            "to create a venue that has no global counterpart. "
            "Requires authentication."
        ),
        tags=["Event Venues"],
    ),
    update=extend_schema(
        summary="Update Event Venue Snapshot",
        description="Full update of an event-scoped venue snapshot. Use PATCH for partial updates.",
        tags=["Event Venues"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Venue Snapshot",
        description="Partial update of an event-scoped venue snapshot.",
        tags=["Event Venues"],
    ),
    destroy=extend_schema(
        summary="Delete Event Venue Snapshot",
        description="Remove an event-scoped venue snapshot from an event.",
        tags=["Event Venues"],
    ),
)
class EventVenueViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event-scoped venue snapshots.

    On create, if ``source_venue_id`` is present in the validated data the
    viewset will attempt to clone all fields from the matching global Venue
    (including its rooms, contacts, and metadata) before saving.  If the
    source cannot be found the record is still created using whatever inline
    field values the caller provides.
    """
    queryset = EventVenue.objects.select_related('event').prefetch_related(
        'rooms', 'contacts', 'metadata'
    ).all()
    serializer_class = EventVenueSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventVenueFilterSet
    search_fields = ['event__title', 'event__display_code', 'name', 'city']
    ordering_fields = ['event__start_datetime', 'name']
    ordering = ['-event__start_datetime']
    lookup_field = 'event_venue_id'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.IsAuthenticatedOrReadOnly()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        """
        Clone global Venue data into the snapshot when source_venue_id is supplied.
        """
        from apps.locations.models import Venue as GlobalVenue

        source_venue_id = serializer.validated_data.get('source_venue_id')
        extra_fields = {}

        if source_venue_id:
            try:
                global_venue = GlobalVenue.objects.select_related('poi').prefetch_related(
                    'rooms', 'contacts', 'metadata'
                ).get(pk=source_venue_id)
                poi = global_venue.poi
                extra_fields = {
                    'name': poi.name,
                    'address': poi.address,
                    'postcode': poi.postcode,
                    'city': poi.city,
                    'poi_type': poi.poi_type,
                    'latitude': poi.latitude,
                    'longitude': poi.longitude,
                    'description': global_venue.description,
                    'instructions': global_venue.instructions,
                    'notes': global_venue.notes,
                    'capacity': global_venue.capacity,
                }
            except GlobalVenue.DoesNotExist:
                pass  # Caller-supplied inline fields are used as-is

        event_venue = serializer.save(**extra_fields)

        # Clone sub-resources when a source was resolved
        if source_venue_id and extra_fields:
            EventVenueRoom.objects.bulk_create([
                EventVenueRoom(
                    event_venue=event_venue,
                    room_name=r.room_name,
                    description=r.description,
                    capacity=r.capacity,
                )
                for r in global_venue.rooms.all()
            ])
            EventVenueContact.objects.bulk_create([
                EventVenueContact(
                    event_venue=event_venue,
                    contact_name=c.contact_name,
                    phone_number=c.phone_number,
                    email=c.email,
                    role=c.role,
                )
                for c in global_venue.contacts.all()
            ])
            EventVenueMetadata.objects.bulk_create([
                EventVenueMetadata(
                    event_venue=event_venue,
                    label=m.label,
                    value=m.value,
                )
                for m in global_venue.metadata.all()
            ])


# ── Sub-resource ViewSets ─────────────────────────────────────────────────────

class EventVenueRoomViewSet(viewsets.ModelViewSet):
    """Manage rooms scoped to an EventVenue snapshot."""
    serializer_class = EventVenueRoomSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event_venue']

    def get_queryset(self):
        return EventVenueRoom.objects.select_related('event_venue').all()


class EventVenueContactViewSet(viewsets.ModelViewSet):
    """Manage contacts scoped to an EventVenue snapshot."""
    serializer_class = EventVenueContactSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event_venue']

    def get_queryset(self):
        return EventVenueContact.objects.select_related('event_venue').all()


class EventVenueMetadataViewSet(viewsets.ModelViewSet):
    """Manage metadata entries scoped to an EventVenue snapshot."""
    serializer_class = EventVenueMetadataSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['event_venue']

    def get_queryset(self):
        return EventVenueMetadata.objects.select_related('event_venue').all()