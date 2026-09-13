from rest_framework import permissions

from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
from apps.organisations.models import OrganisationControl

# ---------------------------------------------------------------------------
# Helpers shared across permission classes
# ---------------------------------------------------------------------------

def _get_event_from_obj(obj):
    """Extract an Event instance from an object or return the object itself."""
    if obj.__class__.__name__ == 'Event':
        return obj
    return getattr(obj, 'event', None)


def _user_is_event_staff_member(user, event):
    """Return True if *user* has an EventStaff record for *event*."""
    return event.staff_members.filter(user=user).exists()


def _user_has_administrative_role(user, event):
    """Return True if *user* has an ADMINISTRATIVE EventRole for *event*."""
    return EventRoleAssignment.objects.filter(
        user=user,
        event=event,
        role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
    ).exists()


def user_can_manage_event_forms(user, event) -> bool:
    """
    Return True if *user* may see/manage all form responses for *event*:
    the event creator, an assigned EventStaff member, a user with an
    ADMINISTRATIVE role, or Django staff/superuser.
    """
    if not user or not getattr(user, 'is_authenticated', False) or event is None:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return (
        event.created_by_id == user.id
        or _user_is_event_staff_member(user, event)
        or _user_has_administrative_role(user, event)
    )


# ---------------------------------------------------------------------------
# New granular permission classes (replace inline viewset checks)
# ---------------------------------------------------------------------------


class IsEventOwnerOrDjangoStaff(permissions.BasePermission):
    """
    Grants access when the request user is:
      - the event creator, OR
      - a Django staff / superuser.

    Used for actions that only the event owner (or a platform admin) should
    control: add/remove staff, soft-delete/restore, availability window writes,
    resource writes, permission assignment.
    """

    message = "You must be the event creator or a platform administrator to perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_staff or user.is_superuser:
            return True
        event = _get_event_from_obj(obj)
        if event is None:
            return False
        return event.created_by == user


class IsEventOwnerOrEventStaffOrDjangoStaff(permissions.BasePermission):
    """
    Grants access when the request user is:
      - the event creator, OR
      - an assigned EventStaff member, OR
      - a Django staff / superuser.

    Used for collaborative management actions where existing team members
    should also have write access: staff invite management, ws-token.
    """

    message = "You must be the event owner, an event staff member, or a platform administrator."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_staff or user.is_superuser:
            return True
        event = _get_event_from_obj(obj)
        if event is None:
            return False
        return event.created_by == user or _user_is_event_staff_member(user, event)
    
class StaffInvitePermission(IsEventOwnerOrEventStaffOrDjangoStaff):
    
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
    
    def has_object_permission(self, request, view, obj):
        
        if obj.target_user == request.user:
            return True

        return super().has_object_permission(request, view, obj)

class IsEventAdminOrDjangoStaff(permissions.BasePermission):
    """
    Grants access when the request user is:
      - the event creator, OR
      - a user with an ADMINISTRATIVE EventRole for this event, OR
      - a Django staff / superuser.

    Used for elevated management actions: approve/reject sponsors,
    create/modify/delete sponsorship packages.
    """

    message = "You must be an event administrator or a platform administrator."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_staff or user.is_superuser:
            return True
        event = _get_event_from_obj(obj)
        if event is None:
            return False
        return event.created_by == user or _user_has_administrative_role(user, event)


class CanManageSponsorForOrganisation(permissions.BasePermission):
    """
    Grants access when the request user can act on behalf of the sponsor's
    organisation — i.e. is an event admin OR holds an OrganisationControl
    record for the organisation supplied in the request payload.

    For list-level checks (has_permission) this only verifies authentication;
    the organisation-specific check happens at the object / action level via
    has_object_permission, and for create paths the viewset calls
    ``check_organisation_permission(request, event, organisation)`` directly.
    """

    message = "You don't have permission to manage a sponsor for this organisation."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        """obj is an EventSponsor instance."""
        user = request.user
        if user.is_staff or user.is_superuser:
            return True
        event = getattr(obj, 'event', None)
        if event is None:
            return False
        if event.created_by == user or _user_has_administrative_role(user, event):
            return True
        # Fall back to org-level control
        return OrganisationControl.objects.filter(
            user=user,
            organisation=obj.organisation,
        ).exists()

    @staticmethod
    def user_can_manage_for_organisation(user, event, organisation):
        """
        Helper callable from viewset action logic for create paths where no
        object instance exists yet.
        """
        if user.is_staff or user.is_superuser:
            return True
        if event.created_by == user or _user_has_administrative_role(user, event):
            return True
        from apps.organisations.models import OrganisationControl
        return OrganisationControl.objects.filter(
            user=user,
            organisation=organisation,
        ).exists()


