from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from .events import Event

from django.utils import timezone

import uuid
User = get_user_model()

class EventStaffInvite(models.Model):
    '''
    Model representing an invitation sent to a user to join the staff of an event.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='staff_invites')
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='event_staff_invites_received')
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='event_staff_invites_sent')
    
    # Permission template to apply on acceptance
    permission_template = models.CharField(
        max_length=50, 
        blank=True, 
        null=True,
        help_text="Code of the permission template to apply when invite is accepted"
    )
    
    accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('event', 'target_user') # A user can only have one active invite per event
        ordering = ['-added_at']
    
    
    def __str__(self):
        return f"Invite to {self.target_user} for {self.event.title}"
    
    def __repr__(self):
        return f"<EventStaffInvite id={self.id} event={self.event.title} target_user={self.target_user} accepted={self.accepted}>"
    
    def clean(self):
        if self.expires_at and self.expires_at < timezone.now():
            raise ValidationError("Expiry date cannot be in the past.")
        
    @property
    def is_valid(self):
        if not self.is_active:
            return False
        
        if self.accepted:
            return False
        
        if self.expires_at and self.expires_at < timezone.now():
            return False
        
        return True
    
    def accept_invite(self):
        '''
        Denotes that the invite has been accepted.
        Raises ValidationError if the invite is not valid.
        '''
        if not self.is_valid:
            raise ValidationError("Invite is not valid.")
        
        from .staff import EventStaff
        
        self.accepted = True
        self.accepted_at = timezone.now()
        self.is_active = False

        # Create staff member
        staff = EventStaff.objects.create(
            event=self.event,
            user=self.target_user,
            assigned_by=self.invited_by,
            notes=f"Staff added via invite {self.id}"
        )

        # Apply permission template if one is set
        if self.permission_template:
            from apps.events.services.staff_service import apply_permission_template
            try:
                apply_permission_template(
                    event=self.event,
                    user=self.target_user,
                    template_code=self.permission_template,
                    assigned_by=self.invited_by
                )
            except ValidationError as e:
                # Log the error but don't fail the acceptance
                # The staff member is still added, just without the template permissions
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Failed to apply permission template {self.permission_template} "
                    f"for invite {self.id}: {str(e)}"
                )

        self.save()