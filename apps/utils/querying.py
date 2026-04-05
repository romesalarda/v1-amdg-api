
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
import uuid


def get_organisation_or_url_safe_title(organisation_identifier):
    """Helper function to retrieve an Organisation by numeric id or URL-safe title."""
    from apps.organisations.models import Organisation  # Import here to avoid circular imports

    try:
        organisation_id = int(organisation_identifier)
        return get_object_or_404(Organisation, pk=organisation_id)
    except (TypeError, ValueError):
        return get_object_or_404(Organisation, url_safe_title=organisation_identifier)

def get_event_or_url_safe_title(event_id):
    """Helper function to retrieve an Event instance by UUID or URL-safe title."""
    from apps.events.models import Event  # Import here to avoid circular imports

    if not event_id:
        return None

    try:
        # Try to interpret event_id as a UUID
        event_uuid = uuid.UUID(event_id)
        return get_object_or_404(Event, event_id=event_uuid)
    except ValueError:
        # If it's not a valid UUID, treat it as a URL-safe title
        return get_object_or_404(Event, url_safe_title=event_id)