from django.db import models
from django.core import validators
from core.utils.validators import PhoneNumberValidator
import uuid


class EventVenueContactRoleChoice(models.TextChoices):
    MANAGER = 'MANAGER', 'Manager'
    OWNER = 'OWNER', 'Owner'
    COORDINATOR = 'COORDINATOR', 'Coordinator'
    SUPPORT = 'SUPPORT', 'Support'
    OTHER = 'OTHER', 'Other'


class EventVenue(models.Model):
    """
    Event-scoped venue snapshot.

    When created from an existing global Venue, all relevant fields are cloned
    from that source record (including rooms, contacts, metadata).  After
    creation the event fully owns this record — edits here never touch the
    global Venue registry.

    source_venue_id is a nullable soft reference (no FK) kept purely for
    attribution / history.  It carries no referential integrity.
    """
    event_venue_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='event_venues')
    is_primary = models.BooleanField(default=False, help_text="Designates the primary venue for the event when multiple venues are present.")

    # Soft reference to the global Venue from which this snapshot was cloned.
    # NULL when the venue was created directly for this event (no global source).
    source_venue_id = models.IntegerField(null=True, blank=True)

    # ── POI / location fields (cloned from Venue.poi) ────────────────────────
    name = models.CharField(max_length=255)
    address = models.TextField(max_length=500)
    postcode = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, blank=True)
    poi_type = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ── Venue-level fields (cloned from Venue) ────────────────────────────────
    description = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Event Venue"
        verbose_name_plural = "Event Venues"
        constraints = [
            # Prevent the same global venue from being linked twice to one event.
            models.UniqueConstraint(
                fields=['event', 'source_venue_id'],
                condition=models.Q(source_venue_id__isnull=False),
                name='unique_event_source_venue',
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.event.display_code}"

    def __repr__(self):
        return (
            f"<EventVenue(event_venue_id={self.event_venue_id}, "
            f"event_id={self.event.pk}, source_venue_id={self.source_venue_id})>"
        )


class EventVenueRoom(models.Model):
    """Room record scoped to an EventVenue snapshot."""
    event_venue = models.ForeignKey(EventVenue, on_delete=models.CASCADE, related_name='rooms')
    room_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.room_name} — {self.event_venue}"


class EventVenueContact(models.Model):
    """Contact record scoped to an EventVenue snapshot."""
    event_venue = models.ForeignKey(EventVenue, on_delete=models.CASCADE, related_name='contacts')
    contact_name = models.CharField(max_length=255, validators=[validators.MinLengthValidator(2)])
    phone_number = models.CharField(max_length=20, blank=True, null=True, validators=[PhoneNumberValidator()])
    email = models.EmailField(blank=True, null=True, validators=[validators.EmailValidator()])
    role = models.CharField(
        max_length=100,
        choices=EventVenueContactRoleChoice.choices,
        blank=True,
        default=EventVenueContactRoleChoice.OWNER,
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.contact_name} ({self.role}) — {self.event_venue}"


class EventVenueMetadata(models.Model):
    """Metadata entry scoped to an EventVenue snapshot."""
    event_venue = models.ForeignKey(EventVenue, on_delete=models.CASCADE, related_name='metadata')
    label = models.CharField(max_length=255)
    value = models.TextField(blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.label} — {self.event_venue}"