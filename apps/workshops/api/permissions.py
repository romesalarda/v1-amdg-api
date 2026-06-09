from rest_framework import permissions


def _get_event(obj):
    """Resolve the event from a workshop-related model instance."""
    if hasattr(obj, 'event'):
        return obj.event
    if hasattr(obj, 'workshop'):
        return obj.workshop.event
    if hasattr(obj, 'submission'):
        return obj.submission.event
    return None


def _is_event_staff_or_owner(user, event):
    """Return True if user is the event creator or an assigned event staff member."""
    if not event:
        return False
    if event.created_by_id == user.pk:
        return True
    return event.staff_members.filter(user=user).exists()


class IsWorkshopEventStaffOrReadOnly(permissions.BasePermission):
    """
    Safe methods (GET, HEAD, OPTIONS) are allowed for any authenticated user.
    Write methods require the requesting user to be the event owner or an
    event staff member of the workshop's parent event.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff or request.user.is_superuser:
            return True
        event = _get_event(obj)
        return _is_event_staff_or_owner(request.user, event)


class IsWorkshopEventStaff(permissions.BasePermission):
    """
    Only the event owner or an assigned event staff member may access this resource.
    Applies to both safe and unsafe methods (e.g. admin-only list endpoints).
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        event = _get_event(obj)
        return _is_event_staff_or_owner(request.user, event)


class CanManageWorkshopAllocations(permissions.BasePermission):
    """
    Only Django staff/superusers or the event owner/staff may trigger allocation actions.
    Used on custom viewset actions (run_allocation, confirm, promote_from_waitlist, etc.).
    """

    message = "Only event staff may manage workshop allocations."

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        event = _get_event(obj)
        return _is_event_staff_or_owner(request.user, event)
