from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class EventPermissionCategoryChoices(models.TextChoices):
    GENERAL = 'GENERAL', 'General Permissions'
    REGISTRATION = 'REGISTRATION', 'Registration Permissions'
    PRODUCT_MANAGEMENT = 'PRODUCT_MANAGEMENT', 'Product Management Permissions'
    CONTENT_MANAGEMENT = 'CONTENT_MANAGEMENT', 'Content Management Permissions'
    STAFF_MANAGEMENT = 'STAFF_MANAGEMENT', 'Staff Management Permissions'
    PAYMENT_MANAGEMENT = 'PAYMENT_MANAGEMENT', 'Payment Management Permissions'
    BOOKING_MANAGEMENT = 'BOOKING_MANAGEMENT', 'Booking Management Permissions'
    RESOURCE_MANAGEMENT = 'RESOURCE_MANAGEMENT', 'Resource Management Permissions'
    REPORTING = 'REPORTING', 'Reporting Permissions'

class EventPermission(models.Model):
    '''
    Model representing specific permissions related to events.

    If an endpoint requires a permission and it is not assigned, it is assumed that the user does not have that permission.
    '''
    permission_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    
    category = models.CharField(
        max_length=30, 
        choices=EventPermissionCategoryChoices.choices, 
        default=EventPermissionCategoryChoices.GENERAL
        )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<EventPermission name={self.name}, code={self.code}>"
        
class EventPermissionAssignment(models.Model):
    '''
    Model representing the assignment of permissions to users for specific events.
    '''
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='permission_assignments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_permissions')
    permission = models.ForeignKey(EventPermission, on_delete=models.CASCADE, related_name='assignments')
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='event_permission_assigned_by')

    read_only = models.BooleanField(default=False) # Whether this permission permits read only
    allow_update = models.BooleanField(default=False) # Whether this permission allows updating resources
    allow_delete = models.BooleanField(default=False) # Whether this permission allows deleting resources
    allow_create = models.BooleanField(default=False) # Whether this permission allows creating resources

    def __str__(self):
        return f"{self.user.username} - {self.permission.name} for {self.event.display_identifier}"
    
    def __repr__(self):
        return f"<EventPermissionAssignment user={self.user.username}, permission={self.permission.name}, event={self.event.display_identifier}>"
    
    class Meta:
        unique_together = ('event', 'user', 'permission')
        verbose_name = 'Event Permission Assignment'
        verbose_name_plural = 'Event Permission Assignments'

    @property
    def has_full_access(self):
        return not self.read_only and self.allow_update and self.allow_delete and self.allow_create
