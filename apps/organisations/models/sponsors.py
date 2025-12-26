from django.db import models
from django.contrib.auth import get_user_model

from apps.payments.mixins import PayableModel

User = get_user_model()

class EventSponsor(models.Model):
    
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    organisation = models.ForeignKey('organisations.Organisation', on_delete=models.CASCADE, related_name='sponsored_events')
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='sponsors')
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='event_sponsors_added', null=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
class EventSponsorPackage(PayableModel):
    
    sponsor = models.ForeignKey(EventSponsor, on_delete=models.CASCADE, related_name='sponsorship_packages')
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='sponsorship_packages')
    package_name = models.CharField(max_length=200)
    package_description = models.TextField(blank=True, null=True)
        
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.package_name} - {self.sponsor.name}"