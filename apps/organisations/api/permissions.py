"""
Production-grade permissions for the organisations app.

Provides comprehensive permission classes for organisation management with
support for organisation control, event-based ADMINISTRATIVE roles, Django staff, and superusers.

Permission Classes:
    - IsOrganisationController: Checks if user controls the organisation
    - IsOrganisationControllerOrEventAdmin: Combined permission for organisation operations
    - IsOrganisationMember: Checks if user is a member of the organisation
    - IsOrganisationRelated: Checks if user has any relation to the organisation

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import permissions
from django.contrib.auth import get_user_model
from typing import Any

from apps.organisations.models import OrganisationControl, UserOrganisationMembership
from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices

User = get_user_model()


class IsOrganisationController(permissions.BasePermission):
    """
    Permission class to check if user has control over an organisation.
    
    Grants access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    3. Has OrganisationControl for the relevant organisation
    
    This permission should be used for operations that require organisation-level control
    such as managing contacts, invites, or organisation settings.
    """
    
    message = "You must be a controller of this organisation to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has permission at the request level."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # For object-specific checks, allow through to object-level permission
        return True
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user has control over the organisation."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Get the organisation from the object
        organisation = self._get_organisation_from_object(obj)
        if not organisation:
            return False
        
        # Check if user has control over this organisation
        return OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user
        ).exists()
    
    def _get_organisation_from_object(self, obj) -> Any:
        """Extract the organisation from various object types."""
        from apps.organisations.models import (
            Organisation, OrganisationContact, OrganisationControl,
            UserOrganisationMembership, OrganisationAcceptanceCode,
            OrganisationInvite, InvolvedEventOrganisation,
            EventSponsor, EventSponsorPackage, Leader
        )
        
        if isinstance(obj, Organisation):
            return obj
        elif hasattr(obj, 'organisation'):
            return obj.organisation
        elif isinstance(obj, Leader):
            # Leader uses generic FK, check if it points to an organisation
            if obj.target_type and obj.target_type.model == 'organisation':
                return obj.authority_object
        
        return None


class IsOrganisationControllerOrEventAdmin(permissions.BasePermission):
    """
    Combined permission: user must be an organisation controller OR have
    ADMINISTRATIVE role in related event.
    
    Grants access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    3. Has OrganisationControl for the relevant organisation
    4. Has EventRoleAssignment with ADMINISTRATIVE category for the related event
    
    This is the primary permission for most organisation operations.
    """
    
    message = "You must be an organisation controller or event administrator to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has permission at the request level."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Allow through to object-level check
        return True
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user has control or administrative role."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user has administrative role in related event first.
        event = self._get_event_from_object(obj)
        if event and self._user_has_administrative_role(request.user, event):
            return True

        # Get the organisation from the object
        organisation = self._get_organisation_from_object(obj)
        if not organisation:
            return False
        
        # Check if user has control over this organisation
        if OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user
        ).exists():
            return True
        
        return False
    
    def _get_organisation_from_object(self, obj) -> Any:
        """Extract the organisation from various object types."""
        from apps.organisations.models import (
            Organisation, OrganisationContact, OrganisationControl,
            UserOrganisationMembership, OrganisationAcceptanceCode,
            OrganisationInvite, InvolvedEventOrganisation,
            EventSponsor, EventSponsorPackage, Leader
        )
        
        if isinstance(obj, Organisation):
            return obj
        elif hasattr(obj, 'organisation'):
            return obj.organisation
        elif isinstance(obj, Leader):
            if obj.target_type and obj.target_type.model == 'organisation':
                return obj.authority_object
        
        return None
    
    def _get_event_from_object(self, obj) -> Any:
        """Extract the event from various object types."""
        from apps.organisations.models import (
            InvolvedEventOrganisation, EventSponsor, EventSponsorPackage
        )
        
        if hasattr(obj, 'event'):
            return obj.event
        elif isinstance(obj, EventSponsorPackage):
            return obj.event
        
        return None
    
    def _user_has_administrative_role(self, user, event) -> bool:
        """Check if user has an ADMINISTRATIVE role for the given event."""
        return EventRoleAssignment.objects.filter(
            user=user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()


class IsOrganisationMember(permissions.BasePermission):
    """
    Permission class to check if user is a member of an organisation.
    
    Grants access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    3. Has UserOrganisationMembership for the relevant organisation
    
    This permission is useful for read-only operations or member-specific actions.
    """
    
    message = "You must be a member of this organisation to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has permission at the request level."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Allow through to object-level check
        return True
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user is a member of the organisation."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Get the organisation from the object
        organisation = self._get_organisation_from_object(obj)
        if not organisation:
            return False
        
        # Check if user is a member of this organisation
        return UserOrganisationMembership.objects.filter(
            organisation=organisation,
            user=request.user
        ).exists()
    
    def _get_organisation_from_object(self, obj) -> Any:
        """Extract the organisation from various object types."""
        from apps.organisations.models import (
            Organisation, OrganisationContact, OrganisationControl,
            UserOrganisationMembership, OrganisationAcceptanceCode,
            OrganisationInvite, InvolvedEventOrganisation,
            EventSponsor, EventSponsorPackage, Leader
        )
        
        if isinstance(obj, Organisation):
            return obj
        elif hasattr(obj, 'organisation'):
            return obj.organisation
        elif isinstance(obj, Leader):
            if obj.target_type and obj.target_type.model == 'organisation':
                return obj.authority_object
        
        return None


class IsOrganisationRelated(permissions.BasePermission):
    """
    Combined permission: user must have any relation to the organisation
    (controller, member, or event admin).
    
    This is the most permissive organisation-related permission.
    """
    
    message = "You must have a relationship with this organisation to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has permission at the request level."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Allow through to object-level check
        return True
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user has any relation to the organisation."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Get the organisation from the object
        organisation = self._get_organisation_from_object(obj)
        if not organisation:
            return False
        
        # Check if user has control
        if OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user
        ).exists():
            return True
        
        # Check if user is a member
        if UserOrganisationMembership.objects.filter(
            organisation=organisation,
            user=request.user
        ).exists():
            return True
        
        # Check if user has administrative role in related event
        event = self._get_event_from_object(obj)
        if event:
            return self._user_has_administrative_role(request.user, event)
        
        return False
    
    def _get_organisation_from_object(self, obj) -> Any:
        """Extract the organisation from various object types."""
        from apps.organisations.models import (
            Organisation, OrganisationContact, OrganisationControl,
            UserOrganisationMembership, OrganisationAcceptanceCode,
            OrganisationInvite, InvolvedEventOrganisation,
            EventSponsor, EventSponsorPackage, Leader
        )
        
        if isinstance(obj, Organisation):
            return obj
        elif hasattr(obj, 'organisation'):
            return obj.organisation
        elif isinstance(obj, Leader):
            if obj.target_type and obj.target_type.model == 'organisation':
                return obj.authority_object
        
        return None
    
    def _get_event_from_object(self, obj) -> Any:
        """Extract the event from various object types."""
        from apps.organisations.models import (
            InvolvedEventOrganisation, EventSponsor, EventSponsorPackage
        )
        
        if hasattr(obj, 'event'):
            return obj.event
        elif isinstance(obj, EventSponsorPackage):
            return obj.event
        
        return None
    
    def _user_has_administrative_role(self, user, event) -> bool:
        """Check if user has an ADMINISTRATIVE role for the given event."""
        return EventRoleAssignment.objects.filter(
            user=user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()


class IsReadOnly(permissions.BasePermission):
    """Permission that allows read-only access for safe methods."""
    
    def has_permission(self, request, view) -> bool:
        return request.method in permissions.SAFE_METHODS
    
    def has_object_permission(self, request, view, obj) -> bool:
        return request.method in permissions.SAFE_METHODS
