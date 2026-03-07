"""
Permission classes for the attendee app.

Provides granular access control for attendee resources based on user roles,
ownership, and guardian relationships.
"""
from rest_framework import permissions
from apps.attendee.models import AttendeeGuardian


class IsAttendeeOwnerOrStaff(permissions.BasePermission):
    """
    Permission to allow attendee owners, guardians, or event staff to access/modify attendee data.
    
    - Attendees with 'self' relationship can access their own data
    - Guardians can access their guarded attendees
    - Event staff can access all attendees for their events
    - Superusers can access all
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):

        if request.user.is_anonymous:
            return False
        # Superusers have full access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user is the attendee (self relationship)
        if hasattr(obj, 'user') and obj.user == request.user:
            return True
        
        # Check if user is a guardian of this attendee
        if hasattr(obj, 'attendee_id'):  # obj is an Attendee
            if AttendeeGuardian.objects.filter(
                attendee=obj,
                user=request.user
            ).exists():
                return True
        
        # Check if user is event staff for the attendee's event
        if hasattr(obj, 'event') and obj.event:
            from apps.events.models import EventStaff
            if EventStaff.objects.filter(
                event=obj.event,
                user=request.user
            ).exists():
                return True
        
        # Read-only for safe methods, deny write methods
        return request.method in permissions.SAFE_METHODS and False


class IsAttendeeOwnerOrReadOnly(permissions.BasePermission):
    """
    Permission to allow attendee owners to modify their data, others can only read.
    """
    
    def has_object_permission(self, request, view, obj):
        # Allow read permissions for any request
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Superusers have full access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Write permissions only for the owner
        if hasattr(obj, 'user') and obj.user == request.user:
            return True
        
        # Check if user is a guardian
        if hasattr(obj, 'attendee_id'):
            if AttendeeGuardian.objects.filter(
                attendee=obj,
                user=request.user
            ).exists():
                return True
        
        return False


class IsEventStaffOrReadOnly(permissions.BasePermission):
    """
    Permission to allow event staff to modify event-related data, others can only read.
    """
    
    def has_permission(self, request, view):
        # Allow read permissions for authenticated users
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        
        # Write permissions require authentication
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        
        from apps.attendee.models import Attendee
        # Allow read permissions for authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Superusers have full access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user is event staff

        if not hasattr(obj, 'event') and hasattr(obj, 'attendee'):
            if isinstance(obj.attendee, Attendee) and obj.attendee.event:
                obj.event = obj.attendee.event

        if hasattr(obj, 'event') and obj.event:
            from apps.events.models import EventStaff
            if EventStaff.objects.filter(
                event=obj.event,
                user=request.user
            ).exists():
                return True
        

        return False

class IsGuardianOrStaff(permissions.BasePermission):
    """
    Permission for guardian-specific actions.
    """
    
    def has_object_permission(self, request, view, obj):
        # Superusers and staff have full access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user is the guardian in the relationship
        if hasattr(obj, 'user') and obj.user == request.user:
            return True
        
        return False


class CanManageAttendeePersonalInfo(permissions.BasePermission):
    """
    Permission to manage personal information (medical, dietary, accessibility, etc.).
    
    - Attendee owners can manage their own info
    - Guardians can manage guarded attendees' info
    - Event staff can manage info for attendees in their events
    """
    
    def has_permission(self, request, view):
        # Require authentication
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Superusers and staff have full access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Get the attendee from the personal info object
        attendee = getattr(obj, 'attendee', None)
        if not attendee:
            return False
        
        # Check if user is the attendee
        if attendee.user == request.user:
            return True
        
        # Check if user is a guardian
        if AttendeeGuardian.objects.filter(
            attendee=attendee,
            user=request.user
        ).exists():
            return True
        
        # Check if user is event staff
        if attendee.event:
            from apps.events.models import EventStaff
            if EventStaff.objects.filter(
                event=attendee.event,
                user=request.user
            ).exists():
                return True
        
        return False


class CanAccessMessages(permissions.BasePermission):
    """
    Permission to access attendee messages.
    
    - Message sender can view/edit their message
    - Event staff can view/respond to messages
    - Superusers/staff have full access
    """
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Superusers and staff have full access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user is the attendee who sent the message
        if hasattr(obj, 'attendee') and obj.attendee:
            if obj.attendee.user == request.user:
                return True
            
            # Check if user is a guardian of the attendee
            if AttendeeGuardian.objects.filter(
                attendee=obj.attendee,
                user=request.user
            ).exists():
                return True
            
            # Check if user is event staff
            if obj.attendee.event:
                from apps.events.models import EventStaff
                if EventStaff.objects.filter(
                    event=obj.attendee.event,
                    user=request.user
                ).exists():
                    return True
        
        return False


class IsStaffOrReadOnly(permissions.BasePermission):
    """
    Permission that allows staff to edit, others can only read.
    """
    
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        
        return request.user and (request.user.is_staff or request.user.is_superuser)
    
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        
        return request.user and (request.user.is_staff or request.user.is_superuser)
