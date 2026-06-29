"""
URL configuration for organisations app.

Defines API routes for all organisation-related endpoints following the /list/ pattern.

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.organisations.api.viewsets import (
    OrganisationViewSet,
    OrganisationContactViewSet,
    OrganisationControlViewSet,
    UserOrganisationMembershipViewSet,
    OrganisationAcceptanceCodeViewSet,
    OrganisationInviteViewSet,
    InvolvedEventOrganisationViewSet,
    EventSponsorViewSet,
    EventSponsorPackageViewSet,
    EventSponsorInviteViewSet,
    LeaderViewSet,
    LocationLeaderInviteViewSet,
    LeaderPermissionViewSet,
    OrganisationEventTypePolicyRestrictionViewSet,
)
from apps.organisations.api.statistics_viewsets import OrganisationStatisticsViewSet

app_name = 'organisations'

# Initialize router
router = DefaultRouter()

# Register viewsets with appropriate patterns
router.register(r'list', OrganisationViewSet, basename='organisation')
router.register(r'contacts', OrganisationContactViewSet, basename='organisationcontact')
router.register(r'controls', OrganisationControlViewSet, basename='organisationcontrol')
router.register(r'memberships', UserOrganisationMembershipViewSet, basename='organisationmembership')
router.register(r'acceptance-codes', OrganisationAcceptanceCodeViewSet, basename='acceptancecode')
router.register(r'invites', OrganisationInviteViewSet, basename='organisationinvite')
router.register(r'involved-events', InvolvedEventOrganisationViewSet, basename='involvedeventorganisation')
router.register(r'sponsors', EventSponsorViewSet, basename='eventsponsor')
router.register(r'sponsor-packages', EventSponsorPackageViewSet, basename='sponsorpackage')
router.register(r'sponsor-invites', EventSponsorInviteViewSet, basename='eventsponsorinvite')
router.register(r'leaders', LeaderViewSet, basename='leader')
router.register(r'leader-invites', LocationLeaderInviteViewSet, basename='locationleaderinvite')
router.register(r'leader-permissions', LeaderPermissionViewSet, basename='leaderpermission')
router.register(r'event-type-restrictions', OrganisationEventTypePolicyRestrictionViewSet, basename='eventtyperestriction')
router.register(r'statistics', OrganisationStatisticsViewSet, basename='organisationstatistics')

urlpatterns = [
    path('organisations/', include(router.urls)),
]
