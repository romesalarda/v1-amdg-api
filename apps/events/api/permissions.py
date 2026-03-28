from rest_framework import permissions


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
