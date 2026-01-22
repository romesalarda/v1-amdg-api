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
    
    @extend_schema(
        summary="Add leader to country",
        description=(
            "Assign a user as a leader of this country location. "
            "Requires organisation controller permissions for the specified organisation. "
            "Leaders must belong to an organisation for grouping purposes."
        ),
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'ID of the user to assign as leader'},
                    'organisation_id': {'type': 'integer', 'description': 'ID of the organisation the leader belongs to'},
                    'notes': {'type': 'string', 'description': 'Optional notes about this leadership assignment'}
                },
                'required': ['user_id', 'organisation_id']
            }
        },
        responses={
            201: OpenApiResponse(description="Leader added successfully"),
            400: OpenApiResponse(description="Invalid data or duplicate assignment"),
            403: OpenApiResponse(description="Not authorized - requires organisation controller permissions"),
            404: OpenApiResponse(description="User or organisation not found")
        },
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='add-leader')
    def add_leader(self, request, pk=None):
        """Add a leader to this country location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, Organisation, OrganisationControl
        
        country = self.get_object()
        user_id = request.data.get('user_id')
        organisation_id = request.data.get('organisation_id')
        notes = request.data.get('notes', '')
        
        if not user_id or not organisation_id:
            return Response(
                {'error': 'Both user_id and organisation_id are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        User = get_user_model()
        
        try:
            user = User.objects.get(id=user_id)
            organisation = Organisation.objects.get(id=organisation_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Organisation.DoesNotExist:
            return Response(
                {'error': 'Organisation not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if request user has OrganisationControl for this organisation
        if not request.user.is_superuser and not request.user.is_staff:
            has_control = OrganisationControl.objects.filter(
                organisation=organisation,
                user=request.user
            ).exists()
            
            if not has_control:
                return Response(
                    {'error': 'You must be a controller of the specified organisation to add leaders.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Check for existing leadership
        country_ct = ContentType.objects.get_for_model(CountryLocation)
        if Leader.objects.filter(
            user=user,
            target_type=country_ct,
            target_id=country.id
        ).exists():
            return Response(
                {'error': 'This user is already a leader of this country.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create the leader
        leader = Leader.objects.create(
            user=user,
            organisation=organisation,
            target_type=country_ct,
            target_id=country.id,
            notes=notes,
            added_by=request.user
        )
        
        return Response(
            {
                'message': 'Leader added successfully.',
                'leader_id': leader.id,
                'user': user.email,
                'country': str(country),
                'organisation': organisation.title
            },
            status=status.HTTP_201_CREATED
        )
    
    @extend_schema(
        summary="Remove leader from country",
        description=(
            "Remove a user's leadership assignment from this country location. "
            "Requires organisation controller permissions for the leader's organisation."
        ),
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'ID of the user to remove as leader'}
                },
                'required': ['user_id']
            }
        },
        responses={
            200: OpenApiResponse(description="Leader removed successfully"),
            400: OpenApiResponse(description="Invalid data"),
            403: OpenApiResponse(description="Not authorized"),
            404: OpenApiResponse(description="User or leadership assignment not found")
        },
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='remove-leader')
    def remove_leader(self, request, pk=None):
        """Remove a leader from this country location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, OrganisationControl
        
        country = self.get_object()
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'user_id is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        User = get_user_model()
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Find the leader
        country_ct = ContentType.objects.get_for_model(CountryLocation)
        try:
            leader = Leader.objects.get(
                user=user,
                target_type=country_ct,
                target_id=country.id
            )
        except Leader.DoesNotExist:
            return Response(
                {'error': 'This user is not a leader of this country.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if request user has OrganisationControl for the leader's organisation
        if not request.user.is_superuser and not request.user.is_staff:
            if not leader.organisation:
                return Response(
                    {'error': 'Cannot determine organisation for permission check.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            has_control = OrganisationControl.objects.filter(
                organisation=leader.organisation,
                user=request.user
            ).exists()
            
            if not has_control:
                return Response(
                    {'error': 'You must be a controller of the leader\'s organisation to remove them.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        leader.delete()
        
        return Response(
            {'message': 'Leader removed successfully.'},
            status=status.HTTP_200_OK
        )


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
    
    @extend_schema(
        summary="Add leader to cluster",
        description="Assign a user as a leader of this cluster location. Requires organisation controller permissions.",
        request={'application/json': {'type': 'object', 'properties': {'user_id': {'type': 'integer'}, 'organisation_id': {'type': 'integer'}, 'notes': {'type': 'string'}}, 'required': ['user_id', 'organisation_id']}},
        responses={201: OpenApiResponse(description="Leader added successfully"), 400: OpenApiResponse(description="Invalid data"), 403: OpenApiResponse(description="Not authorized"), 404: OpenApiResponse(description="User or organisation not found")},
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='add-leader')
    def add_leader(self, request, pk=None):
        """Add a leader to this cluster location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, Organisation, OrganisationControl
        
        cluster = self.get_object()
        user_id = request.data.get('user_id')
        organisation_id = request.data.get('organisation_id')
        notes = request.data.get('notes', '')
        
        if not user_id or not organisation_id:
            return Response({'error': 'Both user_id and organisation_id are required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
            organisation = Organisation.objects.get(id=organisation_id)
        except (User.DoesNotExist, Organisation.DoesNotExist) as e:
            return Response({'error': 'User or organisation not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        if not request.user.is_superuser and not request.user.is_staff:
            if not OrganisationControl.objects.filter(organisation=organisation, user=request.user).exists():
                return Response({'error': 'You must be a controller of the specified organisation to add leaders.'}, status=status.HTTP_403_FORBIDDEN)
        
        cluster_ct = ContentType.objects.get_for_model(ClusterLocation)
        if Leader.objects.filter(user=user, target_type=cluster_ct, target_id=cluster.id).exists():
            return Response({'error': 'This user is already a leader of this cluster.'}, status=status.HTTP_400_BAD_REQUEST)
        
        leader = Leader.objects.create(user=user, organisation=organisation, target_type=cluster_ct, target_id=cluster.id, notes=notes, added_by=request.user)
        return Response({'message': 'Leader added successfully.', 'leader_id': leader.id, 'user': user.email, 'cluster': str(cluster), 'organisation': organisation.title}, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Remove leader from cluster",
        description="Remove a user's leadership assignment from this cluster location. Requires organisation controller permissions.",
        request={'application/json': {'type': 'object', 'properties': {'user_id': {'type': 'integer'}}, 'required': ['user_id']}},
        responses={200: OpenApiResponse(description="Leader removed successfully"), 400: OpenApiResponse(description="Invalid data"), 403: OpenApiResponse(description="Not authorized"), 404: OpenApiResponse(description="User or leadership not found")},
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='remove-leader')
    def remove_leader(self, request, pk=None):
        """Remove a leader from this cluster location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, OrganisationControl
        
        cluster = self.get_object()
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response({'error': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        cluster_ct = ContentType.objects.get_for_model(ClusterLocation)
        try:
            leader = Leader.objects.get(user=user, target_type=cluster_ct, target_id=cluster.id)
        except Leader.DoesNotExist:
            return Response({'error': 'This user is not a leader of this cluster.'}, status=status.HTTP_404_NOT_FOUND)
        
        if not request.user.is_superuser and not request.user.is_staff:
            if not leader.organisation or not OrganisationControl.objects.filter(organisation=leader.organisation, user=request.user).exists():
                return Response({'error': 'You must be a controller of the leader\'s organisation to remove them.'}, status=status.HTTP_403_FORBIDDEN)
        
        leader.delete()
        return Response({'message': 'Leader removed successfully.'}, status=status.HTTP_200_OK)


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
    
    @extend_schema(
        summary="Add leader to chapter",
        description="Assign a user as a leader of this chapter location. Requires organisation controller permissions.",
        request={'application/json': {'type': 'object', 'properties': {'user_id': {'type': 'integer'}, 'organisation_id': {'type': 'integer'}, 'notes': {'type': 'string'}}, 'required': ['user_id', 'organisation_id']}},
        responses={201: OpenApiResponse(description="Leader added successfully"), 400: OpenApiResponse(description="Invalid data"), 403: OpenApiResponse(description="Not authorized"), 404: OpenApiResponse(description="User or organisation not found")},
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='add-leader')
    def add_leader(self, request, pk=None):
        """Add a leader to this chapter location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, Organisation, OrganisationControl
        
        chapter = self.get_object()
        user_id = request.data.get('user_id')
        organisation_id = request.data.get('organisation_id')
        notes = request.data.get('notes', '')
        
        if not user_id or not organisation_id:
            return Response({'error': 'Both user_id and organisation_id are required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
            organisation = Organisation.objects.get(id=organisation_id)
        except (User.DoesNotExist, Organisation.DoesNotExist):
            return Response({'error': 'User or organisation not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        if not request.user.is_superuser and not request.user.is_staff:
            if not OrganisationControl.objects.filter(organisation=organisation, user=request.user).exists():
                return Response({'error': 'You must be a controller of the specified organisation to add leaders.'}, status=status.HTTP_403_FORBIDDEN)
        
        chapter_ct = ContentType.objects.get_for_model(ChapterLocation)
        if Leader.objects.filter(user=user, target_type=chapter_ct, target_id=chapter.id).exists():
            return Response({'error': 'This user is already a leader of this chapter.'}, status=status.HTTP_400_BAD_REQUEST)
        
        leader = Leader.objects.create(user=user, organisation=organisation, target_type=chapter_ct, target_id=chapter.id, notes=notes, added_by=request.user)
        return Response({'message': 'Leader added successfully.', 'leader_id': leader.id, 'user': user.email, 'chapter': str(chapter), 'organisation': organisation.title}, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Remove leader from chapter",
        description="Remove a user's leadership assignment from this chapter location. Requires organisation controller permissions.",
        request={'application/json': {'type': 'object', 'properties': {'user_id': {'type': 'integer'}}, 'required': ['user_id']}},
        responses={200: OpenApiResponse(description="Leader removed successfully"), 400: OpenApiResponse(description="Invalid data"), 403: OpenApiResponse(description="Not authorized"), 404: OpenApiResponse(description="User or leadership not found")},
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='remove-leader')
    def remove_leader(self, request, pk=None):
        """Remove a leader from this chapter location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, OrganisationControl
        
        chapter = self.get_object()
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response({'error': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        chapter_ct = ContentType.objects.get_for_model(ChapterLocation)
        try:
            leader = Leader.objects.get(user=user, target_type=chapter_ct, target_id=chapter.id)
        except Leader.DoesNotExist:
            return Response({'error': 'This user is not a leader of this chapter.'}, status=status.HTTP_404_NOT_FOUND)
        
        if not request.user.is_superuser and not request.user.is_staff:
            if not leader.organisation or not OrganisationControl.objects.filter(organisation=leader.organisation, user=request.user).exists():
                return Response({'error': 'You must be a controller of the leader\'s organisation to remove them.'}, status=status.HTTP_403_FORBIDDEN)
        
        leader.delete()
        return Response({'message': 'Leader removed successfully.'}, status=status.HTTP_200_OK)


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
    
    @extend_schema(
        summary="Add leader to area",
        description="Assign a user as a leader of this area location. Requires organisation controller permissions.",
        request={'application/json': {'type': 'object', 'properties': {'user_id': {'type': 'integer'}, 'organisation_id': {'type': 'integer'}, 'notes': {'type': 'string'}}, 'required': ['user_id', 'organisation_id']}},
        responses={201: OpenApiResponse(description="Leader added successfully"), 400: OpenApiResponse(description="Invalid data"), 403: OpenApiResponse(description="Not authorized"), 404: OpenApiResponse(description="User or organisation not found")},
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='add-leader')
    def add_leader(self, request, pk=None):
        """Add a leader to this area location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, Organisation, OrganisationControl
        
        area = self.get_object()
        user_id = request.data.get('user_id')
        organisation_id = request.data.get('organisation_id')
        notes = request.data.get('notes', '')
        
        if not user_id or not organisation_id:
            return Response({'error': 'Both user_id and organisation_id are required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
            organisation = Organisation.objects.get(id=organisation_id)
        except (User.DoesNotExist, Organisation.DoesNotExist):
            return Response({'error': 'User or organisation not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        if not request.user.is_superuser and not request.user.is_staff:
            if not OrganisationControl.objects.filter(organisation=organisation, user=request.user).exists():
                return Response({'error': 'You must be a controller of the specified organisation to add leaders.'}, status=status.HTTP_403_FORBIDDEN)
        
        area_ct = ContentType.objects.get_for_model(AreaLocation)
        if Leader.objects.filter(user=user, target_type=area_ct, target_id=area.area_id).exists():
            return Response({'error': 'This user is already a leader of this area.'}, status=status.HTTP_400_BAD_REQUEST)
        
        leader = Leader.objects.create(user=user, organisation=organisation, target_type=area_ct, target_id=area.id, notes=notes, added_by=request.user)
        return Response({'message': 'Leader added successfully.', 'leader_id': leader.id, 'user': user.email, 'area': str(area), 'organisation': organisation.title}, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Remove leader from area",
        description="Remove a user's leadership assignment from this area location. Requires organisation controller permissions.",
        request={'application/json': {'type': 'object', 'properties': {'user_id': {'type': 'integer'}}, 'required': ['user_id']}},
        responses={200: OpenApiResponse(description="Leader removed successfully"), 400: OpenApiResponse(description="Invalid data"), 403: OpenApiResponse(description="Not authorized"), 404: OpenApiResponse(description="User or leadership not found")},
        tags=["Locations"],
    )
    @action(detail=True, methods=['post'], url_path='remove-leader')
    def remove_leader(self, request, pk=None):
        """Remove a leader from this area location."""
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader, OrganisationControl
        
        area = self.get_object()
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response({'error': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        area_ct = ContentType.objects.get_for_model(AreaLocation)
        try:
            leader = Leader.objects.get(user=user, target_type=area_ct, target_id=area.id)
        except Leader.DoesNotExist:
            return Response({'error': 'This user is not a leader of this area.'}, status=status.HTTP_404_NOT_FOUND)
        
        if not request.user.is_superuser and not request.user.is_staff:
            if not leader.organisation or not OrganisationControl.objects.filter(organisation=leader.organisation, user=request.user).exists():
                return Response({'error': 'You must be a controller of the leader\'s organisation to remove them.'}, status=status.HTTP_403_FORBIDDEN)
        
        leader.delete()
        return Response({'message': 'Leader removed successfully.'}, status=status.HTTP_200_OK)


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
