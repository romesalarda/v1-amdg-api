"""
Production-grade serializers for the locations app.

Provides comprehensive serializers for location management with HATEOAS support,
extensive validation, and separation of concerns (list/detail/create/update).

Serializers:
    CountryLocation: CountryLocationListSerializer, CountryLocationDetailSerializer, CountryLocationCreateUpdateSerializer
    ClusterLocation: ClusterLocationListSerializer, ClusterLocationDetailSerializer, ClusterLocationCreateUpdateSerializer
    ChapterLocation: ChapterLocationListSerializer, ChapterLocationDetailSerializer, ChapterLocationCreateUpdateSerializer
    AreaLocation: AreaLocationListSerializer, AreaLocationDetailSerializer, AreaLocationCreateUpdateSerializer
    RelativeArea: RelativeAreaSerializer, RelativeAreaCreateUpdateSerializer
    POI: POIListSerializer, POIDetailSerializer, POICreateUpdateSerializer
    Venue: VenueListSerializer, VenueDetailSerializer, VenueCreateUpdateSerializer
    RoomVenue: RoomVenueSerializer, RoomVenueCreateUpdateSerializer
    VenueContact: VenueContactSerializer, VenueContactCreateUpdateSerializer
    VenueMetadata: VenueMetadataSerializer, VenueMetadataCreateUpdateSerializer

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from typing import Dict, Any, Optional

from apps.locations.models import (
    CountryLocation, ClusterLocation, ChapterLocation, AreaLocation, RelativeArea,
    POI, Venue, RoomVenue, VenueContact, VenueMetadata,
    FloorPlan, FloorPlanAnnotation, FloorPlanAnnotationMetadata,
    GeneralSectorType, SpecificSectorType, POITypeChoice, VenueContactRoleChoice
)
from apps.organisations.models import Leader

User = get_user_model()


# ============================================================================
# COUNTRY LOCATION SERIALIZERS
# ============================================================================

class CountryLocationListSerializer(serializers.ModelSerializer):
    """List serializer for CountryLocation with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    country_name = serializers.CharField(source='country.name', read_only=True)
    general_sector_display = serializers.CharField(source='get_general_sector_display', read_only=True)
    specific_sector_display = serializers.CharField(source='get_specific_sector_display', read_only=True)
    
    class Meta:
        model = CountryLocation
        fields = (
            'id', 'country', 'general_sector', 'specific_sector', 'country_name', 'general_sector_display', 'specific_sector_display',
            'latitude', 'longitude', 'active', 'date_added', '_links'
        )
        read_only_fields = ('id', 'date_added')
        extra_kwargs = {
            'date_added': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'clusters': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/countries/{obj.id}/"),
            'clusters': request.build_absolute_uri(f"/api/locations/countries/{obj.id}/clusters/"),
        }


class CountryLocationDetailSerializer(CountryLocationListSerializer):
    """Detailed serializer for CountryLocation with clusters."""
    
    clusters = serializers.SerializerMethodField(help_text="Clusters in this country")
    
    class Meta(CountryLocationListSerializer.Meta):
        fields = CountryLocationListSerializer.Meta.fields + ('clusters',)
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_clusters(self, obj) -> list:
        """Return summary of clusters."""
        clusters = obj.clusters.filter(active=True)[:10]
        return [{
            'id': cluster.id,
            'cluster_name': cluster.cluster_name,
            'cluster_code': cluster.cluster_code,
            'active': cluster.active,
        } for cluster in clusters]


class CountryLocationCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for CountryLocation with validation."""
    
    class Meta:
        model = CountryLocation
        fields = ('country', 'general_sector', 'specific_sector', 'active')
    
    def validate(self, attrs):
        """Validate sector alignment."""
        general_sector = attrs.get('general_sector')
        specific_sector = attrs.get('specific_sector')
        
        # You could add validation logic here to ensure specific_sector matches general_sector
        # For now, we trust the admin/API users to set this correctly
        
        return attrs


# ============================================================================
# CLUSTER LOCATION SERIALIZERS
# ============================================================================

class ClusterLocationListSerializer(serializers.ModelSerializer):
    """List serializer for ClusterLocation with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    country_name = serializers.CharField(source='country.country.name', read_only=True)
    leader = serializers.SerializerMethodField(help_text="Leader information for this cluster")
    
    class Meta:
        model = ClusterLocation
        fields = (
            'id', 'cluster_name', 'cluster_code', 'country', 'description',
            'latitude', 'longitude', 'active', 'established_date', 'date_added', 'date_updated',
            '_links'
        )
        read_only_fields = ('id', 'date_added', 'date_updated')
        extra_kwargs = {
            'date_added': {'default': None},
            'date_updated': {'default': None},
            'established_date': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'country': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/locations/clusters/{obj.id}/"),
            'country': request.build_absolute_uri(f"/api/locations/countries/{obj.country.id}/"),
        }
        
        return links


