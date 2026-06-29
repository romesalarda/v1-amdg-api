"""
Production-grade permissions for the organisations app.

Provides comprehensive permission classes for organisation management with
support for organisation control, event-based ADMINISTRATIVE roles, Django staff, and superusers.

Permission Classes:
    - IsOrganisationController: Checks if user controls the organisation
    - IsOrganisationControllerOrEventAdmin: Combined permission for organisation operations
    - IsOrganisationMember: Checks if user is a member of the organisation
    - IsOrganisationRelated: Checks if user has any relation to the organisation
    - HasLeaderPermissionCode: Base class for leader permission code checks
    - HasMembershipAccess: Checks ALLOW_MEMBERSHIP_ACCESS leader permission
    - HasManageLeadersPermission: Checks ALLOW_MANAGE_LEADERS leader permission
    - HasPolicyManagementPermission: Checks ALLOW_POLICY_MANAGEMENT leader permission
    - HasReviewAccessPermission: Checks ALLOW_REVIEW_ACCESS leader permission
    - HasMonetaryAccessPermission: Checks ALLOW_MONETARY_ACCESS leader permission

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import permissions
from django.contrib.auth import get_user_model
from typing import Any

from apps.organisations.models import OrganisationControl, UserOrganisationMembership
from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
from apps.utils.querying import get_organisation_or_url_safe_title

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

        from apps.organisations.models import Organisation

        """Check if user has permission at the request level."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # if request.query_params.get("organisation"): # refuse access if no organisation is specified in query params
        #     org_id = request.query_params.get("organisation")
        #     try:
        #         organisation = get_organisation_or_url_safe_title(org_id)
        #         if not (request.user.is_superuser or request.user.is_staff or OrganisationControl.objects.filter(
        #             organisation=organisation,
        #             user=request.user,
        #         ).exists()):
        #             print(f"User {request.user} does not have control over organisation {organisation}.")
        #             return False
        #         return True
        #     except Organisation.DoesNotExist:
        #         print(f"Organisation with ID {org_id} does not exist.")
        #         return False
        # print(f"User {request.user} has no permission to access the view {view}.")
        # return False
        org_id = view.kwargs.get("organisation") or view.kwargs.get("org_id")

        # 2. Fallback to query param
        if not org_id:
            org_id = request.query_params.get("organisation")

        if not org_id:
            # No organisation provided anywhere → deny
            return False

        try:
            organisation = get_organisation_or_url_safe_title(org_id)
        except Organisation.DoesNotExist:
            return False

        # 3. Check control
        return OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user
        ).exists()
    
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
            Organisation, Leader
        )
        
        if isinstance(obj, Organisation):
            return obj
        elif hasattr(obj, 'organisation'):
            return obj.organisation
        elif isinstance(obj, Leader):
            # Leader uses generic FK, check if it points to an organisation
            return obj.organisation
        
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
            Organisation, Leader
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
        from apps.organisations.models import EventSponsorPackage
        
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


# ============================================================================
# LEADER PERMISSION CODE CLASSES
# ============================================================================


def _method_to_crud_flag(method: str) -> str:
    """Map an HTTP method to the corresponding LeaderPermission CRUD flag name."""
    if method in permissions.SAFE_METHODS:
        return 'allow_read'
    if method == 'POST':
        return 'allow_create'
    if method in ('PUT', 'PATCH'):
        return 'allow_update'
    if method == 'DELETE':
        return 'allow_delete'
    return 'allow_read'


class HasLeaderPermissionCode(permissions.BasePermission):
    """
    Base permission class for checking leader-specific permission codes.

    Subclasses must set `required_code` to a value from LeaderPermissionCode.
    Access is granted if the requesting user:
      1. Is a Django superuser or staff member, OR
      2. Has an OrganisationControl record (is a controller), OR
      3. Has a LeaderPermission record with the required_code and the CRUD
         flag corresponding to the HTTP method is True (allow_read for GET,
         allow_create for POST, allow_update for PUT/PATCH, allow_delete for DELETE).

    Object-level checks additionally verify the leader's organisation matches
    the object's organisation to prevent cross-organisation access.
    """

    required_code: str | None = None
    message = "You do not have the required leader permission for this action."

    def _get_crud_flag(self, request) -> str:
        return _method_to_crud_flag(request.method)

    def _user_has_leader_permission(self, user, crud_flag: str) -> bool:
        from apps.organisations.models import LeaderPermission
        if self.required_code is None:
            return False
        return LeaderPermission.objects.filter(
            leader__user=user,
            permission_code=self.required_code,
            **{crud_flag: True},
        ).exists()

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True
        if OrganisationControl.objects.filter(user=request.user).exists():
            return True
        crud_flag = self._get_crud_flag(request)
        return self._user_has_leader_permission(request.user, crud_flag)

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True

        # Derive organisation from the object for scoped checks
        organisation = self._get_organisation_from_object(obj)

        if organisation:
            # Controller of this specific organisation always passes
            if OrganisationControl.objects.filter(
                organisation=organisation, user=request.user
            ).exists():
                return True
            # Leader permission must be scoped to this organisation
            from apps.organisations.models import LeaderPermission
            if self.required_code is None:
                return False
            crud_flag = self._get_crud_flag(request)
            return LeaderPermission.objects.filter(
                leader__user=request.user,
                leader__organisation=organisation,
                permission_code=self.required_code,
                **{crud_flag: True},
            ).exists()

        # Fall back to unscoped check when organisation cannot be derived
        if OrganisationControl.objects.filter(user=request.user).exists():
            return True
        crud_flag = self._get_crud_flag(request)
        return self._user_has_leader_permission(request.user, crud_flag)

    def _get_organisation_from_object(self, obj) -> Any:
        """Extract the organisation from common object shapes."""
        from apps.organisations.models import Organisation
        if isinstance(obj, Organisation):
            return obj
        if hasattr(obj, 'organisation'):
            return obj.organisation
        return None


