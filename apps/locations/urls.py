"""
URL configuration for locations app.

Defines API routes for all location-related endpoints following the /api/locations/ pattern.

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.locations.api.viewsets import (
    CountryLocationViewSet,
    ClusterLocationViewSet,
    ChapterLocationViewSet,
    AreaLocationViewSet,
    RelativeAreaViewSet,
    POIViewSet,
    VenueViewSet,
    RoomVenueViewSet,
    VenueContactViewSet,
    VenueMetadataViewSet,
    FloorPlanViewSet,
    FloorPlanAnnotationViewSet,
    FloorPlanAnnotationMetadataViewSet,
)
from apps.locations.api.statistics_viewsets import LocationStatisticsViewSet

app_name = 'locations'

# Initialize router
router = DefaultRouter()

# Register viewsets with appropriate patterns
router.register(r'countries', CountryLocationViewSet, basename='country')
router.register(r'clusters', ClusterLocationViewSet, basename='cluster')
router.register(r'chapters', ChapterLocationViewSet, basename='chapter')
router.register(r'areas', AreaLocationViewSet, basename='area')
router.register(r'relative-areas', RelativeAreaViewSet, basename='relativearea')
router.register(r'pois', POIViewSet, basename='poi')
router.register(r'venues', VenueViewSet, basename='venue')
router.register(r'rooms', RoomVenueViewSet, basename='room')
router.register(r'venue-contacts', VenueContactViewSet, basename='venuecontact')
router.register(r'venue-metadata', VenueMetadataViewSet, basename='venuemetadata')

urlpatterns = [
    path(
        'locations/statistics/distribution-map/',
        LocationStatisticsViewSet.as_view({'get': 'distribution_map'}),
        name='location-distribution-map',
    ),
    path('locations/', include(router.urls)),

    # ── Nested: Floor Plans under Venue ──────────────────────────────────
    path(
        'locations/venues/<int:venue_pk>/floor-plans/',
        FloorPlanViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='venue-floor-plans-list',
    ),
    path(
        'locations/venues/<int:venue_pk>/floor-plans/<int:pk>/',
        FloorPlanViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}),
        name='venue-floor-plans-detail',
    ),

    # ── Nested: Annotations under Floor Plan ─────────────────────────────
    path(
        'locations/venues/<int:venue_pk>/floor-plans/<int:floor_plan_pk>/annotations/',
        FloorPlanAnnotationViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='floor-plan-annotations-list',
    ),
    path(
        'locations/venues/<int:venue_pk>/floor-plans/<int:floor_plan_pk>/annotations/<int:pk>/',
        FloorPlanAnnotationViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}),
        name='floor-plan-annotations-detail',
    ),

    # ── Nested: Metadata under Annotation ────────────────────────────────
    path(
        'locations/venues/<int:venue_pk>/floor-plans/<int:floor_plan_pk>/annotations/<int:annotation_pk>/metadata/',
        FloorPlanAnnotationMetadataViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='annotation-metadata-list',
    ),
    path(
        'locations/venues/<int:venue_pk>/floor-plans/<int:floor_plan_pk>/annotations/<int:annotation_pk>/metadata/<int:pk>/',
        FloorPlanAnnotationMetadataViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}),
        name='annotation-metadata-detail',
    ),
]