class ClusterLocationDetailSerializer(ClusterLocationListSerializer):
    """Detailed serializer for ClusterLocation with chapters."""
    
    chapters = serializers.SerializerMethodField(help_text="Chapters in this cluster")
    leaders = serializers.SerializerMethodField(help_text="Leaders for this cluster")
    
    class Meta(ClusterLocationListSerializer.Meta):
        fields = ClusterLocationListSerializer.Meta.fields + ('chapters_count', 'leaders')
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_chapters_count(self, obj) -> int:
        return obj.chapters.filter(active=True).count()
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_leaders(self, obj) -> list:
        """Return basic leader info with HATEOAS links."""
        from apps.organisations.models import Leader, LeaderLocationType

        leaders = Leader.filter_by_location(
            Leader.objects.all(),
            LeaderLocationType.CLUSTER,
            obj.id,
        ).select_related('user')[:5]
        
        request = self.context.get('request')
        result = []
        for leader in leaders:
            leader_data = {
                'id': leader.id,
                'user_name': leader.user.username,
                'user_email': leader.user.email,
            }
            if request:
                leader_data['_links'] = {
                    'detail': request.build_absolute_uri(f"/api/organisations/leaders/{leader.id}/"),
                    'user': request.build_absolute_uri(f"/api/users/{leader.user.id}/"),
                }
            result.append(leader_data)
        
        return result


class CountryLocationDetailSerializer(CountryLocationListSerializer):
    """Detailed serializer for CountryLocation."""
    
    clusters = serializers.SerializerMethodField(help_text="Clusters in this country")
    leaders = serializers.SerializerMethodField(help_text="Leaders for this country location")
    
    class Meta(CountryLocationListSerializer.Meta):
        fields = CountryLocationListSerializer.Meta.fields + ('clusters', 'leaders')
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_clusters(self, obj) -> list:
        """Return summary of clusters."""
        clusters = obj.clusters.filter(active=True)[:10]
        return [{
            'id': cluster.id,
            'cluster_name': cluster.cluster_name,
            'cluster_code': cluster.cluster_code,
            'active': cluster.active,
        } for cluster in clusters]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_leaders(self, obj) -> list:
        """Return leaders for this country location."""
        from apps.organisations.models import Leader, LeaderLocationType

        leaders = Leader.filter_by_location(
            Leader.objects.all(),
            LeaderLocationType.COUNTRY,
            obj.id,
        ).select_related('user')[:5]
        
        request = self.context.get('request')
        result = []
        for leader in leaders:
            leader_data = {
                'id': leader.id,
                'user_name': leader.user.username,
                'user_email': leader.user.email,
            }
            if request:
                leader_data['_links'] = {
                    'detail': request.build_absolute_uri(f"/api/organisations/leaders/{leader.id}/"),
                    'user': request.build_absolute_uri(f"/api/users/{leader.user.id}/"),
                }
            result.append(leader_data)
        
        return result


class CountryLocationCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for CountryLocation."""
    
    class Meta:
        model = CountryLocation
        fields = ('country', 'general_sector', 'specific_sector', 'active')
    
    def validate(self, attrs):
        """Validate country uniqueness for updates."""
        country = attrs.get('country')
        instance = self.instance
        
        if country:
            existing = CountryLocation.objects.filter(country=country)
            if instance:
                existing = existing.exclude(id=instance.id)
            if existing.exists():
                raise serializers.ValidationError({
                    'country': 'This country already exists in the system.'
                })
        
        return attrs


# ============================================================================
# CLUSTER LOCATION SERIALIZERS
# ============================================================================

class ClusterLocationListSerializer(serializers.ModelSerializer):
    """List serializer for ClusterLocation with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    country_name = serializers.CharField(source='country.country.name', read_only=True)
    date_added = serializers.DateField(read_only=True)
    date_updated = serializers.DateField(read_only=True)
    
    class Meta:
        model = ClusterLocation
        fields = (
            'id', 'cluster_name', 'cluster_code', 'country', 'country_name',
            'description', 'active', 'established_date',
            'date_added', 'date_updated', '_links'
        )
        read_only_fields = ('id', 'date_added', 'date_updated')
        extra_kwargs = {
            'date_added': {'default': None},
            'date_updated': {'default': None},
            'established_date': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'country': {'type': 'string', 'format': 'uri'},
            'chapters': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/clusters/{obj.id}/"),
            'country': request.build_absolute_uri(f"/api/locations/countries/{obj.country.id}/"),
            'chapters': request.build_absolute_uri(f"/api/locations/clusters/{obj.id}/chapters/"),
        }


