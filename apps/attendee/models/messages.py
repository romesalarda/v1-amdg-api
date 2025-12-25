from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class AttendeeMessagePriority(models.TextChoices):
    LOW = 'low', 'Low'
    MEDIUM = 'medium', 'Medium'
    HIGH = 'high', 'High'
    
class AttendeeMessage(models.Model):
    
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.SET_NULL, null=True, related_name='messages')
    subject = models.CharField(max_length=255)
    message = models.TextField()
    admin_notes = models.TextField(blank=True, null=True)
    
    response = models.TextField(blank=True, null=True)
    responsed_at = models.DateTimeField(blank=True, null=True)
    responsed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='message_responses')
    submitted_at = models.DateTimeField(auto_now_add=True)
    
    sent_at = models.DateTimeField(auto_now_add=True)
    
    priority = models.CharField(max_length=10, 
                                choices=AttendeeMessagePriority.choices, 
                                default=AttendeeMessagePriority.MEDIUM
                                )

    def __str__(self):
        return f"Message to {self.attendee} at {self.sent_at}"