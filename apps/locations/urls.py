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
)

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
    path('locations/', include(router.urls)),
]
