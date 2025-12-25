from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class EventRoleCategoryChoices(models.TextChoices):
    ADMINISTRATIVE = 'ADMINISTRATIVE', 'Administrative Roles'
    VOLUNTEER = 'VOLUNTEER', 'Volunteer Roles'
    SPEAKER = 'SPEAKER', 'Speaker Roles'
    COORDINATOR = 'COORDINATOR', 'Coordinator Roles'
    SUPPORT_STAFF = 'SUPPORT_STAFF', 'Support Staff Roles'

class EventRole(models.Model):
    '''
    Model representing roles that can be assigned to users for events.
    '''
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    code = models.CharField(max_length=10, unique=True)
    
    category = models.CharField(
        max_length=20,
        choices=EventRoleCategoryChoices.choices,
        default=EventRoleCategoryChoices.VOLUNTEER
        )   
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
class EventRoleAssignment(models.Model):
    '''
    Model representing the assignment of roles to users for specific events.
    '''
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='role_assignments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_roles')
    role = models.ForeignKey(EventRole, on_delete=models.CASCADE, related_name='assignments')
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='event_role_assigned_by')
    
    class Meta:
        unique_together = ('event', 'user', 'role')
        
    def __str__(self):
        return f"{self.user.username} - {self.role.name} for {self.event.display_identifier}"
    
    def __repr__(self):
        return f"<EventRoleAssignment user={self.user.username}, role={self.role.name}, event={self.event.display_identifier}>"