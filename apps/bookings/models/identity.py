
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from django.contrib.auth import get_user_model

from apps.common.models.verification import RequiresVerificationModel

import uuid 

User = get_user_model()

class EventAlternativeSigninIdentifier(RequiresVerificationModel):
    '''
    Model to represent alternative sign-in identifiers for events.
    I.e. tickets can check for these identifiers when signing in to allow compatibility with other forms of identification.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name=_("ID"))
    title = models.CharField(max_length=255, verbose_name=_("Title"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='alternative_signins',
        verbose_name=_("Event")
    )

    format_match = models.CharField(
        max_length=255,
        verbose_name=_("Format Match"),
        help_text=_("A regex pattern to match the identifier format."),
        blank=True,
        null=True
    )

    max_uses_per_signin = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Max Uses Per Sign-in"))
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    def __str__(self):
        return self.title
    
    def __repr__(self):
        return f"<EventAlternativeSigninIdentifier(title={self.title}, event_id={self.event_id})>"
    
    class Meta:
        unique_together = ('event', 'title')
        verbose_name = _("Event Alternative Sign-in Identifier")
        verbose_name_plural = _("Event Alternative Sign-in Identifiers")

    def save(self, *args, **kwargs):

        self.full_clean()
        self.title = self.title.strip().title()
        super().save(*args, **kwargs)

    def clean(self):
        if not self.title:
            raise ValidationError({"title": _("Title cannot be empty.")})
        
    @property
    def is_valid(self) -> bool:
        """
        Check if the alternative sign-in identifier is active and valid.
        """
        return self.is_active

    def validate_code_format(self, code: str) -> bool:
        """
        Validate the given code against the format_match regex if provided.
        """
        import re

        if self.format_match:
            pattern = re.compile(self.format_match)
            return bool(pattern.fullmatch(code))
        return True  # If no format_match is provided, consider it valid
    
    
# normal way
# 1. User scans QR code on ticket
# 2. QR code contains general code 
# 3. Looks for Ticket with that code
# 4. gets associated attendee
# 5. signs in the attendee

# defintion
# when user registers for event, they can define alternative signin identifiers for each attendee/ticket
# i.e. YFC YIM number

# alternative way
# 1. user scans with another id defined by event alternative signin identifier
# 2. looks for AttendeeAlternativeSigninIdentifier with that code
# 3. gets associated ticket and attendee
# 4. signs in the attendee
    
class AttendeeAlternativeSigninIdentifier(models.Model):
    '''
    Model to represent alternative sign-in identifiers for attendees.
    I.e. attendees can have multiple identifiers for signing in to events.
    '''
    sign_id = models.UUIDField(default=uuid.uuid4, editable=False, verbose_name=_("Sign ID"))
    attendee = models.ForeignKey( # attendee associated with this identifier for fast lookup
        'attendee.Attendee',
        on_delete=models.CASCADE,
        related_name='alternative_signins',
        verbose_name=_("Attendee")
    )
    ticket = models.ForeignKey( # ticket associated with this identifier for fast lookup, may be null if not linked to a ticket
        'bookings.Ticket',
        on_delete=models.CASCADE,
        related_name='attendee_alternative_signins',
        verbose_name=_("Ticket"),
        blank=True,
        null=True
    )
    identifier = models.CharField(max_length=255, verbose_name=_("Identifier"))

    event_alternative_signin = models.ForeignKey(
        EventAlternativeSigninIdentifier,
        on_delete=models.CASCADE,
        related_name='attendee_identifiers',
        verbose_name=_("Event Alternative Sign-in Identifier")
    )

    defined_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    defined_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='defined_attendee_alternative_signins',
        verbose_name=_("Defined By")
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))
    uses = models.PositiveIntegerField(default=0, verbose_name=_("Uses"))

    def __str__(self):
        return f"{self.attendee} - {self.identifier}"
    
    def __repr__(self):
        return f"<AttendeeAlternativeSigninIdentifier(attendee_id={self.attendee_id}, identifier={self.identifier})>"

    def save(self, *args, **kwargs):
        self.full_clean()
        self.identifier = self.identifier.strip()
        super().save(*args, **kwargs)

    def clean(self):
        if not self.identifier:
            raise ValidationError({"identifier": _("Identifier cannot be empty.")})
        if self.event_alternative_signin and not self.event_alternative_signin.validate_code_format(self.identifier):
            raise ValidationError({"identifier": _("Identifier does not match the required format.")})

        if self.event_alternative_signin.event_id != self.ticket.event_id:
            raise ValidationError({"event_alternative_signin": _("The event alternative sign-in identifier must belong to the same event as the ticket.")})
        
        if not self.ticket.attendee_id == self.attendee_id:
            raise ValidationError({"ticket": _("The ticket must belong to the same attendee.")})
        
        if not self.event_alternative_signin.is_valid:
            raise ValidationError({"event_alternative_signin": _("The event alternative sign-in identifier is not active.")})
        if self.pk is None:  # Only check for uniqueness on creation
            existing = AttendeeAlternativeSigninIdentifier.objects.filter(
                attendee=self.attendee,
                event_alternative_signin=self.event_alternative_signin,
                identifier=self.identifier
            )
            if existing.exists():
                raise ValidationError({"identifier": _("This identifier is already in use for the given attendee and event alternative sign-in.")})

    class Meta:
        unique_together = ('attendee', 'event_alternative_signin', 'identifier')

    @property
    def has_ticket(self) -> bool:
        """
        Check if this identifier is associated with a ticket.
        """
        return self.ticket is not None

    @property
    def is_valid(self) -> bool:
        """
        Check if the attendee alternative sign-in identifier is valid based on its associated event alternative sign-in identifier.
        """
        return self.event_alternative_signin.is_valid and (
            self.event_alternative_signin.max_uses_per_signin is None or 
            self.uses < self.event_alternative_signin.max_uses_per_signin and 
            self.has_ticket
            )

    def use(self):
        """
        Increment the use count for this identifier.
        """
        if not self.is_valid:
            raise ValidationError(_("This identifier has reached its maximum number of uses or is not valid."))
        
        self.uses += 1
        self.save(update_fields=['uses'])
