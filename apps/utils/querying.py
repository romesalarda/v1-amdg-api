
from django.shortcuts import get_object_or_404
import uuid

def get_event_or_url_safe_title(event_id):
    """Helper function to retrieve an Event instance by UUID or URL-safe title."""
    from apps.events.models import Event  # Import here to avoid circular imports

    try:
        # Try to interpret event_id as a UUID
        event_uuid = uuid.UUID(event_id)
        return get_object_or_404(Event, event_id=event_uuid)
    except ValueError:
        # If it's not a valid UUID, treat it as a URL-safe title
        return get_object_or_404(Event, url_safe_title=event_id)