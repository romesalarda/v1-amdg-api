from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from rest_framework import viewsets, permissions
from apps.events.models import EventSettings
from apps.events.api.serializers import EventSettingsSerializer
from apps.events.api.pagination import StandardPagination


@extend_schema_view(
    list=extend_schema(
        summary="List Event Settings",
        description=(
            "Retrieve a paginated list of all event settings across the system. "
            "Event settings control various aspects of event behavior including product selling, "
            "order approval requirements, and booking configurations. Primarily used for administrative oversight."
        ),
        tags=["Event Settings"],
    ),
    retrieve=extend_schema(
        summary="Get Event Settings",
        description=(
            "Retrieve detailed settings for a specific event including all configuration options. "
            "Settings control product selling options, order approval workflows, booking behavior, and other event-specific preferences."
        ),
        tags=["Event Settings"],
    ),
    create=extend_schema(
        summary="Create Event Settings",
        description=(
            "Create new settings for an event with specified configuration options. "
            "Typically created automatically when an event is created. "
            "Only event managers and administrators can create settings."
        ),
        tags=["Event Settings"],
    ),
    update=extend_schema(
        summary="Update Event Settings",
        description=(
            "Update all settings for an event. Requires complete payload with all fields. "
            "Use PATCH for partial updates of individual settings. "
            "Only event managers and administrators can update settings."
        ),
        tags=["Event Settings"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Settings",
        description=(
            "Partially update event settings without providing complete payload. "
            "Allows updating individual configuration options independently. "
            "Only event managers and administrators can update settings."
        ),
        tags=["Event Settings"],
    ),
    destroy=extend_schema(
        summary="Delete Event Settings",
        description=(
            "Delete event settings. Use with caution as this affects event functionality. "
            "Only administrators should delete event settings. "
            "Consider updating instead of deleting to preserve configuration history."
        ),
        tags=["Event Settings"],
    )
)
class EventSettingsViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event settings and configurations.
    
    Provides CRUD operations for event settings including:
    - Product selling options
    - Order approval requirements
    - Booking configurations
    - Custom event preferences
    
    Settings are typically created automatically when events are created and
    control various aspects of event behavior and functionality.
    """
    queryset = EventSettings.objects.all()
    serializer_class = EventSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination