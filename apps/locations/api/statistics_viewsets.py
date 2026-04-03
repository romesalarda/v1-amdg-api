"""
Location statistics endpoints for map-oriented distributions.
"""

from uuid import UUID

from django.db.models import Count, Q
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.attendee.models import Attendee
from apps.locations.models import AreaLocation, ChapterLocation, ClusterLocation, CountryLocation


LEVEL_PARAM = OpenApiParameter(
    name='level',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Location granularity for distribution points.',
    required=False,
    enum=['area', 'chapter', 'cluster', 'country'],
    default='area',
)

EVENT_ID_PARAM = OpenApiParameter(
    name='event_id',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Optional event UUID or url-safe title to scope attendee counts.',
    required=False,
)

INCLUDE_INACTIVE_PARAM = OpenApiParameter(
    name='include_inactive',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Include inactive locations if true.',
    required=False,
    default=False,
)


class LocationDistributionFeatureSerializer(serializers.Serializer):
    type = serializers.CharField()
    geometry = serializers.DictField()
    properties = serializers.DictField()


class LocationDistributionMapSerializer(serializers.Serializer):
    level = serializers.CharField()
    event_id = serializers.CharField(allow_null=True, required=False)
    total_attendees = serializers.IntegerField()
    total_with_location = serializers.IntegerField()
    total_without_location = serializers.IntegerField()
    type = serializers.CharField()
    features = LocationDistributionFeatureSerializer(many=True)


class LocationDistributionFilterSet(filters.FilterSet):
    level = filters.ChoiceFilter(
        choices=[('area', 'area'), ('chapter', 'chapter'), ('cluster', 'cluster'), ('country', 'country')],
        method='filter_noop',
        help_text='Location granularity for distribution points.',
    )
    event_id = filters.CharFilter(method='filter_noop', help_text='Optional event UUID or url-safe title.')
    include_inactive = filters.BooleanFilter(method='filter_noop', help_text='Include inactive locations if true.')

    class Meta:
        model = AreaLocation
        fields = []

    def filter_noop(self, queryset, name, value):
        return queryset