class IsEventOwnerOrStaff(permissions.BasePermission):
    """
    Permission: Event owner or Django staff can manage events.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if hasattr(obj, 'created_by'):
            return obj.created_by == request.user
        
        if hasattr(obj, 'event'):
            return obj.event.created_by == request.user
        
        return False


class IsEventStaffOrReadOnly(permissions.BasePermission):
    """
    Permission: Event staff can modify, others can only read.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if hasattr(obj, 'event'):
            event = obj.event
        elif hasattr(obj, 'created_by'):
            return obj.created_by == request.user
        else:
            event = obj
        
        is_event_staff = event.staff_members.filter(user=request.user).exists()
        is_owner = event.created_by == request.user
        
        return is_event_staff or is_owner


class CanManageEventPermissions(permissions.BasePermission):
    """
    Permission: Only Django staff/superusers can manage event permissions.
    """
    def has_permission(self, request, view):
        return request.user and (request.user.is_staff or request.user.is_superuser)


class CanManageEventStaff(permissions.BasePermission):
    """
    Permission: Event owners and Django staff can manage event staff.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if hasattr(obj, 'event'):
            return obj.event.created_by == request.user
        
        return obj.created_by == request.user


class CanReviewEvent(permissions.BasePermission):
    """
    Permission: Authenticated users can create reviews, only review author can modify.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if hasattr(obj, 'user'):
            return obj.user == request.user
        
        return False


