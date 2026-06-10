from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from apps.common.models import RequiresVerificationModel


class WorkshopStatus(models.TextChoices):
    DRAFT = 'DRAFT', _('Draft')
    OPEN = 'OPEN', _('Open')
    CLOSED = 'CLOSED', _('Closed')
    CANCELLED = 'CANCELLED', _('Cancelled')


class AllocationMode(models.TextChoices):
    FCFS = 'FCFS', _('First Come First Served')
    INTEREST_RANKING = 'INTEREST_RANKING', _('Interest Ranking')
    RANDOM = 'RANDOM', _('Random')
    MANUAL = 'MANUAL', _('Manual')


class Workshop(RequiresVerificationModel):
    '''
    Represents a workshop that attendees can register for.

    Lifecycle: DRAFT → OPEN (registrations allowed) → CLOSED (allocation runs) → CANCELLED.
    Allocation mode controls how attendees are assigned a spot.
    '''

    title = models.CharField(max_length=255)
    description = models.TextField(help_text=_("Detailed description of the workshop"))
    landing_image = models.ImageField(
        upload_to='workshop_images/',
        null=True,
        blank=True,
        help_text=_("Optional image to display on the workshop landing page"),
    )
    what_to_expect = models.TextField(blank=True, null=True, help_text=_("Information about what attendees can expect from the workshop"))
    what_to_bring = models.TextField(blank=True, null=True, help_text=_("Information about what attendees should bring to the workshop"))
    
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="workshops")
    date = models.DateTimeField()
    venue = models.ForeignKey("events.EventVenue", on_delete=models.SET_NULL, null=True, blank=True, related_name="workshops")
    room = models.ForeignKey("events.EventVenueRoom", on_delete=models.SET_NULL, null=True, blank=True, related_name="workshops")
    notes = models.TextField(blank=True, null=True, help_text=_("Additional notes or instructions for the workshop"))

    status = models.CharField(
        max_length=20,
        choices=WorkshopStatus.choices,
        default=WorkshopStatus.DRAFT,
        help_text=_("Current lifecycle status of the workshop."),
    )
    allocation_mode = models.CharField(
        max_length=20,
        choices=AllocationMode.choices,
        default=AllocationMode.FCFS,
        help_text=_("How attendee spots are allocated for this workshop."),
    )
    capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("Maximum number of confirmed registrations. Leave blank for unlimited."),
    )
    duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("Duration of the workshop in minutes."),
    )
    registration_opens_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When registration opens. Informational — does not enforce access automatically."),
    )
    registration_closes_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When registration closes. Informational — does not enforce access automatically."),
    )

    def __str__(self):
        return f"{self.title} ({self.event})"

    class Meta:
        verbose_name = _("Workshop")
        verbose_name_plural = _("Workshops")
        ordering = ['date']

    def clean(self):
        if self.room and self.venue and self.room.event_venue != self.venue:
            raise ValidationError(_("Selected room does not belong to the selected venue."))
        if self.registration_opens_at and self.registration_closes_at:
            if self.registration_opens_at >= self.registration_closes_at:
                raise ValidationError(_("Registration must open before it closes."))

    @property
    def current_registration_count(self):
        from apps.workshops.models.registration import WorkshopRegistrationStatus
        return self.registrations.filter(status=WorkshopRegistrationStatus.CONFIRMED).count()

    @property
    def is_full(self):
        if self.capacity is None:
            return False
        return self.current_registration_count >= self.capacity