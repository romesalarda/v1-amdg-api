from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import EmailValidator, RegexValidator, MinLengthValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.utils.validators import PhoneNumberValidator
from core.utils.display import generate_alphanumeric_id

import uuid

User = get_user_model()

class Organisation(models.Model):
    
    title = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    
    landing_image = models.ImageField(upload_to='organisation/landing-images/', blank=True, null=True)
    landing_image_uploaded_at = models.DateTimeField(auto_now_add=True)
    
    logo = models.ImageField(upload_to='organisation/logos/', blank=True, null=True)
    logo_uploaded_at = models.DateTimeField(auto_now_add=True)
    
    external_website = models.URLField(blank=True, null=True)
    
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='organisations_created')

    required_acceptance_code = models.BooleanField(default=False)
    requires_manual_verification = models.BooleanField(default=False)

    def __str__(self):
        return self.title
    
class OrganisationContact(models.Model):
    '''
    Model representing a contact person for an organisation.
    '''
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=255)
    email = models.EmailField(validators=[EmailValidator()])
    phone = models.CharField(max_length=20, blank=True, validators=[PhoneNumberValidator()])
    label = models.CharField(max_length=100, blank=True)
    
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.organisation.title})"
    
class UserOrganisationMembership(models.Model): # adminregister
    '''
    Model representing a user's membership in an organisation.
    '''
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organisations_memberships')
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='user_organisation_memberships_added')

    verified_at = models.DateTimeField(blank=True, null=True)

    
    class Meta:
        unique_together = ('organisation', 'user')
    
    def __str__(self):
        return f"{self.user.username} member of {self.organisation.title}"
    
    @property
    def requires_verification(self):
        return self.organisation.requires_manual_verification
    
    def verify_with_invite(self, invite: 'OrganisationInvite'):
        '''
        verify associated membership using an invite.
        
        :param self: Description
        :param invite: OrganisationInvite instance to verify membership
        :type invite: OrganisationInvite
        '''
        if not invite.is_valid:
            raise ValidationError("Invite is not valid.")
        
        if invite.organisation != self.organisation or invite.target_user != self.user:
            raise ValidationError("Invite does not match organisation or user.")
        
        invite.accept_invite()
        self.verified_at = timezone.now()
        self.save()

    def verify_with_code(self, acceptance_code: 'OrganisationAcceptanceCode'):
        '''
        verify associated membership using an acceptance code.
        
        :param self: Description
        :param code: Acceptance code to verify membership
        :type code: OrganisationAcceptanceCode
        '''
        if not self.organisation.required_acceptance_code:
            raise ValidationError("This organisation does not require an acceptance code for verification.")
        
        if not acceptance_code.is_valid:
            raise ValidationError("Acceptance code is not valid.")
        
        acceptance_code.use_code()
        self.verified_at = timezone.now()
        self.save()

    def verify_manually(self, verified_by):
        '''
        Docstring for verify_manually
        
        :param self: Description
        :param verified_by: User who verified the membership
        
        Raises ValidationError if the organisation does not require manual verification.
        '''
        if not self.organisation.requires_manual_verification:
            raise ValidationError("This organisation does not require manual verification.")
        
        self.verified_at = timezone.now()
        self.save()
    
class OrganisationControl(models.Model):
    '''
    Model representing a user who has control over an organisation.
    '''

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='controllers')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organisations_controlled')
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='organisation_controls_added')
    
    class Meta:
        unique_together = ('organisation', 'user')
    
    def __str__(self):
        return f"{self.user.username} controls {self.organisation.title}"
    
class InvolvedOrganisationRoleChoices(models.TextChoices):
    COMMUNITY = 'COMMUNITY', 'Community'
    SPONSOR = 'SPONSOR', 'Sponsor'
    PARTNER = 'PARTNER', 'Partner'
    ORGANISER = 'ORGANISER', 'Organiser'
    VENUE_PROVIDER = 'VENUE_PROVIDER', 'Venue Provider'
    MEDIA_PARTNER = 'MEDIA_PARTNER', 'Media Partner'

class InvolvedEventOrganisation(models.Model):
    '''
    Model representing an organisation involved in an event. E.g. sponsors, partners, organisers.
    '''
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='involvements')    
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='involved_organisations')
    role = models.CharField(max_length=30, choices=InvolvedOrganisationRoleChoices.choices, default=InvolvedOrganisationRoleChoices.COMMUNITY)
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='involved_organisations_added')
    
    class Meta:
        unique_together = ('organisation', 'event', 'role')
        ordering = ['-added_at']
    
    def __str__(self):
        return f"{self.organisation.title} as {self.role} in event {self.event.title}"

class OrganisationAcceptanceCode(models.Model):
    '''
    Model representing an acceptance code for an organisation.
    '''
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='acceptance_codes')
    code = models.CharField(max_length=15, unique=True, blank=True, null=True, help_text="Alphanumeric acceptance code.", validators=
                            [RegexValidator(
                                    regex='^[A-Z0-9]+$',
                                    message='Code must be alphanumeric and uppercase.',
                                    code='invalid_code'
                                ),
                                MinLengthValidator(5)
                            ])
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='organisation_acceptance_codes_added')
    expires_at = models.DateTimeField(blank=True, null=True)

    uses = models.PositiveIntegerField(default=0)
    max_uses = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"Acceptance code for {self.organisation.title}: {self.code}"
    
    def __repr__(self):
        return f"<OrganisationAcceptanceCode organisation={self.organisation.title} code={self.code} uses={self.uses}/{self.max_uses} active={self.is_active}>"
    
    def save(self, *args, **kwargs):
        if not self.code:
            while True:
                generated_code = generate_alphanumeric_id(length=10).upper()
                if not OrganisationAcceptanceCode.objects.filter(code=generated_code).exists():
                    self.code = generated_code
                    break

        if self.expires_at and self.expires_at < timezone.now():
            self.is_active = False

        super().save(*args, **kwargs)
    
    def clean(self):
        if self.code:
            self.code = self.code.strip().upper()

        if self.expires_at and self.expires_at < timezone.now():
            raise ValidationError("Expiry date cannot be in the past.")


    @property
    def is_single_use(self):
        return self.max_uses == 1
    
    @property
    def is_valid(self):
        if not self.is_active:
            return False
        
        if self.uses >= self.max_uses:
            return False
        
        if self.expires_at and self.expires_at < timezone.now():
            return False
        
        return True
        
    def use_code(self):
        if not self.is_active:
            raise ValidationError("Acceptance code is not active.")
        
        if self.uses >= self.max_uses:
            raise ValidationError("Acceptance code has reached its maximum uses.")
        
        if self.expires_at and self.expires_at < timezone.now():
            self.is_active = False
            raise ValidationError("Acceptance code has expired.")
        self.uses += 1
        
        if self.uses >= self.max_uses:
            self.is_active = False
        
        self.save()

class OrganisationInvite(models.Model): # adminregister
    '''
    Model representing an invite to join an organisatnio to a specific user / email.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='invites')
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='organisation_invites_received')
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='organisation_invites_sent')
    
    accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('organisation', 'target_user') # A user can only have one active invite per organisation
        ordering = ['-added_at']
    
    
    def __str__(self):
        return f"Invite to {self.target_user} for {self.organisation.title}"
    
    def __repr__(self):
        return f"<OrganisationInvite id={self.id} organisation={self.organisation.title} target_user={self.target_user} accepted={self.accepted}>"
    
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
        
        self.accepted = True
        self.accepted_at = timezone.now()
        self.is_active = False
        self.save()