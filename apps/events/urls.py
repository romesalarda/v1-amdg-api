from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.events.api.viewsets import (
    EventTypeViewSet,
    EventViewSet,
    EventSettingsViewSet,
    EventAuthorizationViewSet,
    EventPermissionViewSet,
    EventPermissionAssignmentViewSet,
    EventRoleViewSet,
    EventRoleAssignmentViewSet,
    EventStaffViewSet,
    EventStaffAvailabilityViewSet,
    EventStaffInviteViewSet,
    EventReviewViewSet,
    EventQuestionViewSet,
    EventQuestionOptionViewSet,
    EventQuestionAnswerViewSet,
    EventQuestionAnswerChoiceViewSet,
    EventVenueViewSet,
    EventVenueRoomViewSet,
    EventVenueContactViewSet,
    EventVenueMetadataViewSet,
)
from apps.events.api.statistics_viewsets import EventStatisticsViewSet

app_name = 'events'

router = DefaultRouter()
router.register(r'types', EventTypeViewSet, basename='eventtype')
router.register(r'list', EventViewSet, basename='event')
router.register(r'settings', EventSettingsViewSet, basename='eventsettings')
router.register(r'authorizations', EventAuthorizationViewSet, basename='eventauthorization')
router.register(r'permissions', EventPermissionViewSet, basename='eventpermission')
router.register(r'permission-assignments', EventPermissionAssignmentViewSet, basename='eventpermissionassignment')
router.register(r'roles', EventRoleViewSet, basename='eventrole')
router.register(r'role-assignments', EventRoleAssignmentViewSet, basename='eventroleassignment')
router.register(r'staff', EventStaffViewSet, basename='eventstaff')
router.register(r'staff-availability', EventStaffAvailabilityViewSet, basename='eventstaffavailability')
router.register(r'staff-invites', EventStaffInviteViewSet, basename='eventstaffinvite')
router.register(r'reviews', EventReviewViewSet, basename='eventreview')
router.register(r'questions', EventQuestionViewSet, basename='eventquestion')
router.register(r'question-options', EventQuestionOptionViewSet, basename='eventquestionoption')
router.register(r'question-answers', EventQuestionAnswerViewSet, basename='eventquestionanswer')
router.register(r'answer-choices', EventQuestionAnswerChoiceViewSet, basename='eventquestionanswerchoice')
router.register(r'venues', EventVenueViewSet, basename='eventvenue')
router.register(r'venue-rooms', EventVenueRoomViewSet, basename='eventvenueroom')
router.register(r'venue-contacts', EventVenueContactViewSet, basename='eventvenuecontact')
router.register(r'venue-metadata', EventVenueMetadataViewSet, basename='eventvenuemetadata')
router.register(r'statistics', EventStatisticsViewSet, basename='eventstatistics')

urlpatterns = [
    path('event/', include(router.urls)),
]
