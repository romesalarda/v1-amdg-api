from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class EventStaff(models.Model):
    
    staff_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='staff_members')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='event_staff', null=True)
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='event_staff_assigned')
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        unique_together = ('event', 'user')
        ordering = ['-assigned_at']
        
class EventStaffAvailability(models.Model):
    '''
    Model representing the availability of event staff members.
    '''
    staff = models.ForeignKey(EventStaff, on_delete=models.CASCADE, related_name='availabilities')
    available_from = models.DateTimeField()
    available_to = models.DateTimeField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def validate_availability(self):
        if self.available_from >= self.available_to:
            raise ValueError("available_from must be earlier than available_to")