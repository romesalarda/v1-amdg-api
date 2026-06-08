from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.validators import MinLengthValidator, MaxLengthValidator, EmailValidator
from core.utils.validators import PhoneNumberValidator
from django.utils.translation import gettext_lazy as _

from django.contrib.auth import get_user_model

from apps.common.models.verification import RequiresVerificationModel

import uuid 

class DelegationType(models.TextChoices):
    COUNTRY = 'country', _('Country')
    AREA = 'area', _('Area')
    CHAPTER = 'chapter', _('Chapter')
    CLUSTER = 'cluster', _('Cluster')
    COMPANY = 'company', _('Company')
    ORGANISATION = 'organisation', _('Organisation')
    PARISH = 'parish', _('Parish')
    COMMUNITY = 'community', _('Community')
    GROUP = 'group', _('Group')
    OTHER = 'other', _('Other')


class Delegation(RequiresVerificationModel):
    """
    Represents a group or attendees for an event. This could country delegations, company delegations, or any other grouping of attendees.
    """

    LOCATION_BASED_TYPES = {DelegationType.COUNTRY, DelegationType.AREA, DelegationType.CHAPTER, DelegationType.CLUSTER}


    delegation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255, validators=[MinLengthValidator(3), MaxLengthValidator(255)])
    type = models.CharField(max_length=50, choices=DelegationType.choices)
    description = models.TextField(blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True, validators=[EmailValidator()], help_text=_('Primary contact email for the delegation. At least one contact method (email or phone) must be provided.'))
    contact_phone = models.CharField(max_length=20, blank=True, null=True, validators=[PhoneNumberValidator()], help_text=_('Primary contact phone for the delegation. At least one contact method (email or phone) must be provided.'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True, related_name='delegations_created')

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"
    
    def clean(self):
        super().clean()
        if not self.contact_email and not self.contact_phone:
            raise ValidationError(_('At least one contact method (email or phone) must be provided.'))
        
    @property
    def is_location_based(self):
        return self.type in self.LOCATION_BASED_TYPES

class DelegationHeadRoleChoices(models.TextChoices):
    YOUTH_HEAD = 'youth_head', _('Youth Head')
    ADULT_HEAD = 'adult_head', _('Adult Head')
    OTHER = 'other', _('Other')

class DelegationHead(models.Model):
    """
    Represents the head of a delegation, linking a user to a delegation with a specific role.
    """
    delegation = models.ForeignKey(Delegation, on_delete=models.CASCADE, related_name='heads')
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='delegation_heads')
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name='delegation_heads')
    role = models.CharField(max_length=50, choices=DelegationHeadRoleChoices.choices, default=DelegationHeadRoleChoices.OTHER)

    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True, related_name='delegation_heads_added')

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_role_display()} of {self.delegation.name}"


def default_expires_at():
    return timezone.now() + timezone.timedelta(days=7)
    
class DelegationHeadInvite(RequiresVerificationModel):
    """
    Represents an invitation for a user to become a delegation head. This allows for pending invitations that can be accepted or declined.
    """
    invite_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    delegation = models.ForeignKey(Delegation, on_delete=models.CASCADE, related_name='head_invites')
    email = models.EmailField(validators=[EmailValidator()])
    user = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True, related_name='delegation_head_invites')
    role = models.CharField(max_length=50, choices=DelegationHeadRoleChoices.choices, default=DelegationHeadRoleChoices.OTHER)
    
    expires_at = models.DateTimeField(blank=True, null=True, default=default_expires_at)
    invited_at = models.DateTimeField(auto_now_add=True)
    invited_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True, related_name='delegation_head_invites_sent')
    accepted_at = models.DateTimeField(blank=True, null=True)
    accepted_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True, related_name='delegation_head_invites_accepted')
    
    def __str__(self):
        return f"Invite for {self.email} to be {self.get_role_display()} of {self.delegation.name}"

    def clean(self):
        super().clean()
        if self.accepted_at and not self.accepted_by:
            raise ValidationError(_('Accepted invitations must have an accepted_by user.'))
        if not self.accepted_at and self.accepted_by:
            raise ValidationError(_('Pending invitations cannot have an accepted_by user.'))

        if self.expires_at and self.expires_at < timezone.now():
            raise ValidationError(_('The expiration date cannot be in the past.'))
        
    @property
    def is_accepted(self):
        return self.accepted_at is not None
    
    def accept(self, user):
        if self.accepted_at:
            raise ValidationError(_('This invitation has already been accepted.'))
        self.accepted_at = timezone.now()
        self.accepted_by = user
        self.save()
        # Create the DelegationHead record
        delegation_head = DelegationHead(
            delegation=self.delegation,
            attendee=None,  # This can be set to an attendee if needed
            user=user,
            role=self.role,
            added_by=user
        )
        delegation_head.full_clean()
        delegation_head.save()