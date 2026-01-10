"""
Production-grade permissions for the bookings app.

Provides comprehensive permission classes for booking management with
support for event-based ADMINISTRATIVE roles, Django staff, superusers,
and booking ownership.

Permission Classes:
    - IsAdministrativeStaff: Checks for ADMINISTRATIVE event role, staff, or superuser
    - IsBookingOwner: Checks if user owns/created the booking
    - IsBookingOwnerOrAdministrative: Combined permission for booking operations
    - IsReadOnly: Read-only access for safe methods
    - IsTicketOwnerOrAdministrative: Permission for ticket operations

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import permissions
from django.contrib.auth import get_user_model
from typing import Any, Optional

from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices

User = get_user_model()


class IsAdministrativeStaff(permissions.BasePermission):
    """
    Permission class to check if user has administrative access.
    
    Grants access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    3. Has EventRoleAssignment with ADMINISTRATIVE category role for the relevant event
    
    This permission should be used for operations that require administrative oversight
    such as viewing all bookings, managing ticket types, or configuring booking packages.
    """
    
    message = "You must be an administrator, staff member, or have an administrative event role to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has administrative privileges."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # For actions without objects (like create), check if user has ANY administrative role
        # This prevents non-admin users from creating resources
        has_any_admin_role = EventRoleAssignment.objects.filter(
            user=request.user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()
        
        if has_any_admin_role:
            return True
        
        # If no admin role, deny access
        return False
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user has administrative privileges for the specific object."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Get the event from the object
        event = self._get_event_from_object(obj)
        if not event:
            return False
        
        # Check if user has an ADMINISTRATIVE role for this event
        return self._user_has_administrative_role(request.user, event)
    
    def _get_event_from_object(self, obj) -> Any:
        """Extract the event from various object types."""
        # Direct event attribute
        if hasattr(obj, 'event'):
            return obj.event
        
        # Through booking
        if hasattr(obj, 'booking') and obj.booking:
            return obj.booking.event
        
        # Through attendee
        if hasattr(obj, 'attendee') and obj.attendee:
            return obj.attendee.event
        
        # Through ticket_type
        if hasattr(obj, 'ticket_type') and obj.ticket_type:
            return obj.ticket_type.event
        
        # Through booking_package
        if hasattr(obj, 'booking_package') and obj.booking_package:
            return obj.booking_package.event
        
        return None
    
    def _user_has_administrative_role(self, user, event) -> bool:
        """Check if user has an ADMINISTRATIVE role for the given event."""
        return EventRoleAssignment.objects.filter(
            user=user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()


class IsBookingOwner(permissions.BasePermission):
    """
    Permission class to check if user owns/created the booking.
    
    Grants access if:
    1. User is the booking creator (made_by field)
    2. User is associated with an attendee in the booking
    """
    
    message = "You must be the booking owner to perform this action."
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user owns the booking or related object."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Get the booking from the object
        booking = self._get_booking_from_object(obj)
        if not booking:
            return False
        
        # Check if user created the booking
        if booking.made_by and booking.made_by == request.user:
            return True
        
        # Check if user is associated with any attendee in the booking
        if booking.attendees.filter(user=request.user).exists():
            return True
        
        return False
    
    def _get_booking_from_object(self, obj) -> Any:
        """Extract the booking from various object types."""
        from apps.bookings.models import Booking
        
        # Direct booking object
        if isinstance(obj, Booking):
            return obj
        
        # Direct booking attribute
        if hasattr(obj, 'booking'):
            return obj.booking
        
        # Through attendee
        if hasattr(obj, 'attendee') and obj.attendee and hasattr(obj.attendee, 'booking'):
            return obj.attendee.booking
        
        return None


class IsBookingOwnerOrAdministrative(permissions.BasePermission):
    """
    Combined permission checking both booking ownership and administrative access.
    
    This is the primary permission class for booking-related operations.
    Grants access if user is EITHER:
    1. The booking owner (created it or is an attendee)
    2. Has administrative privileges (superuser, staff, or ADMINISTRATIVE event role)
    """
    
    message = "You must be the booking owner or have administrative access to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check basic authentication and allow through to object-level check."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # For list views, filter will be applied in viewset
        return True
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user is owner or has administrative access."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check administrative access first
        admin_perm = IsAdministrativeStaff()
        if admin_perm.has_object_permission(request, view, obj):
            return True
        
        # Check booking ownership
        owner_perm = IsBookingOwner()
        if owner_perm.has_object_permission(request, view, obj):
            return True
        
        return False


class IsTicketOwnerOrAdministrative(permissions.BasePermission):
    """
    Permission for ticket operations.
    
    Grants access if user is:
    1. The attendee who owns the ticket
    2. The booking creator
    3. Has administrative privileges
    """
    
    message = "You must be the ticket owner or have administrative access to perform this action."
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user can access the ticket."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check administrative access
        admin_perm = IsAdministrativeStaff()
        if admin_perm.has_object_permission(request, view, obj):
            return True
        
        # Check if user is the attendee
        if hasattr(obj, 'attendee') and obj.attendee:
            if obj.attendee.user and obj.attendee.user == request.user:
                return True
        
        # Check if user created the booking
        if hasattr(obj, 'attendee') and obj.attendee and obj.attendee.booking:
            booking = obj.attendee.booking
            if booking.made_by and booking.made_by == request.user:
                return True
        
        return False


class IsReadOnly(permissions.BasePermission):
    """
    Permission class that grants read-only access for safe methods.
    
    Allows GET, HEAD, OPTIONS requests for all authenticated users.
    Useful for reference data endpoints like ticket types.
    """
    
    def has_permission(self, request, view) -> bool:
        """Allow safe methods for authenticated users."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.method in permissions.SAFE_METHODS


class IsAdministrativeStaffOnly(permissions.BasePermission):
    """
    Strict administrative-only permission.
    
    Only allows access to superusers, staff, or users with ADMINISTRATIVE event roles.
    Used for sensitive endpoints like alternative sign-in identifiers.
    """
    
    message = "This action is restricted to administrative staff only."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has administrative privileges."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user has ANY administrative role
        has_admin_role = EventRoleAssignment.objects.filter(
            user=request.user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()
        
        return has_admin_role
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user has administrative privileges for the specific object."""
        admin_perm = IsAdministrativeStaff()
        return admin_perm.has_object_permission(request, view, obj)