class LocationStatisticsViewSet(viewsets.GenericViewSet):
    """Statistics endpoints for locations."""

    permission_classes = [AllowAny]
    serializer_class = LocationDistributionMapSerializer
    queryset = AreaLocation.objects.none()
    filter_backends = [DjangoFilterBackend]
    filterset_class = LocationDistributionFilterSet

    def _parse_event_filter(self, event_id):
        if not event_id:
            return {}

        try:
            UUID(str(event_id), version=4)
            return {'event__event_id': str(event_id)}
        except ValueError:
            return {'event__url_safe_title': str(event_id)}

    def _base_attendee_queryset(self, event_id):
        return Attendee.objects.filter(deleted_at__isnull=True, **self._parse_event_filter(event_id))

    def _build_event_q(self, relation_prefix, event_id):
        if not event_id:
            return Q()

        try:
            UUID(str(event_id), version=4)
            return Q(**{f'{relation_prefix}__event__event_id': str(event_id)})
        except ValueError:
            return Q(**{f'{relation_prefix}__event__url_safe_title': str(event_id)})

    def _build_area_features(self, event_id, include_inactive):
        queryset = AreaLocation.objects.select_related('chapter__cluster__country').filter(
            longitude__isnull=False,
            latitude__isnull=False,
        )
        if not include_inactive:
            queryset = queryset.filter(active=True)

        event_filter = self._build_event_q('attendees_from', event_id)
        queryset = queryset.annotate(
            attendee_count=Count(
                'attendees_from',
                filter=Q(attendees_from__deleted_at__isnull=True) & event_filter,
                distinct=True,
            )
        ).filter(attendee_count__gt=0)

        features = []
        for item in queryset:
            features.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [float(item.longitude), float(item.latitude)],
                },
                'properties': {
                    'level': 'area',
                    'location_id': item.id,
                    'location_uuid': str(item.area_id),
                    'label': item.area_name,
                    'code': item.area_code,
                    'attendee_count': item.attendee_count,
                    'area': item.area_name,
                    'chapter': item.chapter.chapter_name,
                    'cluster': item.chapter.cluster.cluster_name,
                    'country': item.chapter.cluster.country.country.name if item.chapter.cluster.country.country else None,
                },
            })

        return features

    def _build_chapter_features(self, event_id, include_inactive):
        queryset = ChapterLocation.objects.select_related('cluster__country').filter(
            longitude__isnull=False,
            latitude__isnull=False,
        )
        if not include_inactive:
            queryset = queryset.filter(active=True)

        event_filter = self._build_event_q('areas__attendees_from', event_id)
        queryset = queryset.annotate(
            attendee_count=Count(
                'areas__attendees_from',
                filter=Q(areas__attendees_from__deleted_at__isnull=True) & event_filter,
                distinct=True,
            )
        ).filter(attendee_count__gt=0)

        features = []
        for item in queryset:
            features.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [float(item.longitude), float(item.latitude)],
                },
                'properties': {
                    'level': 'chapter',
                    'location_id': item.id,
                    'label': item.chapter_name,
                    'code': item.chapter_code,
                    'attendee_count': item.attendee_count,
                    'chapter': item.chapter_name,
                    'cluster': item.cluster.cluster_name,
                    'country': item.cluster.country.country.name if item.cluster.country.country else None,
                },
            })

        return features

    def _build_cluster_features(self, event_id, include_inactive):
        queryset = ClusterLocation.objects.select_related('country').filter(
            longitude__isnull=False,
            latitude__isnull=False,
        )
        if not include_inactive:
            queryset = queryset.filter(active=True)

        event_filter = self._build_event_q('chapters__areas__attendees_from', event_id)
        queryset = queryset.annotate(
            attendee_count=Count(
                'chapters__areas__attendees_from',
                filter=Q(chapters__areas__attendees_from__deleted_at__isnull=True) & event_filter,
                distinct=True,
            )
        ).filter(attendee_count__gt=0)

        features = []
        for item in queryset:
            features.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [float(item.longitude), float(item.latitude)],
                },
                'properties': {
                    'level': 'cluster',
                    'location_id': item.id,
                    'label': item.cluster_name,
                    'code': item.cluster_code,
                    'attendee_count': item.attendee_count,
                    'cluster': item.cluster_name,
                    'country': item.country.country.name if item.country.country else None,
                },
            })

        return features

    def _build_country_features(self, event_id, include_inactive):
        queryset = CountryLocation.objects.filter(
            longitude__isnull=False,
            latitude__isnull=False,
        )
        if not include_inactive:
            queryset = queryset.filter(active=True)

        event_filter = self._build_event_q('clusters__chapters__areas__attendees_from', event_id)
        queryset = queryset.annotate(
            attendee_count=Count(
                'clusters__chapters__areas__attendees_from',
                filter=Q(clusters__chapters__areas__attendees_from__deleted_at__isnull=True) & event_filter,
                distinct=True,
            )
        ).filter(attendee_count__gt=0)

        features = []
        for item in queryset:
            country_name = item.country.name if item.country else None
            features.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [float(item.longitude), float(item.latitude)],
                },
                'properties': {
                    'level': 'country',
                    'location_id': item.id,
                    'label': country_name,
                    'code': str(item.country) if item.country else None,
                    'attendee_count': item.attendee_count,
                    'country': country_name,
                },
            })

        return features

    @extend_schema(
        summary='Location distribution map',
        description=(
            'Returns GeoJSON points for area/chapter/cluster/country with attendee counts. '
            'Use level query parameter to switch location hierarchy.'
        ),
        parameters=[LEVEL_PARAM, EVENT_ID_PARAM, INCLUDE_INACTIVE_PARAM],
        responses={200: LocationDistributionMapSerializer},
        tags=['Locations'],
    )
    @action(detail=False, methods=['get'], url_path='distribution-map')
    def distribution_map(self, request):
        filters_instance = self.filterset_class(
            data=request.query_params,
            queryset=AreaLocation.objects.all(),
            request=request,
        )
        if not filters_instance.is_valid():
            return Response(
                {'error': filters_instance.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        level = (filters_instance.form.cleaned_data.get('level') or 'area').strip().lower()
        event_id = filters_instance.form.cleaned_data.get('event_id')
        include_inactive = bool(filters_instance.form.cleaned_data.get('include_inactive'))

        attendee_queryset = self._base_attendee_queryset(event_id)

        builders = {
            'area': self._build_area_features,
            'chapter': self._build_chapter_features,
            'cluster': self._build_cluster_features,
            'country': self._build_country_features,
        }

        features = builders[level](event_id, include_inactive)
        total_with_location = sum(item['properties']['attendee_count'] for item in features)
        total_attendees = attendee_queryset.count()

        return Response({
            'level': level,
            'event_id': event_id,
            'total_attendees': total_attendees,
            'total_with_location': total_with_location,
            'total_without_location': max(total_attendees - total_with_location, 0),
            'type': 'FeatureCollection',
            'features': features,
        })
