from django.db import models
from django.contrib.auth import get_user_model

import uuid
User = get_user_model()

class AttendeeOrganisation(models.Model):
    
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='organisations')
    organisation = models.ForeignKey('organisations.Organisation', on_delete=models.CASCADE, related_name='attendees')
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='attendee_organisations_added')
    
    class Meta:
        unique_together = ('attendee', 'organisation')
    
    def __str__(self):
        return f"{self.attendee.first_name} {self.attendee.last_name} - {self.organisation.title}"
    
    def __repr__(self):
        return super().__repr__()