class IsEventOwnerOrStaffMember(permissions.BasePermission):
    """
    Permission: Event owner or assigned event staff member.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if hasattr(obj, 'event'):
            event = obj.event
        else:
            event = obj
        
        is_owner = event.created_by == request.user
        is_event_staff = event.staff_members.filter(user=request.user).exists()
        
        return is_owner or is_event_staff


class CanManageEventInvites(permissions.BasePermission):
    """
    Permission: Event owners and existing event staff can manage invites.
    Target users can view their own invites.
    
    Note: This permission is now deprecated as we handle permissions inline
    in the EventViewSet nested actions. Kept for backward compatibility.
    """
    def has_permission(self, request, view):
        # Anyone authenticated can view invites (filtered by viewset)
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        
        # Only authenticated users can create/update/delete invites
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        # Target user can view their own invite
        if request.method in permissions.SAFE_METHODS:
            if obj.target_user == request.user:
                return True
        
        # Event owner can manage invites
        if obj.event.created_by == request.user:
            return True
        
        # Existing event staff can manage invites
        is_event_staff = obj.event.staff_members.filter(user=request.user).exists()
        
        return is_event_staff


# ============================================================================
# Granular CRUD-based Permission Classes
# ============================================================================


class HasEventPermission(permissions.BasePermission):
    """
    Base permission class for checking EventPermissionAssignment with CRUD flags.
    
    This checks:
    1. Django staff/superuser always have access
    2. Event creator always has access
    3. Users with ADMINISTRATIVE role have full access
    4. Users with specific EventPermissionAssignment for the given category with proper CRUD flags
    
    Logic:
    - If read_only=True, user can only perform SAFE_METHODS (GET, HEAD, OPTIONS)
    - Otherwise, check specific allow_create, allow_update, allow_delete flags
    - Most permissive wins: if role OR permission grants access, allow it
    """
    
    # Subclasses should override this with the permission category to check
    permission_category = None
    
    def has_permission(self, request, view):
        """Check if user has basic permission to access the view."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django staff/superuser always have access
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        # For list views, allow through - object permission will filter
        return True
    
    def has_object_permission(self, request, view, obj):
        """Check if user has permission for specific object with CRUD flags."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django staff/superuser always have access
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        # Get the event from the object
        event = self._get_event_from_object(obj)
        if not event:
            return False
        
        # Event creator always has full access
        if event.created_by == request.user:
            return True
        
        # Check if user has ADMINISTRATIVE role (full access)
        if self._has_administrative_role(request.user, event):
            return True
        
        # Check EventPermissionAssignment with CRUD flags
        return self._check_permission_assignment(request, event)
    
    def _get_event_from_object(self, obj):
        """Extract event from various object types."""
        if hasattr(obj, 'event'):
            return obj.event
        if obj.__class__.__name__ == 'Event':
            return obj
        # Add more extraction logic as needed
        return None
    
    def _has_administrative_role(self, user, event):
        """Check if user has ADMINISTRATIVE role for the event."""
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        
        return EventRoleAssignment.objects.filter(
            user=user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()
    
    def _check_permission_assignment(self, request, event):
        """
        Check EventPermissionAssignment with CRUD flags.
        
        Logic:
        - If read_only=True, only allow SAFE_METHODS
        - Otherwise check specific CRUD flags based on request method
        """
        from apps.events.models import EventPermissionAssignment
        
        if not self.permission_category:
            return False
        
        # Get all permission assignments for this user, event, and category
        assignments = EventPermissionAssignment.objects.filter(
            user=request.user,
            event=event,
            permission__category=self.permission_category
        ).select_related('permission')
        
        if not assignments.exists():
            return False
        
        # Check each assignment - if ANY grants access, allow (most permissive wins)
        for assignment in assignments:
            if self._assignment_grants_access(assignment, request.method):
                return True
        
        return False
    
    def _assignment_grants_access(self, assignment, method):
        """Check if a specific assignment grants access for the given method."""
        # If read_only is True, only allow safe methods
        if assignment.read_only:
            return method in permissions.SAFE_METHODS
        
        # Check specific CRUD flags based on method
        if method in permissions.SAFE_METHODS:
            # For read operations, user needs at least one write permission or implicit read
            return (assignment.allow_create or assignment.allow_update or 
                   assignment.allow_delete)
        elif method == 'POST':
            return assignment.allow_create
        elif method in ['PUT', 'PATCH']:
            return assignment.allow_update
        elif method == 'DELETE':
            return assignment.allow_delete
        
        return False


class HasRegistrationPermission(HasEventPermission):
    """
    Permission for registration/attendee management endpoints.
    Checks for REGISTRATION category permissions.
    """
    permission_category = 'REGISTRATION'


class HasProductManagementPermission(HasEventPermission):
    """
    Permission for product management endpoints.
    Checks for PRODUCT_MANAGEMENT category permissions.
    """
    permission_category = 'PRODUCT_MANAGEMENT'


class HasStaffManagementPermission(HasEventPermission):
    """
    Permission for staff management endpoints.
    Checks for STAFF_MANAGEMENT category permissions.
    """
    permission_category = 'STAFF_MANAGEMENT'


class HasContentManagementPermission(HasEventPermission):
    """
    Permission for content management endpoints (resources, images, etc).
    Checks for CONTENT_MANAGEMENT category permissions.
    """
    permission_category = 'CONTENT_MANAGEMENT'


class HasReportingPermission(HasEventPermission):
    """
    Permission for reporting and analytics endpoints.
    Checks for REPORTING category permissions.
    """
    permission_category = 'REPORTING'


class HasGeneralPermission(HasEventPermission):
    """
    Permission for general event operations.
    Checks for GENERAL category permissions.
    """
    permission_category = 'GENERAL'


class CannotTargetEventCreator(permissions.BasePermission):
    """
    Prevents write operations on assignment objects that target the event's creator.
    Applies to EventStaff, EventPermissionAssignment, and EventRoleAssignment.
    Safe methods are always allowed.
    """
    message = "Event creator access is immutable"

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        # For create/update payloads, block when target user is event creator.
        target_user_id = request.data.get('user')
        if target_user_id in (None, ''):
            return True

        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            return True

        event = None

        # Update/partial update/destroy paths can resolve event from instance.
        if getattr(view, 'action', None) in ('update', 'partial_update', 'destroy'):
            try:
                instance = view.get_object()
                event = getattr(instance, 'event', None)
            except Exception:
                event = None

        # Create paths should resolve event from payload.
        if event is None and request.data.get('event'):
            from apps.events.models import Event

            event_identifier = request.data.get('event')
            event = Event.objects.filter(event_id=event_identifier).first()
            if event is None:
                event = Event.objects.filter(url_safe_title=event_identifier).first()

        if event and target_user_id == event.created_by_id:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        user_id = getattr(obj, 'user_id', None)
        event = getattr(obj, 'event', None)
        if user_id and event and user_id == event.created_by_id:
            return False
        return True


class CanManageEventVenueFloorPlans(permissions.BasePermission):
    """
    Grants authenticated event staff / owners full access to floor plans
    that are scoped to an EventVenue.  Django staff / superusers always have
    full access.

    Reads and writes are both guarded: the caller must be authenticated and
    must be either the event owner or a staff member of the event that owns
    the referenced EventVenue.
    """

    message = "You must be the event owner or event staff to manage floor plans for this venue."

    def _has_event_venue_access(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            return True
        event_venue_pk = view.kwargs.get("event_venue_pk")
        if not event_venue_pk:
            return False
        from apps.events.models import EventVenue
        try:
            ev = EventVenue.objects.select_related("event").get(
                event_venue_id=event_venue_pk
            )
        except EventVenue.DoesNotExist:
            return False
        event = ev.event
        return (
            event.created_by == request.user
            or event.staff_members.filter(user=request.user).exists()
        )

    def has_permission(self, request, view) -> bool:
        return self._has_event_venue_access(request, view)

    def has_object_permission(self, request, view, obj) -> bool:
        return self._has_event_venue_access(request, view)
