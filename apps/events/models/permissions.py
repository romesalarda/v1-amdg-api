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
    REPORTING = 'REPORTING', 'Reporting Permissions'

class EventPermmission(models.Model):
    '''
    Model representing specific permissions related to events.
    '''
    permission_id = models.UUIDField(default=uuid.uuid4, editable=False)
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
    
    def __str__(self):
        return self.name
    
class EventPermissionAssignment(models.Model):
    '''
    Model representing the assignment of permissions to users for specific events.
    '''
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='permission_assignments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_permissions')
    permission = models.ForeignKey(EventPermmission, on_delete=models.CASCADE, related_name='assignments')
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='event_permission_assigned_by')