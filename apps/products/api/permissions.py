"""
Production-grade permissions for the products app.

Provides comprehensive permission classes for product management with
support for event-based ADMINISTRATIVE roles, Django staff, superusers,
and order ownership.

Permission Classes:
    - IsAdministrativeStaff: Checks for ADMINISTRATIVE event role, staff, or superuser
    - IsAdministrativeStaffOnly: Administrative access only (no owner bypass)
    - IsOrderOwnerOrAdministrative: Combined permission for order operations
    - IsReadOnly: Read-only access for safe methods
    - CanManageProducts: Permission for product/variant management

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import permissions
from django.contrib.auth import get_user_model
from typing import Any

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
    such as viewing all products, managing inventory, or processing orders.
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
        
        # Through product
        if hasattr(obj, 'product') and obj.product:
            return obj.product.event
        
        # Through order
        if hasattr(obj, 'order') and obj.order:
            if obj.order.attendee:
                return obj.order.attendee.event
        
        # Through attendee
        if hasattr(obj, 'attendee') and obj.attendee:
            return obj.attendee.event
        
        return None
    
    def _user_has_administrative_role(self, user, event) -> bool:
        """Check if user has administrative role for the event."""
        return EventRoleAssignment.objects.filter(
            user=user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()


class IsAdministrativeStaffOnly(permissions.BasePermission):
    """
    Strict administrative permission - no owner bypass.
    
    Only grants access to:
    1. Django superusers
    2. Django staff
    3. Users with ADMINISTRATIVE event role
    
    Use for critical operations like stock management, bulk actions.
    """
    
    message = "Only administrators and staff can perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has administrative privileges."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check for any administrative role
        return EventRoleAssignment.objects.filter(
            user=request.user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user has administrative privileges for the specific object."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Get the event and check for administrative role
        event = IsAdministrativeStaff()._get_event_from_object(obj)
        if not event:
            return False
        
        return EventRoleAssignment.objects.filter(
            user=request.user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()


class IsOrderOwner(permissions.BasePermission):
    """
    Permission to check if user owns the order.
    
    Grants access if:
    1. User is the customer on the order
    2. User is the user associated with the order's attendee
    """
    
    message = "You do not have permission to access this order."
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user owns the order."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if user is the customer
        if obj.customer and obj.customer.id == request.user.id:
            return True
        
        # Check if user is associated with the attendee
        if obj.attendee and hasattr(obj.attendee, 'user') and obj.attendee.user.id == request.user.id:
            return True
        
        return False


class IsOrderOwnerOrAdministrative(permissions.BasePermission):
    """
    Combined permission: order owner OR administrative staff.
    
    Used for order viewing, updating, and cancellation operations where
    both order owners and administrators should have access.
    """
    
    message = "You must be the order owner, administrator, or have administrative event role."
    
    def has_permission(self, request, view) -> bool:
        """Basic authentication check and admin permission."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Admins always pass
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # For list/create, allow authenticated users
        if view.action in ['list', 'create']:
            return True
        
        # For object-specific actions, will be checked in has_object_permission
        return True
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user is owner or has administrative access."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if user is owner
        is_owner = IsOrderOwner().has_object_permission(request, view, obj)
        if is_owner:
            return True
        
        # Check if user has administrative access
        is_admin = IsAdministrativeStaff().has_object_permission(request, view, obj)
        if is_admin:
            return True
        
        return False


class IsReadOnly(permissions.BasePermission):
    """
    Permission that grants read-only access.
    
    Allows GET, HEAD, OPTIONS methods only.
    """
    
    message = "You only have read-only access."
    
    def has_permission(self, request, view) -> bool:
        """Check if request is a safe method."""
        return request.method in permissions.SAFE_METHODS
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if request is a safe method."""
        return request.method in permissions.SAFE_METHODS


class CanManageProducts(permissions.BasePermission):
    """
    Permission for product and variant management.
    
    Grants access for:
    - Read operations: Any authenticated user
    - Write operations: Administrative staff only
    """
    
    message = "You must have administrative access to manage products."
    
    def has_permission(self, request, view) -> bool:
        """Check permission based on request method."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Read access for all authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write access requires admin
        return IsAdministrativeStaff().has_permission(request, view)
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check object-level permission."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Read access for all authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write access requires admin
        return IsAdministrativeStaff().has_object_permission(request, view, obj)


class CanManageCategories(permissions.BasePermission):
    """
    Permission for category management.
    
    Categories are global, so only superusers and staff can manage them.
    Event categories can be managed by event administrators.
    """
    
    message = "You must be an administrator to manage categories."
    
    def has_permission(self, request, view) -> bool:
        """Check permission for category operations."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Read access for all authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write access to global categories requires superuser or staff
        if view.basename == 'productcategory':
            return request.user.is_superuser or request.user.is_staff
        
        # Event categories can be managed by event admins
        if view.basename == 'eventproductcategory':
            return IsAdministrativeStaff().has_permission(request, view)
        
        return False
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check object-level permission."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Read access for all authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write access to global categories requires superuser or staff
        if isinstance(obj, ProductCategory):
            return request.user.is_superuser or request.user.is_staff
        
        # Event categories can be managed by event admins
        return IsAdministrativeStaff().has_object_permission(request, view, obj)


# Import ProductCategory here to avoid circular imports
from apps.products.models import ProductCategory
