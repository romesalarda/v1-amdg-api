"""
Production-grade viewsets for the locations app.

Provides comprehensive viewsets for location management with proper validation,
business logic separation, schema configuration, and permission classes.

ViewSets:
    - CountryLocationViewSet: CRUD for country locations
    - ClusterLocationViewSet: CRUD for cluster locations
    - ChapterLocationViewSet: CRUD for chapter locations
    - AreaLocationViewSet: CRUD for area locations
    - RelativeAreaViewSet: CRUD for relative search areas
    - POIViewSet: CRUD for points of interest
    - VenueViewSet: CRUD for venues
    - RoomVenueViewSet: CRUD for venue rooms
    - VenueContactViewSet: CRUD for venue contacts
    - VenueMetadataViewSet: CRUD for venue metadata

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.locations.models import (
    CountryLocation, ClusterLocation, ChapterLocation, AreaLocation, RelativeArea,
    POI, Venue, RoomVenue, VenueContact, VenueMetadata
)
from .serializers import (
    CountryLocationListSerializer, CountryLocationDetailSerializer, CountryLocationCreateUpdateSerializer,
    ClusterLocationListSerializer, ClusterLocationDetailSerializer, ClusterLocationCreateUpdateSerializer,
    ChapterLocationListSerializer, ChapterLocationDetailSerializer, ChapterLocationCreateUpdateSerializer,
    AreaLocationListSerializer, AreaLocationDetailSerializer, AreaLocationCreateUpdateSerializer,
    RelativeAreaSerializer, RelativeAreaCreateUpdateSerializer,
    POIListSerializer, POIDetailSerializer, POICreateUpdateSerializer,
    VenueListSerializer, VenueDetailSerializer, VenueCreateUpdateSerializer,
    RoomVenueSerializer, RoomVenueCreateUpdateSerializer,
    VenueContactSerializer, VenueContactCreateUpdateSerializer,
    VenueMetadataSerializer, VenueMetadataCreateUpdateSerializer
)
from .filtersets import (
    CountryLocationFilterSet, ClusterLocationFilterSet, ChapterLocationFilterSet,
    AreaLocationFilterSet, RelativeAreaFilterSet, POIFilterSet, VenueFilterSet,
    RoomVenueFilterSet, VenueContactFilterSet, VenueMetadataFilterSet
)
from .permissions import IsAdministrativeStaffOrReadOnly, IsLocationManager


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration for location endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================================
# COUNTRY LOCATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List country locations",
        description="Retrieve a paginated list of country locations with filtering.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve country location details",
        description="Get detailed information about a specific country location including clusters.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create country location",
        description="Create a new country location. Requires staff permissions.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update country location",
        description="Update country location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update country location",
        description="Partially update country location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete country location",
        description="Delete a country location. Requires staff permissions.",
        tags=["Locations"],
    ),
)
class CountryLocationViewSet(viewsets.ModelViewSet):
    """ViewSet for CountryLocation CRUD operations."""
    
    queryset = CountryLocation.objects.all().order_by('country')
    permission_classes = [IsAdministrativeStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CountryLocationFilterSet
    search_fields = ['country__name']
    ordering_fields = ['country', 'general_sector', 'date_added']
    ordering = ['country']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return CountryLocationListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return CountryLocationCreateUpdateSerializer
        return CountryLocationDetailSerializer
    
    @extend_schema(
        summary="List clusters in country",
        description="Get all clusters for a specific country location.",
        responses={200: ClusterLocationListSerializer(many=True)},
        tags=["Locations"],
    )
    @action(detail=True, methods=['get'])
    def clusters(self, request, pk=None):
        """Get all clusters for a country location."""
        country = self.get_object()
        clusters = country.clusters.all().order_by('cluster_name')
        serializer = ClusterLocationListSerializer(
            clusters, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================================
# CLUSTER LOCATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List cluster locations",
        description="Retrieve a paginated list of cluster locations with filtering.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve cluster location details",
        description="Get detailed information about a specific cluster location including chapters.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create cluster location",
        description="Create a new cluster location. Requires staff permissions.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update cluster location",
        description="Update cluster location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update cluster location",
        description="Partially update cluster location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete cluster location",
        description="Delete a cluster location. Requires staff permissions.",
        tags=["Locations"],
    ),
)
class ClusterLocationViewSet(viewsets.ModelViewSet):
    """ViewSet for ClusterLocation CRUD operations."""
    
    queryset = ClusterLocation.objects.select_related('country').all()
    permission_classes = [IsAdministrativeStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ClusterLocationFilterSet
    search_fields = ['cluster_name', 'cluster_code', 'description']
    ordering_fields = ['cluster_name', 'established_date', 'date_added']
    ordering = ['cluster_name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return ClusterLocationListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ClusterLocationCreateUpdateSerializer
        return ClusterLocationDetailSerializer
    
    @extend_schema(
        summary="List chapters in cluster",
        description="Get all chapters for a specific cluster location.",
        responses={200: ChapterLocationListSerializer(many=True)},
        tags=["Locations"],
    )
    @action(detail=True, methods=['get'])
    def chapters(self, request, pk=None):
        """Get all chapters for a cluster location."""
        cluster = self.get_object()
        chapters = cluster.chapters.all().order_by('chapter_name')
        serializer = ChapterLocationListSerializer(
            chapters, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================================
# CHAPTER LOCATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List chapter locations",
        description="Retrieve a paginated list of chapter locations with filtering.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve chapter location details",
        description="Get detailed information about a specific chapter location including areas.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create chapter location",
        description="Create a new chapter location. Requires staff permissions.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update chapter location",
        description="Update chapter location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update chapter location",
        description="Partially update chapter location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete chapter location",
        description="Delete a chapter location. Requires staff permissions.",
        tags=["Locations"],
    ),
)
class ChapterLocationViewSet(viewsets.ModelViewSet):
    """ViewSet for ChapterLocation CRUD operations."""
    
    queryset = ChapterLocation.objects.select_related('cluster__country').all()
    permission_classes = [IsAdministrativeStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ChapterLocationFilterSet
    search_fields = ['chapter_name', 'chapter_code', 'description']
    ordering_fields = ['chapter_name', 'established_date', 'date_added']
    ordering = ['chapter_name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return ChapterLocationListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ChapterLocationCreateUpdateSerializer
        return ChapterLocationDetailSerializer
    
    @extend_schema(
        summary="List areas in chapter",
        description="Get all areas for a specific chapter location.",
        responses={200: AreaLocationListSerializer(many=True)},
        tags=["Locations"],
    )
    @action(detail=True, methods=['get'])
    def areas(self, request, pk=None):
        """Get all areas for a chapter location."""
        chapter = self.get_object()
        areas = chapter.areas.all().order_by('area_name')
        serializer = AreaLocationListSerializer(
            areas, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================================
# AREA LOCATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List area locations",
        description="Retrieve a paginated list of area locations with filtering and search.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve area location details",
        description="Get detailed information about a specific area location including relative areas.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create area location",
        description="Create a new area location. Requires staff permissions.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update area location",
        description="Update area location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update area location",
        description="Partially update area location details. Requires staff permissions.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete area location",
        description="Delete an area location. Requires staff permissions.",
        tags=["Locations"],
    ),
)
class AreaLocationViewSet(viewsets.ModelViewSet):
    """ViewSet for AreaLocation CRUD operations with relative area search."""
    
    queryset = AreaLocation.objects.select_related('chapter__cluster__country').prefetch_related(
        'relative_search_areas'
    ).all()
    permission_classes = [IsAdministrativeStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AreaLocationFilterSet
    search_fields = ['area_name', 'area_code', 'description', 'relative_search_areas__name']
    ordering_fields = ['area_name', 'established_date', 'date_added']
    ordering = ['area_name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AreaLocationListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return AreaLocationCreateUpdateSerializer
        return AreaLocationDetailSerializer
    
    @extend_schema(
        summary="List relative areas",
        description="Get all relative search areas for a specific area location.",
        responses={200: RelativeAreaSerializer(many=True)},
        tags=["Locations"],
    )
    @action(detail=True, methods=['get'])
    def relative_areas(self, request, pk=None):
        """Get all relative search areas for an area location."""
        area = self.get_object()
        relatives = area.relative_search_areas.all()
        serializer = RelativeAreaSerializer(
            relatives, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================================
# RELATIVE AREA VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List relative areas",
        description="Retrieve a paginated list of relative search areas.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve relative area details",
        description="Get detailed information about a specific relative area.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create relative area",
        description="Create a new relative search area. Requires staff permissions.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update relative area",
        description="Update relative area details. Requires staff permissions.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update relative area",
        description="Partially update relative area details. Requires staff permissions.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete relative area",
        description="Delete a relative area. Requires staff permissions.",
        tags=["Locations"],
    ),
)
class RelativeAreaViewSet(viewsets.ModelViewSet):
    """ViewSet for RelativeArea CRUD operations."""
    
    queryset = RelativeArea.objects.select_related('relative_area').all()
    permission_classes = [IsAdministrativeStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = RelativeAreaFilterSet
    search_fields = ['name', 'relative_area__area_name']
    ordering_fields = ['name']
    ordering = ['name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return RelativeAreaCreateUpdateSerializer
        return RelativeAreaSerializer


# ============================================================================
# POI VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List points of interest",
        description="Retrieve a paginated list of POIs with filtering by type, city, etc.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve POI details",
        description="Get detailed information about a specific point of interest.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create POI",
        description="Create a new point of interest.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update POI",
        description="Update POI details.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update POI",
        description="Partially update POI details.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete POI",
        description="Delete a point of interest.",
        tags=["Locations"],
    ),
)
class POIViewSet(viewsets.ModelViewSet):
    """ViewSet for POI CRUD operations."""
    
    queryset = POI.objects.select_related('created_by', 'updated_by').all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = POIFilterSet
    search_fields = ['name', 'description', 'address', 'city', 'postcode']
    ordering_fields = ['name', 'city', 'created_at']
    ordering = ['name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return POIListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return POICreateUpdateSerializer
        return POIDetailSerializer


# ============================================================================
# VENUE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List venues",
        description="Retrieve a paginated list of venues with filtering.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve venue details",
        description="Get detailed information about a specific venue including rooms and contacts.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create venue",
        description="Create a new venue linked to a POI.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update venue",
        description="Update venue details.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update venue",
        description="Partially update venue details.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete venue",
        description="Delete a venue.",
        tags=["Locations"],
    ),
)
class VenueViewSet(viewsets.ModelViewSet):
    """ViewSet for Venue CRUD operations."""
    
    queryset = Venue.objects.select_related('poi', 'added_by').prefetch_related(
        'rooms', 'contacts', 'metadata'
    ).all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = VenueFilterSet
    search_fields = ['poi__name', 'description', 'poi__city']
    ordering_fields = ['poi__name', 'capacity', 'added_at']
    ordering = ['poi__name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return VenueListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return VenueCreateUpdateSerializer
        return VenueDetailSerializer
    
    @extend_schema(
        summary="List venue rooms",
        description="Get all rooms for a specific venue.",
        responses={200: RoomVenueSerializer(many=True)},
        tags=["Locations"],
    )
    @action(detail=True, methods=['get'])
    def rooms(self, request, pk=None):
        """Get all rooms for a venue."""
        venue = self.get_object()
        rooms = venue.rooms.all()
        serializer = RoomVenueSerializer(
            rooms, many=True, context={'request': request}
        )
        return Response(serializer.data)
    
    @extend_schema(
        summary="List venue contacts",
        description="Get all contacts for a specific venue.",
        responses={200: VenueContactSerializer(many=True)},
        tags=["Locations"],
    )
    @action(detail=True, methods=['get'])
    def contacts(self, request, pk=None):
        """Get all contacts for a venue."""
        venue = self.get_object()
        contacts = venue.contacts.all()
        serializer = VenueContactSerializer(
            contacts, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================================
# ROOM VENUE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List venue rooms",
        description="Retrieve a paginated list of venue rooms with filtering.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve room details",
        description="Get detailed information about a specific venue room.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create venue room",
        description="Create a new room in a venue.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update venue room",
        description="Update room details.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update venue room",
        description="Partially update room details.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete venue room",
        description="Delete a venue room.",
        tags=["Locations"],
    ),
)
class RoomVenueViewSet(viewsets.ModelViewSet):
    """ViewSet for RoomVenue CRUD operations."""
    
    queryset = RoomVenue.objects.select_related('venue__poi', 'added_by').all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = RoomVenueFilterSet
    search_fields = ['room_name', 'description', 'venue__poi__name']
    ordering_fields = ['room_name', 'capacity', 'added_at']
    ordering = ['room_name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return RoomVenueCreateUpdateSerializer
        return RoomVenueSerializer


# ============================================================================
# VENUE CONTACT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List venue contacts",
        description="Retrieve a paginated list of venue contacts with filtering.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve venue contact details",
        description="Get detailed information about a specific venue contact.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create venue contact",
        description="Create a new contact for a venue.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update venue contact",
        description="Update venue contact details.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update venue contact",
        description="Partially update venue contact details.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete venue contact",
        description="Delete a venue contact.",
        tags=["Locations"],
    ),
)
class VenueContactViewSet(viewsets.ModelViewSet):
    """ViewSet for VenueContact CRUD operations."""
    
    queryset = VenueContact.objects.select_related('venue__poi', 'added_by').all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = VenueContactFilterSet
    search_fields = ['contact_name', 'email', 'phone_number', 'venue__poi__name']
    ordering_fields = ['contact_name', 'role', 'added_at']
    ordering = ['contact_name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return VenueContactCreateUpdateSerializer
        return VenueContactSerializer


# ============================================================================
# VENUE METADATA VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List venue metadata",
        description="Retrieve a paginated list of venue metadata entries.",
        tags=["Locations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve venue metadata details",
        description="Get detailed information about a specific venue metadata entry.",
        tags=["Locations"],
    ),
    create=extend_schema(
        summary="Create venue metadata",
        description="Create a new metadata entry for a venue.",
        tags=["Locations"],
    ),
    update=extend_schema(
        summary="Update venue metadata",
        description="Update venue metadata details.",
        tags=["Locations"],
    ),
    partial_update=extend_schema(
        summary="Partially update venue metadata",
        description="Partially update venue metadata details.",
        tags=["Locations"],
    ),
    destroy=extend_schema(
        summary="Delete venue metadata",
        description="Delete a venue metadata entry.",
        tags=["Locations"],
    ),
)
class VenueMetadataViewSet(viewsets.ModelViewSet):
    """ViewSet for VenueMetadata CRUD operations."""
    
    queryset = VenueMetadata.objects.select_related('venue__poi', 'poi', 'added_by').all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = VenueMetadataFilterSet
    search_fields = ['label', 'value', 'venue__poi__name']
    ordering_fields = ['label', 'added_at']
    ordering = ['label']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return VenueMetadataCreateUpdateSerializer
        return VenueMetadataSerializer