class HasMembershipAccess(HasLeaderPermissionCode):
    """Grants access to leaders with ALLOW_MEMBERSHIP_ACCESS permission code."""
    required_code = 'allow_membership_access'
    message = "You need the membership access leader permission for this action."


class HasManageLeadersPermission(HasLeaderPermissionCode):
    """Grants access to leaders with ALLOW_MANAGE_LEADERS permission code."""
    required_code = 'allow_manage_leaders'
    message = "You need the manage leaders permission for this action."


class HasPolicyManagementPermission(HasLeaderPermissionCode):
    """Grants access to leaders with ALLOW_POLICY_MANAGEMENT permission code."""
    required_code = 'allow_policy_management'
    message = "You need the policy management leader permission for this action."


class HasReviewAccessPermission(HasLeaderPermissionCode):
    """Grants access to leaders with ALLOW_REVIEW_ACCESS permission code."""
    required_code = 'allow_review_access'
    message = "You need the review access leader permission for this action."


class HasMonetaryAccessPermission(HasLeaderPermissionCode):
    """Grants access to leaders with ALLOW_MONETARY_ACCESS permission code."""
    required_code = 'allow_monetary_access'
    message = "You need the monetary access leader permission for this action."


# ============================================================================
# COMPOSITE PERMISSIONS
# ============================================================================


class WriteRequiresOrganisationController(permissions.BasePermission):
    """
    Read-only access for any authenticated user; write access requires the user
    to be a Django superuser/staff or hold an OrganisationControl record.

    Intended for use in viewsets where list/retrieve are safe-readable but
    create/update/delete must be gated to controllers.
    """

    message = "You must be an organisation controller to perform write operations."

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser or request.user.is_staff:
            return True
        return OrganisationControl.objects.filter(user=request.user).exists()

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser or request.user.is_staff:
            return True
        organisation = self._get_organisation_from_object(obj)
        if organisation:
            return OrganisationControl.objects.filter(
                organisation=organisation, user=request.user
            ).exists()
        return OrganisationControl.objects.filter(user=request.user).exists()

    def _get_organisation_from_object(self, obj) -> Any:
        from apps.organisations.models import Organisation
        if isinstance(obj, Organisation):
            return obj
        if hasattr(obj, 'organisation'):
            return obj.organisation
        if hasattr(obj, 'leader') and hasattr(obj.leader, 'organisation'):
            return obj.leader.organisation
        return None


class WriteRequiresControllerOrPolicyManager(permissions.BasePermission):
    """
    Read-only access for any authenticated user; write access requires the user
    to be a controller OR a leader with ALLOW_POLICY_MANAGEMENT permission.
    """

    message = "You must be an organisation controller or policy manager to perform write operations."

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser or request.user.is_staff:
            return True
        if OrganisationControl.objects.filter(user=request.user).exists():
            return True
        from apps.organisations.models import LeaderPermission
        return LeaderPermission.objects.filter(
            leader__user=request.user,
            permission_code='allow_policy_management',
            allow_update=True,
        ).exists()

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser or request.user.is_staff:
            return True
        organisation = self._get_organisation_from_object(obj)
        if organisation:
            if OrganisationControl.objects.filter(
                organisation=organisation, user=request.user
            ).exists():
                return True
            from apps.organisations.models import LeaderPermission
            return LeaderPermission.objects.filter(
                leader__user=request.user,
                leader__organisation=organisation,
                permission_code='allow_policy_management',
                allow_update=True,
            ).exists()
        # Fallback to unscoped check
        return self.has_permission(request, view)

    def _get_organisation_from_object(self, obj) -> Any:
        from apps.organisations.models import Organisation
        if isinstance(obj, Organisation):
            return obj
        if hasattr(obj, 'organisation'):
            return obj.organisation
        return None
