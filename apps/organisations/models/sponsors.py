from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.payments.mixins import PayableModel
from apps.common.models import RequiresVerificationModel
from apps.locations.models import ChapterLocation, AreaLocation

import uuid

User = get_user_model()

class EventSponsor(RequiresVerificationModel):
    '''
    Represents an organisation sponsoring an event, with details about the sponsorship package and location.
    '''
    sponsor_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=('event', 'organisation', 'chapter_location'),
                name='unique_event_sponsor_per_org_location',
            ),
        ]
        verbose_name = "Event Sponsor"
        verbose_name_plural = "Event Sponsors"

    def clean(self):
        if self.package and self.package.event_id != self.event_id:
            raise ValidationError({
                'package': "Selected package must belong to the same event as the sponsor.",
            })
    
    def __str__(self):
        return self.name
    
class EventSponsorPackage(PayableModel):
    '''
    Represents a sponsorship package for an event, detailing the benefits and requirements for sponsors.
    '''
    package_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='sponsorship_packages')
    package_name = models.CharField(max_length=200)
    package_description = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)
    tier = models.PositiveIntegerField(help_text="Sponsorship tier (e.g., 1 for Gold, 2 for Silver, etc.)", default=1)
        
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('event', 'package_name'),
                name='unique_sponsor_package_name_per_event',
            ),
            models.UniqueConstraint(
                fields=('event', 'tier'),
                name='unique_sponsor_package_tier_per_event',
            ),
        ]
        ordering = ['tier']
        verbose_name = "Event Sponsor Package"
        verbose_name_plural = "Event Sponsor Packages"
    
    def __str__(self):
        return f"{self.package_name} - {self.event.title}"
    
class EventSponsorInvite(models.Model):
    '''
    Represents an invitation sent to a potential sponsor for an event, allowing them to accept or decline the sponsorship opportunity.
    '''
    invite_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='sponsor_invites')
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    organisation = models.ForeignKey('organisations.Organisation', on_delete=models.SET_NULL, related_name='sponsor_invites', null=True, blank=True)
    chapter_location = models.ForeignKey(ChapterLocation, on_delete=models.SET_NULL, null=True, related_name='sponsor_invites', blank=True)
    accepted = models.BooleanField(default=False)
    declined = models.BooleanField(default=False)
    
    sent_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('event', 'email'),
                name='unique_sponsor_invite_per_event_email',
            ),
        ]
        verbose_name = "Event Sponsor Invite"
        verbose_name_plural = "Event Sponsor Invites"

    def __str__(self):
        return f"Invite for {self.email} to sponsor {self.event.title}"