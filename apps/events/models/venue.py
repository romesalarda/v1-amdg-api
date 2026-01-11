from django.db import models
from apps.locations.models import Venue
import uuid

class EventVenue(models.Model):
    """
    Model representing the association between events and their venues.
    """
    event_venue_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='event_venues')
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='event_venues')

    class Meta:
        verbose_name = "Event Venue"
        verbose_name_plural = "Event Venues"

    def __str__(self):
        return f"EventVenue for Event ID {self.event.id} at Venue {self.venue.poi.name}"
    
    def __repr__(self):
        return f"<EventVenue(event_venue_id={self.event_venue_id}, event_id={self.event.id}, venue_id={self.venue.id})>"