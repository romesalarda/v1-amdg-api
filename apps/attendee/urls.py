"""
URL configuration for the attendee app.

Provides comprehensive routing with nested resources under attendees.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.attendee.api.viewsets import (
    AttendeeViewSet,
    AttendeeGuardianViewSet,
    AttendeeActionViewSet,
    FamilyGroupViewSet,
    FamilyAttendeeViewSet,
    AttendeeMessageViewSet,
    AccessibilityRequirementViewSet,
    AttendeeAccessibilityRequirementViewSet,
    DietaryRequirementViewSet,
    AttendeeDietaryRequirementViewSet,
    MedicalConditionViewSet,
    AttendeeMedicalConditionViewSet,
    EmergencyContactViewSet,
    ConsentViewSet,
    AttendeeConsentViewSet,
    EventAttendanceViewSet,
    AttendeeOrganisationViewSet,
)
from apps.attendee.api.statistics_viewset import AttendeeStatisticsViewSet

app_name = 'attendee'

# Create main router
router = DefaultRouter()

# Core attendee endpoints
router.register(r'attendees', AttendeeViewSet, basename='attendee')
router.register(r'guardians', AttendeeGuardianViewSet, basename='attendeeguardian')
router.register(r'actions', AttendeeActionViewSet, basename='attendeeaction')

# Statistics endpoints
router.register(r'attendees/statistics', AttendeeStatisticsViewSet, basename='attendeestatistics')

# Family and messaging endpoints
router.register(r'family-groups', FamilyGroupViewSet, basename='familygroup')
router.register(r'family-attendees', FamilyAttendeeViewSet, basename='familyattendee')
router.register(r'messages', AttendeeMessageViewSet, basename='attendeemessage')

# Reference data endpoints (not nested under specific attendee)
router.register(r'accessibility-requirements', AccessibilityRequirementViewSet, basename='accessibilityrequirement')
router.register(r'dietary-requirements', DietaryRequirementViewSet, basename='dietaryrequirement')
router.register(r'medical-conditions', MedicalConditionViewSet, basename='medicalcondition')
router.register(r'consents', ConsentViewSet, basename='consent')
router.register(r'event-attendances', EventAttendanceViewSet, basename='eventattendance')

# Nested URL patterns for attendee-specific resources
nested_patterns = [
    path('dietary-requirements/', AttendeeDietaryRequirementViewSet.as_view({'get': 'list', 'post': 'create'}), name='attendee-dietary-requirements-list'),
    path('dietary-requirements/<int:pk>/', AttendeeDietaryRequirementViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='attendee-dietary-requirements-detail'),
    
    path('medical-conditions/', AttendeeMedicalConditionViewSet.as_view({'get': 'list', 'post': 'create'}), name='attendee-medical-conditions-list'),
    path('medical-conditions/<int:pk>/', AttendeeMedicalConditionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='attendee-medical-conditions-detail'),
    
    path('accessibility-requirements/', AttendeeAccessibilityRequirementViewSet.as_view({'get': 'list', 'post': 'create'}), name='attendee-accessibility-requirements-list'),
    path('accessibility-requirements/<int:pk>/', AttendeeAccessibilityRequirementViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='attendee-accessibility-requirements-detail'),
    
    path('emergency-contacts/', EmergencyContactViewSet.as_view({'get': 'list', 'post': 'create'}), name='attendee-emergency-contacts-list'),
    path('emergency-contacts/<int:pk>/', EmergencyContactViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='attendee-emergency-contacts-detail'),
    
    path('consents/', AttendeeConsentViewSet.as_view({'get': 'list', 'post': 'create'}), name='attendee-consents-list'),
    path('consents/<int:pk>/', AttendeeConsentViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='attendee-consents-detail'),
    
    path('organisations/', AttendeeOrganisationViewSet.as_view({'get': 'list', 'post': 'create'}), name='attendee-organisations-list'),
    path('organisations/<int:pk>/', AttendeeOrganisationViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'}), name='attendee-organisations-detail'),
]

urlpatterns = [
    path('', include(router.urls)),
    path('attendees/<uuid:attendee_id>/', include(nested_patterns)),
]

