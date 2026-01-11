"""
Production-grade permissions for the locations app.

Provides comprehensive permission classes for location management with
support for Django staff, superusers, and location-specific managers.

Permission Classes:
    - IsAdministrativeStaffOrReadOnly: Read-only for all, write for staff
    - IsLocationManager: Checks if user manages the location or is staff
    - IsVenueOwnerOrReadOnly: Venue owner or read-only access

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import permissions
from django.contrib.auth import get_user_model
from typing import Any

User = get_user_model()


class IsAdministrativeStaffOrReadOnly(permissions.BasePermission):
    """
    Permission class for read-only access to all, write access to administrative staff.
    
    Grants write access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    
    All users (including unauthenticated) have read-only access.
    """
    
    message = "You must be an administrative staff member to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has permission at the request level."""
        # Read-only access for all
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write access only for authenticated staff
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.is_superuser or request.user.is_staff
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user has permission at the object level."""
        # Read-only access for all
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write access only for authenticated staff
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.is_superuser or request.user.is_staff


class IsLocationManager(permissions.BasePermission):
    """
    Permission class to check if user is a location manager or administrative staff.
    
    Grants access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    3. Leader for the specific location
    
    This is used for operations that require location-level management.
    """
    
    message = "You must be a location manager or administrative staff to perform this action."
    
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
        """Check if user is a location manager."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user is a leader for this location
        from django.contrib.contenttypes.models import ContentType
        from apps.organisations.models import Leader
        from apps.locations.models import (
            CountryLocation, ClusterLocation, ChapterLocation, AreaLocation
        )
        
        # Determine the location object
        location = self._get_location_from_object(obj)
        if not location:
            return False
        
        # Get ContentType for the location
        ct = ContentType.objects.get_for_model(location)
        
        # Check if user is a leader for this location
        return Leader.objects.filter(
            target_type=ct,
            target_id=location.id,
            user=request.user
        ).exists()
    
    def _get_location_from_object(self, obj) -> Any:
        """Extract the location from various object types."""
        from apps.locations.models import (
            CountryLocation, ClusterLocation, ChapterLocation, AreaLocation
        )
        
        # Direct location models
        if isinstance(obj, (CountryLocation, ClusterLocation, ChapterLocation, AreaLocation)):
            return obj
        
        return None


class IsVenueOwnerOrReadOnly(permissions.BasePermission):
    """
    Permission class for venue-related models.
    
    Grants write access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    3. User who added/created the object
    
    All users have read-only access.
    """
    
    message = "You must be the venue owner, creator, or administrative staff to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has permission at the request level."""
        # Read-only access for all
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write access requires authentication
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check if user is the owner or staff."""
        # Read-only access for all
        if request.method in permissions.SAFE_METHODS:
            return True
        
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check if user is the creator/owner
        if hasattr(obj, 'added_by') and obj.added_by == request.user:
            return True
        if hasattr(obj, 'created_by') and obj.created_by == request.user:
            return True
        
        # For venue-related objects, check if user owns the parent venue
        if hasattr(obj, 'venue') and hasattr(obj.venue, 'added_by'):
            if obj.venue.added_by == request.user:
                return True
        
        return False


class IsReadOnly(permissions.BasePermission):
    """
    Permission class that only allows read-only operations.
    Useful for combining with other permissions using OR logic.
    """
    
    def has_permission(self, request, view) -> bool:
        """Allow only safe methods."""
        return request.method in permissions.SAFE_METHODS
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Allow only safe methods."""
        return request.method in permissions.SAFE_METHODS
