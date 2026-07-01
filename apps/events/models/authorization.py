from django.db import models
from django.contrib.auth import get_user_model


import uuid
User = get_user_model()

class EventAuthorizationStatusChoices(models.TextChoices):
    PENDING = 'PENDING', 'Pending Review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    POSTPONED = 'POSTPONED', 'Postponed'
    CANCELLED = 'CANCELLED', 'Cancelled'

class EventAuthorization(models.Model):

    OPEN_STATUS_CHOICES = [
        EventAuthorizationStatusChoices.APPROVED,
    ]
    
    CLOSED_STATUS_CHOICES = [
        EventAuthorizationStatusChoices.REJECTED,
        EventAuthorizationStatusChoices.POSTPONED,
        EventAuthorizationStatusChoices.CANCELLED,
        EventAuthorizationStatusChoices.PENDING,
    ]

    review_id = models.UUIDField(default=uuid.uuid4, editable=False) # url usage
    review_code = models.CharField(max_length=30, unique=True, blank=True, null=True) # used for reference
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='authorizations')
    
    reviewed_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_authorizations')
    reviewed_at = models.DateTimeField(auto_now_add=True)
    
    status = models.CharField(
        max_length=10,
        choices=EventAuthorizationStatusChoices.choices,
        default=EventAuthorizationStatusChoices.PENDING
    )
    
    reason = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if not self.review_code:
            self.review_code = f"EVT-AUTH-{uuid.uuid4().hex[:10].upper()}"

        if self.status == EventAuthorizationStatusChoices.REJECTED:
            self.event.force_close()

        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Authorization for {self.event} by {self.reviewed_by} - Status: {self.status}"
    
    def __repr__(self):
        return f"<EventAuthorization(event={self.event}, reviewed_by={self.reviewed_by}, status={self.status})>"
    
    @property
    def is_rejected(self):
        return self.status == EventAuthorizationStatusChoices.REJECTED
    
    @property
    def is_approved(self):
        return self.status == EventAuthorizationStatusChoices.APPROVED
    
    @property
    def is_pending(self):
        return self.status == EventAuthorizationStatusChoices.PENDING
    
    class Meta:
        unique_together = ('event', 'reviewed_by')
        ordering = ['-reviewed_at']
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['review_id']),
            models.Index(fields=['reviewed_by']),
        ]