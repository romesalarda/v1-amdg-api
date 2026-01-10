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
