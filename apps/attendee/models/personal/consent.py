from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
User = get_user_model()

class Consent(models.Model):
    
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='consents')
    code = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField()
    external_link = models.URLField(null=True, blank=True)
    
    version = models.CharField(max_length=10, default='1.0')
    required = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    defined_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='defined_consents', null=True, blank=True)

    def __str__(self):
        return f"{self.title} ({self.code}) - Event: {self.event.title if self.event else 'N/A'}"
    
    def __repr__(self):
        return f"<Consent {self.code} for Event {self.event.id if self.event else 'N/A'}>"
    
    def save(self, *args, **kwargs):

        super().save(*args, **kwargs)
    
    def clean(self):
        # validate version is in format X.Y where X and Y are integers
        import re
        version_pattern = r'^\d+\.\d+$'
        if not re.match(version_pattern, self.version):
            raise ValidationError({'version': 'Version must be in format X.Y where X and Y are integers.'})
        
class AttendeeConsent(models.Model): # m2m through model
    
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='consents')
    consent = models.ForeignKey(Consent, on_delete=models.CASCADE, related_name='event_consents')
    consent_given = models.BooleanField(default=False)    
    given_at = models.DateTimeField(null=True, blank=True) # time when consent was given if any
    given_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='given_event_consents', null=True, blank=True)
    
    recorded_at = models.DateTimeField(auto_now_add=True) # time when this record was created - on registration
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='recorded_event_consents', null=True, blank=True)  
    
    class Meta:
        unique_together = ('attendee', 'consent')
    
    def __str__(self):
        return f"Consent {self.consent.code} for Event {self.attendee.event.id}"