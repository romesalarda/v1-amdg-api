
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

def get_event_or_url_safe_title(event_id, qs=None):
    """Helper function to retrieve an Event instance by UUID or URL-safe title."""

    if not event_id:
        return None

    try:
        event_uuid = uuid.UUID(event_id)
        if qs is not None:
            return get_object_or_404(qs, event_id=event_uuid)
        from apps.events.models import Event
        return get_object_or_404(Event, event_id=event_uuid)
    except ValueError:
        if qs is not None:
            return get_object_or_404(qs, url_safe_title=event_id)
        from apps.events.models import Event  # Import here to avoid circular imports
        return get_object_or_404(Event, url_safe_title=event_id)
    
def get_object_or_url_safe_title(model_queryset, identifier):
    """Generic helper function to retrieve an object by numeric id or URL-safe title."""
    try:
        obj_id = int(identifier)
        return get_object_or_404(model_queryset, pk=obj_id)
    except (TypeError, ValueError):
        return get_object_or_404(model_queryset, url_safe_title=identifier)
    
def get_event_list_or_url_safe_title(model_queryset, event_identifier, **kwargs):
    """
    Get Event queryset filtered by either UUID or URL-safe title.
    """

    try:
        obj_id = uuid.UUID(event_identifier)
        return model_queryset.filter(event_id=obj_id)
    except (TypeError, ValueError):
        return model_queryset.filter(url_safe_title=event_identifier)