class ClusterLocationDetailSerializer(ClusterLocationListSerializer):
    """Detailed serializer for ClusterLocation."""
    
    chapters = serializers.SerializerMethodField(help_text="Chapters in this cluster")
    leaders = serializers.SerializerMethodField(help_text="Leaders for this cluster location")
    
    class Meta(ClusterLocationListSerializer.Meta):
        fields = ClusterLocationListSerializer.Meta.fields + ('chapters', 'leaders')
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_chapters(self, obj) -> list:
        """Return summary of chapters."""
        chapters = obj.chapters.filter(active=True)[:10]
        return [{
            'id': chapter.id,
            'chapter_name': chapter.chapter_name,
            'chapter_code': chapter.chapter_code,
            'active': chapter.active,
        } for chapter in chapters]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_leaders(self, obj) -> list:
        """Return leaders for this cluster location."""
        from apps.organisations.models import Leader, LeaderLocationType

        leaders = Leader.filter_by_location(
            Leader.objects.all(),
            LeaderLocationType.CLUSTER,
            obj.id,
        ).select_related('user')[:5]
        
        request = self.context.get('request')
        result = []
        for leader in leaders:
            leader_data = {
                'id': leader.id,
                'user_name': leader.user.username,
                'user_email': leader.user.email,
            }
            if request:
                leader_data['_links'] = {
                    'detail': request.build_absolute_uri(f"/api/organisations/leaders/{leader.id}/"),
                    'user': request.build_absolute_uri(f"/api/users/{leader.user.id}/"),
                }
            result.append(leader_data)
        
        return result


class ClusterLocationCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for ClusterLocation."""
    
    class Meta:
        model = ClusterLocation
        fields = ('cluster_name', 'cluster_code', 'country', 'description', 'active', 'established_date')
    
    def validate_cluster_name(self, value):
        """Validate cluster name."""
        if not value or not value.strip():
            raise serializers.ValidationError("Cluster name cannot be empty.")
        return value.strip().title()


# ============================================================================
# CHAPTER LOCATION SERIALIZERS
# ============================================================================

class ChapterLocationListSerializer(serializers.ModelSerializer):
    """List serializer for ChapterLocation with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    cluster_name = serializers.CharField(source='cluster.cluster_name', read_only=True)
    date_added = serializers.DateField(read_only=True)
    date_updated = serializers.DateField(read_only=True)
    
    class Meta:
        model = ChapterLocation
        fields = (
            'id', 'chapter_name', 'chapter_code', 'cluster', 'cluster_name',
            'description', 'latitude', 'longitude', 'active', 'established_date',
            'date_added', 'date_updated', '_links'
        )
        read_only_fields = ('id', 'date_added', 'date_updated')
        extra_kwargs = {
            'date_added': {'default': None},
            'date_updated': {'default': None},
            'established_date': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'cluster': {'type': 'string', 'format': 'uri'},
            'areas': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/chapters/{obj.id}/"),
            'cluster': request.build_absolute_uri(f"/api/locations/clusters/{obj.cluster.id}/"),
            'areas': request.build_absolute_uri(f"/api/locations/chapters/{obj.id}/areas/"),
        }


class ChapterLocationDetailSerializer(ChapterLocationListSerializer):
    """Detailed serializer for ChapterLocation."""
    
    areas = serializers.SerializerMethodField(help_text="Areas in this chapter")
    leaders = serializers.SerializerMethodField(help_text="Leaders for this chapter location")
    
    class Meta(ChapterLocationListSerializer.Meta):
        fields = ChapterLocationListSerializer.Meta.fields + ('areas', 'leaders')
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_areas(self, obj) -> list:
        """Return summary of areas."""
        areas = obj.areas.filter(active=True)[:10]
        return [{
            'id': area.id,
            'area_name': area.area_name,
            'area_code': area.area_code,
            'active': area.active,
        } for area in areas]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_leaders(self, obj) -> list:
        """Return leaders for this chapter location."""
        from apps.organisations.models import Leader, LeaderLocationType

        leaders = Leader.filter_by_location(
            Leader.objects.all(),
            LeaderLocationType.CHAPTER,
            obj.id,
        ).select_related('user')[:5]
        
        request = self.context.get('request')
        result = []
        for leader in leaders:
            leader_data = {
                'id': leader.id,
                'user_name': leader.user.username,
                'user_email': leader.user.email,
            }
            if request:
                leader_data['_links'] = {
                    'detail': request.build_absolute_uri(f"/api/organisations/leaders/{leader.id}/"),
                    'user': request.build_absolute_uri(f"/api/users/{leader.user.id}/"),
                }
            result.append(leader_data)
        
        return result


class ChapterLocationCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for ChapterLocation."""
    
    class Meta:
        model = ChapterLocation
        fields = ('chapter_name', 'chapter_code', 'cluster', 'description', 'active', 'established_date')
    
    def validate_chapter_name(self, value):
        """Validate chapter name."""
        if not value or not value.strip():
            raise serializers.ValidationError("Chapter name cannot be empty.")
        return value.strip().title()
    
    def validate(self, attrs):
        """Validate unique chapter per cluster."""
        chapter_name = attrs.get('chapter_name')
        cluster = attrs.get('cluster')
        instance = self.instance
        
        if chapter_name and cluster:
            existing = ChapterLocation.objects.filter(chapter_name=chapter_name, cluster=cluster)
            if instance:
                existing = existing.exclude(id=instance.id)
            if existing.exists():
                raise serializers.ValidationError({
                    'chapter_name': 'This chapter already exists in this cluster.'
                })
        
        return attrs


# ============================================================================
# AREA LOCATION SERIALIZERS
# ============================================================================

class AreaLocationListSerializer(serializers.ModelSerializer):
    """List serializer for AreaLocation with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    chapter_name = serializers.CharField(source='chapter.chapter_name', read_only=True)
    area_id_str = serializers.CharField(source='area_id', read_only=True)
    date_added = serializers.DateField(read_only=True)
    date_updated = serializers.DateField(read_only=True)
    
    class Meta:
        model = AreaLocation
        fields = (
            'id', 'area_id_str', 'area_name', 'area_code', 'chapter', 'chapter_name',
            'description', 'latitude', 'longitude', 'active', 'established_date',
            'date_added', 'date_updated', '_links'
        )
        read_only_fields = ('id', 'area_id_str', 'date_added', 'date_updated')
        extra_kwargs = {
            'date_added': {'default': None},
            'date_updated': {'default': None},
            'established_date': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'chapter': {'type': 'string', 'format': 'uri'},
            'relative_areas': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/areas/{obj.id}/"),
            'chapter': request.build_absolute_uri(f"/api/locations/chapters/{obj.chapter.id}/"),
            'relative_areas': request.build_absolute_uri(f"/api/locations/areas/{obj.id}/relative-areas/"),
        }


class AreaLocationDetailSerializer(AreaLocationListSerializer):
    """Detailed serializer for AreaLocation."""
    
    relative_areas = serializers.SerializerMethodField(help_text="Relative search areas")
    leaders = serializers.SerializerMethodField(help_text="Leaders for this area location")
    
    class Meta(AreaLocationListSerializer.Meta):
        fields = AreaLocationListSerializer.Meta.fields + ('relative_areas', 'leaders')
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_relative_areas(self, obj) -> list:
        """Return relative search areas."""
        relatives = obj.relative_search_areas.all()[:20]
        return [{
            'id': rel.id,
            'name': rel.name,
        } for rel in relatives]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_leaders(self, obj) -> list:
        """Return leaders for this area location."""
        from apps.organisations.models import Leader, LeaderLocationType

        leaders = Leader.filter_by_location(
            Leader.objects.all(),
            LeaderLocationType.AREA,
            obj.id,
        ).select_related('user')[:5]
        
        request = self.context.get('request')
        result = []
        for leader in leaders:
            leader_data = {
                'id': leader.id,
                'user_name': leader.user.username,
                'user_email': leader.user.email,
            }
            if request:
                leader_data['_links'] = {
                    'detail': request.build_absolute_uri(f"/api/organisations/leaders/{leader.id}/"),
                    'user': request.build_absolute_uri(f"/api/users/{leader.user.id}/"),
                }
            result.append(leader_data)
        
        return result


class AreaLocationCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for AreaLocation."""
    
    class Meta:
        model = AreaLocation
        fields = ('area_name', 'area_code', 'chapter', 'description', 'active', 'established_date')
    
    def validate_area_name(self, value):
        """Validate area name."""
        if not value or not value.strip():
            raise serializers.ValidationError("Area name cannot be empty.")
        return value.strip().title()
    
    def validate(self, attrs):
        """Validate unique area per chapter and area code per chapter."""
        area_name = attrs.get('area_name')
        area_code = attrs.get('area_code')
        chapter = attrs.get('chapter')
        instance = self.instance
        
        if area_name and chapter:
            existing = AreaLocation.objects.filter(area_name=area_name, chapter=chapter)
            if instance:
                existing = existing.exclude(id=instance.id)
            if existing.exists():
                raise serializers.ValidationError({
                    'area_name': 'This area already exists in this chapter.'
                })
        
        if area_code and chapter:
            existing = AreaLocation.objects.filter(area_code=area_code, chapter=chapter)
            if instance:
                existing = existing.exclude(id=instance.id)
            if existing.exists():
                raise serializers.ValidationError({
                    'area_code': 'This area code already exists in this chapter.'
                })
        
        return attrs


# ============================================================================
# RELATIVE AREA SERIALIZERS
# ============================================================================

class RelativeAreaSerializer(serializers.ModelSerializer):
    """Serializer for RelativeArea model."""
    
    _links = serializers.SerializerMethodField()
    relative_area_name = serializers.CharField(source='relative_area.area_name', read_only=True)
    
    class Meta:
        model = RelativeArea
        fields = ('id', 'name', 'relative_area', 'relative_area_name', '_links')
        read_only_fields = ('id',)
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'relative_area': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/locations/relative-areas/{obj.id}/"),
        }
        
        if obj.relative_area:
            links['relative_area'] = request.build_absolute_uri(
                f"/api/locations/areas/{obj.relative_area.id}/"
            )
        
        return links


class RelativeAreaCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for RelativeArea."""
    
    class Meta:
        model = RelativeArea
        fields = ('name', 'relative_area')
    
    def validate_name(self, value):
        """Validate relative area name."""
        if not value or not value.strip():
            raise serializers.ValidationError("Relative area name cannot be empty.")
        return value.strip().title()


# ============================================================================
# POI SERIALIZERS
# ============================================================================

