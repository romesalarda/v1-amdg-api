from django.db import models
from django.contrib.auth import get_user_model

from apps.payments.mixins import PayableModel
from apps.common.models import RequiresVerificationModel
from apps.locations.models import ChapterLocation

import uuid

User = get_user_model()

class EventSponsor(RequiresVerificationModel):
    '''
    Represents an organisation sponsoring an event, with details about the sponsorship package and location.
    '''
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    organisation = models.ForeignKey('organisations.Organisation', on_delete=models.CASCADE, related_name='sponsored_events')
    package = models.ForeignKey('organisations.EventSponsorPackage', on_delete=models.SET_NULL, related_name='sponsors', null=True, blank=True)
    chapter_location = models.ForeignKey(ChapterLocation, on_delete=models.SET_NULL, null=True, related_name='sponsors', blank=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='sponsors')
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='event_sponsors_added', null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('event', 'organisation', 'chapter_location', 'package')
        verbose_name = "Event Sponsor"
        verbose_name_plural = "Event Sponsors"
    
    def __str__(self):
        return self.name
    
class EventSponsorPackage(PayableModel):
    '''
    Represents a sponsorship package for an event, detailing the benefits and requirements for sponsors.
    '''
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='sponsorship_packages')
    package_name = models.CharField(max_length=200)
    package_description = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)
    tier = models.PositiveIntegerField(help_text="Sponsorship tier (e.g., 1 for Gold, 2 for Silver, etc.)", default=1)
        
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('event', 'package_name')
        ordering = ['tier']
        verbose_name = "Event Sponsor Package"
        verbose_name_plural = "Event Sponsor Packages"
    
    def __str__(self):
        return f"{self.package_name} - {self.event.title}"