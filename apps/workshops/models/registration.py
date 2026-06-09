from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.common.models import RequiresVerificationModel
from core.utils.display import try_generate_unique_display_code

import uuid


class WorkshopRegistrationStatus(models.TextChoices):
    PENDING_ALLOCATION = 'PENDING_ALLOCATION', _('Pending Allocation')
    CONFIRMED = 'CONFIRMED', _('Confirmed')
    WAITLISTED = 'WAITLISTED', _('Waitlisted')
    CANCELLED = 'CANCELLED', _('Cancelled')


class WorkshopRegistration(RequiresVerificationModel):
    '''
    Represents a registration of an attendee for a workshop.

    Status flow:
    - FCFS: created directly as CONFIRMED (or WAITLISTED if capacity full).
    - INTEREST_RANKING / RANDOM: created as PENDING_ALLOCATION, then transitioned
      to CONFIRMED or WAITLISTED by the allocation service.
    - MANUAL: set to CONFIRMED directly by a staff member.
    '''

    registration_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_reference = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        help_text=_("Unique reference code for the workshop registration. Auto-generated if not provided."),
    )
    workshop = models.ForeignKey(
        "workshops.Workshop",
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    attendee = models.ForeignKey(
        "attendee.Attendee",
        on_delete=models.CASCADE,
        related_name="workshop_registrations",
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=WorkshopRegistrationStatus.choices,
        default=WorkshopRegistrationStatus.CONFIRMED,
        help_text=_("Allocation status for this registration."),
    )
    allocation_method = models.CharField(
        max_length=20,
        choices=[
            ('FCFS', _('First Come First Served')),
            ('INTEREST_RANKING', _('Interest Ranking')),
            ('RANDOM', _('Random')),
            ('MANUAL', _('Manual')),
        ],
        null=True,
        blank=True,
        help_text=_("Which allocation method produced this registration."),
    )
    allocated_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workshop_allocations_made",
        help_text=_("Staff member who manually confirmed this registration (if applicable)."),
    )
    notes = models.TextField(
        null=True,
        blank=True,
        help_text=_("Optional internal notes about this registration."),
    )

    def __str__(self):
        return f"{self.attendee} — {self.workshop} [{self.get_status_display()}]"

    class Meta:
        verbose_name = _("Workshop Registration")
        verbose_name_plural = _("Workshop Registrations")
        unique_together = ('workshop', 'attendee')

    def save(self, *args, **kwargs):
        if not self.booking_reference:
            try:
                self.booking_reference = try_generate_unique_display_code(
                    model_class=WorkshopRegistration,
                    length=35,
                    prefix='WRK-',
                    args=[str(self.workshop_id)],
                    lookup_field='booking_reference',
                    max_attempts=5,
                ).lower()
            except ValueError:
                raise ValidationError({'booking_reference': 'Could not generate unique workshop booking reference.'})
        super().save(*args, **kwargs)