class POIListSerializer(serializers.ModelSerializer):
    """List serializer for POI with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    poi_type_display = serializers.CharField(source='get_poi_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = POI
        fields = (
            'id', 'name', 'poi_type', 'poi_type_display', 'address', 'city', 'postcode',
            'created_by', 'created_by_name', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'created_by': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/locations/pois/{obj.id}/"),
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(f"/api/users/{obj.created_by.id}/")
        
        # Add venue link if POI has a venue
        if hasattr(obj, 'venue'):
            links['venue'] = request.build_absolute_uri(f"/api/locations/venues/{obj.venue.id}/")
        
        return links


class POIDetailSerializer(POIListSerializer):
    """Detailed serializer for POI with full information."""
    
    class Meta(POIListSerializer.Meta):
        fields = POIListSerializer.Meta.fields + (
            'description', 'latitude', 'longitude', 'updated_by'
        )


class POICreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for POI with validation."""
    
    class Meta:
        model = POI
        fields = (
            'name', 'description', 'address', 'postcode', 'city', 'poi_type',
            'latitude', 'longitude'
        )
    
    def validate_name(self, value):
        """Validate POI name."""
        if not value or not value.strip():
            raise serializers.ValidationError("POI name cannot be empty.")
        return value.strip()
    
    def validate_address(self, value):
        """Validate address."""
        if not value or not value.strip():
            raise serializers.ValidationError("Address cannot be empty.")
        return value.strip()
    
    def validate(self, attrs):
        """Validate coordinates."""
        latitude = attrs.get('latitude')
        longitude = attrs.get('longitude')
        
        if latitude is not None and (latitude < -90 or latitude > 90):
            raise serializers.ValidationError({
                'latitude': 'Latitude must be between -90 and 90.'
            })
        
        if longitude is not None and (longitude < -180 or longitude > 180):
            raise serializers.ValidationError({
                'longitude': 'Longitude must be between -180 and 180.'
            })
        
        return attrs
    
    def create(self, validated_data):
        """Create POI with current user as created_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Update POI with current user as updated_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['updated_by'] = request.user
        return super().update(instance, validated_data)


# ============================================================================
# VENUE SERIALIZERS
# ============================================================================

class VenueListSerializer(serializers.ModelSerializer):
    """List serializer for Venue with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    poi_name = serializers.CharField(source='poi.name', read_only=True)
    poi_city = serializers.CharField(source='poi.city', read_only=True)
    poi_type = serializers.CharField(source='poi.poi_type', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    added_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = Venue
        fields = (
            'id', 'poi', 'poi_name', 'poi_city', 'poi_type', 'capacity',
            'added_by', 'added_by_name', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'poi': {'type': 'string', 'format': 'uri'},
            'rooms': {'type': 'string', 'format': 'uri'},
            'contacts': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/venues/{obj.id}/"),
            'poi': request.build_absolute_uri(f"/api/locations/pois/{obj.poi.id}/"),
            'rooms': request.build_absolute_uri(f"/api/locations/venues/{obj.id}/rooms/"),
            'contacts': request.build_absolute_uri(f"/api/locations/venues/{obj.id}/contacts/"),
        }


class VenueDetailSerializer(VenueListSerializer):
    """Detailed serializer for Venue with nested data."""
    
    poi_details = POIDetailSerializer(source='poi', read_only=True)
    rooms = serializers.SerializerMethodField(help_text="Rooms in this venue")
    contacts = serializers.SerializerMethodField(help_text="Venue contacts")
    metadata_list = serializers.SerializerMethodField(help_text="Venue metadata")
    
    class Meta(VenueListSerializer.Meta):
        fields = VenueListSerializer.Meta.fields + (
            'description', 'instructions', 'notes',
            'poi_details', 'rooms', 'contacts', 'metadata_list'
        )
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_rooms(self, obj) -> list:
        """Return venue rooms."""
        rooms = obj.rooms.all()[:20]
        return [{
            'id': room.id,
            'room_name': room.room_name,
            'capacity': room.capacity,
            'description': room.description,
        } for room in rooms]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_contacts(self, obj) -> list:
        """Return venue contacts."""
        contacts = obj.contacts.all()[:10]
        return [{
            'id': contact.id,
            'contact_name': contact.contact_name,
            'email': contact.email,
            'phone_number': contact.phone_number,
            'role': contact.role,
        } for contact in contacts]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_metadata_list(self, obj) -> list:
        """Return venue metadata."""
        metadata = obj.metadata.all()[:20]
        return [{
            'id': meta.id,
            'label': meta.label,
            'value': meta.value,
        } for meta in metadata]


class VenueCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for Venue with validation."""
    
    class Meta:
        model = Venue
        fields = ('poi', 'description', 'instructions', 'notes', 'capacity')
    
    def validate_poi(self, value):
        """Ensure POI doesn't already have a venue."""
        instance = self.instance
        
        if value:
            existing_venue = Venue.objects.filter(poi=value)
            if instance:
                existing_venue = existing_venue.exclude(id=instance.id)
            if existing_venue.exists():
                raise serializers.ValidationError(
                    "This POI already has a venue associated with it."
                )
        
        return value
    
    def validate_capacity(self, value):
        """Validate capacity is positive."""
        if value is not None and value <= 0:
            raise serializers.ValidationError("Capacity must be greater than zero.")
        return value
    
    def create(self, validated_data):
        """Create venue with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# ROOM VENUE SERIALIZERS
# ============================================================================

class RoomVenueSerializer(serializers.ModelSerializer):
    """Serializer for RoomVenue."""
    
    _links = serializers.SerializerMethodField()
    venue_name = serializers.CharField(source='venue.poi.name', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    added_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = RoomVenue
        fields = (
            'id', 'venue', 'venue_name', 'room_name', 'description', 'capacity',
            'added_by', 'added_by_name', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'venue': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/rooms/{obj.id}/"),
            'venue': request.build_absolute_uri(f"/api/locations/venues/{obj.venue.id}/"),
        }


class RoomVenueCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for RoomVenue."""
    
    class Meta:
        model = RoomVenue
        fields = ('venue', 'room_name', 'description', 'capacity')
    
    def validate_room_name(self, value):
        """Validate room name."""
        if not value or not value.strip():
            raise serializers.ValidationError("Room name cannot be empty.")
        return value.strip()
    
    def validate_capacity(self, value):
        """Validate capacity is positive."""
        if value is not None and value <= 0:
            raise serializers.ValidationError("Capacity must be greater than zero.")
        return value
    
    def create(self, validated_data):
        """Create room with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# VENUE CONTACT SERIALIZERS
# ============================================================================

class VenueContactSerializer(serializers.ModelSerializer):
    """Serializer for VenueContact."""
    
    _links = serializers.SerializerMethodField()
    venue_name = serializers.CharField(source='venue.poi.name', read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    added_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = VenueContact
        fields = (
            'id', 'venue', 'venue_name', 'contact_name', 'phone_number', 'email',
            'role', 'role_display', 'added_by', 'added_by_name',
            'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'venue': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/venue-contacts/{obj.id}/"),
            'venue': request.build_absolute_uri(f"/api/locations/venues/{obj.venue.id}/"),
        }


class VenueContactCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for VenueContact."""
    
    class Meta:
        model = VenueContact
        fields = ('venue', 'contact_name', 'phone_number', 'email', 'role')
    
    def validate_contact_name(self, value):
        """Validate contact name."""
        if not value or not value.strip():
            raise serializers.ValidationError("Contact name cannot be empty.")
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Contact name must be at least 2 characters long.")
        return value.strip()
    
    def validate(self, attrs):
        """Ensure either phone or email is provided."""
        phone_number = attrs.get('phone_number')
        email = attrs.get('email')
        
        if not phone_number and not email:
            raise serializers.ValidationError(
                "At least one contact method (phone number or email) must be provided."
            )
        
        return attrs
    
    def create(self, validated_data):
        """Create contact with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# VENUE METADATA SERIALIZERS
# ============================================================================

class VenueMetadataSerializer(serializers.ModelSerializer):
    """Serializer for VenueMetadata."""
    
    _links = serializers.SerializerMethodField()
    venue_name = serializers.CharField(source='venue.poi.name', read_only=True)
    poi_name = serializers.CharField(source='poi.name', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    added_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = VenueMetadata
        fields = (
            'id', 'venue', 'venue_name', 'poi', 'poi_name', 'label', 'value',
            'added_by', 'added_by_name', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'venue': {'type': 'string', 'format': 'uri'},
            'poi': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/locations/venue-metadata/{obj.id}/"),
            'venue': request.build_absolute_uri(f"/api/locations/venues/{obj.venue.id}/"),
            'poi': request.build_absolute_uri(f"/api/locations/pois/{obj.poi.id}/"),
        }


class VenueMetadataCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for VenueMetadata."""
    
    class Meta:
        model = VenueMetadata
        fields = ('venue', 'poi', 'label', 'value')
    
    def validate_label(self, value):
        """Validate label."""
        if not value or not value.strip():
            raise serializers.ValidationError("Label cannot be empty.")
        return value.strip()
    
    def validate(self, attrs):
        """Ensure POI matches venue's POI."""
        venue = attrs.get('venue')
        poi = attrs.get('poi')
        
        if venue and poi:
            if venue.poi != poi:
                raise serializers.ValidationError({
                    'poi': 'POI must match the venue\'s associated POI.'
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create metadata with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# FLOOR PLAN SERIALIZERS
# ============================================================================

class FloorPlanAnnotationMetadataSerializer(serializers.ModelSerializer):
    """Full CRUD serializer for FloorPlanAnnotationMetadata."""

    added_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = FloorPlanAnnotationMetadata
        fields = ('id', 'label', 'value', 'added_by', 'added_at')
        read_only_fields = ('id', 'added_by', 'added_at')


class FloorPlanAnnotationSerializer(serializers.ModelSerializer):
    """
    Serializer for FloorPlanAnnotation.

    On read, includes nested metadata and the linked room name.
    On write, accepts a list of metadata objects that are created/replaced atomically.
    Vertices are validated as a list of normalised {x, y} coordinate objects.
    """

    metadata = FloorPlanAnnotationMetadataSerializer(many=True, read_only=True)
    metadata_write = FloorPlanAnnotationMetadataSerializer(many=True, write_only=True, required=False, source='metadata')
    room_venue_name = serializers.SerializerMethodField(read_only=True)
    added_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = FloorPlanAnnotation
        fields = (
            'id', 'floor_plan', 'room_venue', 'room_venue_name',
            'label', 'colour', 'vertices',
            'metadata', 'metadata_write',
            'added_by', 'added_at', 'updated_at',
        )
        read_only_fields = ('id', 'floor_plan', 'room_venue_name', 'added_by', 'added_at', 'updated_at')

    @extend_schema_field({'type': 'string', 'nullable': True})
    def get_room_venue_name(self, obj) -> Optional[str]:
        """Return the room name if a RoomVenue is linked."""
        if obj.room_venue:
            return obj.room_venue.room_name
        return None

    def validate_vertices(self, value):
        """
        Validate that vertices is a list of {x, y} dicts with normalised float values.

        Rules:
        - Must be a list of dicts
        - Each dict must have 'x' and 'y' keys
        - Both values must be floats (or ints) in [0.0, 1.0]
        - Minimum 3 vertices required to form a closed polygon
        """
        if not isinstance(value, list):
            raise serializers.ValidationError("Vertices must be a list.")
        if len(value) < 3:
            raise serializers.ValidationError("A polygon requires at least 3 vertices.")
        for i, vertex in enumerate(value):
            if not isinstance(vertex, dict):
                raise serializers.ValidationError(f"Vertex {i} must be a dict.")
            if 'x' not in vertex or 'y' not in vertex:
                raise serializers.ValidationError(f"Vertex {i} must have 'x' and 'y' keys.")
            for axis in ('x', 'y'):
                coord = vertex[axis]
                if not isinstance(coord, (int, float)):
                    raise serializers.ValidationError(
                        f"Vertex {i} '{axis}' must be a number, got {type(coord).__name__}."
                    )
                if not (0.0 <= float(coord) <= 1.0):
                    raise serializers.ValidationError(
                        f"Vertex {i} '{axis}' must be between 0.0 and 1.0, got {coord}."
                    )
        return value

    def create(self, validated_data):
        """Create annotation with nested metadata and set added_by from request."""
        metadata_data = validated_data.pop('metadata', [])
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        annotation = FloorPlanAnnotation.objects.create(**validated_data)
        for meta in metadata_data:
            FloorPlanAnnotationMetadata.objects.create(
                annotation=annotation,
                added_by=validated_data.get('added_by'),
                **meta,
            )
        return annotation

    def update(self, instance, validated_data):
        """Update annotation; if metadata_write provided, replace all metadata."""
        metadata_data = validated_data.pop('metadata', None)
        instance = super().update(instance, validated_data)
        if metadata_data is not None:
            instance.metadata.all().delete()
            request = self.context.get('request')
            added_by = request.user if request and request.user.is_authenticated else None
            for meta in metadata_data:
                FloorPlanAnnotationMetadata.objects.create(
                    annotation=instance,
                    added_by=added_by,
                    **meta,
                )
        return instance


class FloorPlanListSerializer(serializers.ModelSerializer):
    """Summary serializer for FloorPlan used in list views."""

    image_url = serializers.SerializerMethodField(read_only=True)
    venue_name = serializers.CharField(source='venue.poi.name', read_only=True)

    class Meta:
        model = FloorPlan
        fields = (
            'id', 'name', 'level', 'level_label',
            'image_url', 'original_width', 'original_height',
            'venue_name', 'added_at', 'updated_at',
        )

    @extend_schema_field({'type': 'string', 'format': 'uri', 'nullable': True})
    def get_image_url(self, obj) -> Optional[str]:
        """Return the absolute URL of the floor plan image."""
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        if obj.image:
            return obj.image.url
        return None


class FloorPlanDetailSerializer(FloorPlanListSerializer):
    """Detail serializer for FloorPlan with nested annotations."""

    annotations = FloorPlanAnnotationSerializer(many=True, read_only=True)

    class Meta(FloorPlanListSerializer.Meta):
        fields = FloorPlanListSerializer.Meta.fields + ('annotations',)


class FloorPlanCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Create/Update serializer for FloorPlan.

    Accepts image uploads via multipart/form-data. The original_width and
    original_height fields are populated automatically by opening the uploaded
    image with Pillow — client-supplied dimension values are ignored.
    """

    image_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = FloorPlan
        fields = (
            'id', 'venue', 'name', 'level', 'level_label', 'image',
            'image_url', 'original_width', 'original_height',
        )
        read_only_fields = ('id', 'image_url', 'original_width', 'original_height')

    @extend_schema_field({'type': 'string', 'format': 'uri', 'nullable': True})
    def get_image_url(self, obj) -> Optional[str]:
        """Return the absolute URL of the floor plan image."""
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        if obj.image:
            return obj.image.url
        return None

    def validate_image(self, value):
        """Validate that the uploaded file is a valid image."""
        from PIL import Image as PillowImage
        try:
            img = PillowImage.open(value)
            img.verify()
        except Exception:
            raise serializers.ValidationError("The uploaded file is not a valid image.")
        # Reset file pointer after verify() (which exhausts the file)
        value.seek(0)
        return value

    def _extract_dimensions(self, image_file):
        """Open the image with Pillow and return (width, height) in pixels."""
        from PIL import Image as PillowImage
        image_file.seek(0)
        img = PillowImage.open(image_file)
        return img.size  # (width, height)

    def create(self, validated_data):
        """Create FloorPlan, extracting pixel dimensions from the uploaded image."""
        image = validated_data.get('image')
        width, height = self._extract_dimensions(image)
        validated_data['original_width'] = width
        validated_data['original_height'] = height
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Update FloorPlan; re-extract dimensions if a new image is provided."""
        if 'image' in validated_data:
            image = validated_data['image']
            width, height = self._extract_dimensions(image)
            validated_data['original_width'] = width
            validated_data['original_height'] = height
        return super().update(instance, validated_data)
