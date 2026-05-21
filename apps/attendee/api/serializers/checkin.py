"""
Serializers for AttendeeCheckIn — covers HTTP endpoints and WebSocket message
validation/formatting.
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model

from apps.attendee.models import AttendeeCheckIn, CheckInAction, CheckInMethod, CheckInScanResult

User = get_user_model()


# ============================================================================
# HTTP — CREATE / RESPONSE
# ============================================================================

class CheckInCreateSerializer(serializers.Serializer):
    """Validates the POST /api/attendee/checkins/ request body."""

    # At least one lookup field must be provided.
    ticket_code = serializers.CharField(required=False, allow_blank=False)
    attendee_display_id = serializers.CharField(required=False, allow_blank=False)
    alternative_identifier = serializers.CharField(required=False, allow_blank=False)

    action = serializers.ChoiceField(
        choices=CheckInAction.choices,
        default=CheckInAction.CHECK_IN,
    )
    method = serializers.ChoiceField(
        choices=CheckInMethod.choices,
        default=CheckInMethod.MANUAL,
    )
    venue_id = serializers.UUIDField(required=False, allow_null=True)
    venue_room_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    device_info = serializers.DictField(required=False, allow_null=True)

    def validate(self, data):
        lookup_fields = ('ticket_code', 'attendee_display_id', 'alternative_identifier')
        if not any(data.get(f) for f in lookup_fields):
            raise serializers.ValidationError(
                'At least one of ticket_code, attendee_display_id, or '
                'alternative_identifier is required.'
            )
        return data


class CheckInResponseSerializer(serializers.ModelSerializer):
    """Full detail response for a created AttendeeCheckIn record."""

    attendee_uuid = serializers.UUIDField(
        source='attendee.attendee_id', read_only=True
    )
    attendee_display_id = serializers.CharField(
        source='attendee.attendee_display_id', read_only=True
    )
    attendee_full_name = serializers.CharField(
        source='attendee.full_name', read_only=True
    )
    ticket_code = serializers.CharField(
        source='ticket.ticket_code', read_only=True, allow_null=True
    )
    ticket_type_code = serializers.CharField(
        source='ticket.ticket_type.code', read_only=True, allow_null=True
    )
    venue_name = serializers.CharField(
        source='venue.name', read_only=True, allow_null=True
    )
    venue_room_name = serializers.CharField(
        source='venue_room.room_name', read_only=True, allow_null=True
    )
    performed_by_id = serializers.IntegerField(
        source='performed_by.id', read_only=True, allow_null=True
    )
    performed_by_name = serializers.SerializerMethodField()
    area_from = serializers.CharField(
        source='attendee.area_from.area_name', read_only=True, allow_null=True
    )

    class Meta:
        model = AttendeeCheckIn
        fields = (
            'check_in_id',
            'attendee_id',
            'attendee_uuid',
            'attendee_display_id',
            'attendee_full_name',
            'ticket_id',
            'ticket_code',
            'ticket_type_code',
            'action',
            'method',
            'scan_result',
            'venue_id',
            'venue_name',
            'venue_room_id',
            'venue_room_name',
            'has_outstanding_payments',
            'attendee_status_snapshot',
            'area_from',
            'performed_by_id',
            'performed_by_name',
            'performed_at',
            'notes',
            'event_day',
        )
        read_only_fields = fields

    def get_performed_by_name(self, obj) -> str | None:
        if obj.performed_by:
            return (
                obj.performed_by.get_full_name()
                or obj.performed_by.email
            )
        return None


# ============================================================================
# WS — BROADCAST PAYLOAD
# ============================================================================

class CheckInBroadcastSerializer(serializers.ModelSerializer):
    """
    Minimal pointer-rich payload for the checkin.occurred WS broadcast.

    Consumed by the HTTP view (after creating an AttendeeCheckIn) and by the
    WS consumer when formatting checkin.history.response items.
    """

    attendee_id = serializers.UUIDField(source='attendee.attendee_id', read_only=True)
    attendee_display_id = serializers.CharField(
        source='attendee.attendee_display_id', read_only=True
    )
    ticket_id = serializers.UUIDField(
        source='ticket.ticket_id', read_only=True, allow_null=True
    )
    ticket_code = serializers.CharField(
        source='ticket.ticket_code', read_only=True, allow_null=True
    )
    ticket_type_code = serializers.CharField(
        source='ticket.ticket_type.code', read_only=True, allow_null=True
    )
    venue_id = serializers.UUIDField(
        source='venue.event_venue_id', read_only=True, allow_null=True
    )
    venue_room_id = serializers.UUIDField(
        source='venue_room.id', read_only=True, allow_null=True
    )
    attendee_status = serializers.CharField(
        source='attendee_status_snapshot', read_only=True
    )
    area_from = serializers.CharField(
        source='attendee.area_from.area_name', read_only=True, allow_null=True
    )
    performed_by_id = serializers.IntegerField(
        source='performed_by.id', read_only=True, allow_null=True
    )

    class Meta:
        model = AttendeeCheckIn
        fields = (
            'check_in_id',
            'attendee_id',
            'attendee_display_id',
            'ticket_id',
            'ticket_code',
            'ticket_type_code',
            'action',
            'method',
            'scan_result',
            'venue_id',
            'venue_room_id',
            'has_outstanding_payments',
            'attendee_status',
            'area_from',
            'performed_at',
            'performed_by_id',
            'event_day',
        )
        read_only_fields = fields


# ============================================================================
# WS — INCOMING MESSAGE VALIDATION
# ============================================================================

class CheckInFilterSerializer(serializers.Serializer):
    """
    Validates the checkin.filter.set WS message data payload.

    All fields are optional — omitting a field means "no filter on this
    dimension".  The consumer stores the validated data as self.priority_filters
    and injects matches_priority_filter into every forwarded broadcast.
    """

    has_outstanding_payments = serializers.BooleanField(required=False, allow_null=True)
    attendee_status = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    ticket_type = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    area_from = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class CheckInHistoryRequestSerializer(serializers.Serializer):
    """Validates the checkin.history WS request."""

    cursor = serializers.IntegerField(required=False, min_value=0, default=0)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)


# ============================================================================
# ATTENDEE ROSTER — WS SERIALIZERS
# ============================================================================

class BulkDeleteCheckInsSerializer(serializers.Serializer):
    """Validates the DELETE /api/attendee/checkins/bulk-delete-logs/ request body."""

    event = serializers.UUIDField()
    date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text=(
            'Delete logs for this specific calendar date only. '
            'If omitted, all logs for the event are deleted.'
        ),
    )


class BulkAttendeeStatusUpdateSerializer(serializers.Serializer):
    """Validates the POST /api/attendee/checkins/bulk-status/ request body."""

    event = serializers.UUIDField()
    action = serializers.ChoiceField(choices=CheckInAction.choices)
    attendee_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        help_text=(
            'Specific attendees to update. '
            'Omit or send an empty list to act on all non-cancelled attendees in the event.'
        ),
    )


class AttendeeRosterFilterSerializer(serializers.Serializer):
    """
    Validates attendee.filter.set and the filters sub-field in
    attendee.list.request WS messages.

    Mirrors the fields of AttendeeFilterSet that are relevant for the live
    attendee roster so clients can send the same filter schema used in the
    HTTP participants dashboard.

    All fields are optional — omitting means no filter on that dimension.
    """
    # Roster-specific day filter (scope to a specific event day)
    day = serializers.IntegerField(required=False, allow_null=True)

    # Text search
    search = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    first_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    last_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # Demographics
    gender = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    age_min = serializers.IntegerField(required=False, allow_null=True)
    age_max = serializers.IntegerField(required=False, allow_null=True)
    is_minor = serializers.BooleanField(required=False, allow_null=True)

    # Location
    area_from = serializers.IntegerField(required=False, allow_null=True)
    area_from_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # Status
    is_checked_in = serializers.BooleanField(required=False, allow_null=True)
    is_cancelled = serializers.BooleanField(required=False, allow_null=True)
    is_registered = serializers.BooleanField(required=False, allow_null=True)
    is_event_staff = serializers.BooleanField(required=False, allow_null=True)

    # Organisation
    organisation = serializers.IntegerField(required=False, allow_null=True)
    organisation_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # Personal needs
    has_dietary_requirements = serializers.BooleanField(required=False, allow_null=True)
    has_medical_conditions = serializers.BooleanField(required=False, allow_null=True)
    has_accessibility_requirements = serializers.BooleanField(required=False, allow_null=True)
    has_emergency_contacts = serializers.BooleanField(required=False, allow_null=True)

    # Relationship
    relationship_to_user = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class AttendeeRosterRequestSerializer(serializers.Serializer):
    """Validates the attendee.list.request WS message."""
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)
    filters = AttendeeRosterFilterSerializer(required=False, default=dict)


class AttendeeRosterItemSerializer(serializers.Serializer):
    """
    Lightweight attendee row for the live roster table.

    Returned in attendee.list.response and attendee.updated WS messages.
    Annotated fields (last_check_in_at, event_day_last_seen) are expected
    to be set via queryset annotation before serialization.
    """
    attendee_id = serializers.UUIDField()
    attendee_display_id = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(allow_null=True)
    area_from_name = serializers.SerializerMethodField()
    status = serializers.CharField()
    is_checked_in = serializers.BooleanField()
    is_cancelled = serializers.BooleanField()
    last_check_in_at = serializers.DateTimeField(allow_null=True)
    event_day_last_seen = serializers.IntegerField(allow_null=True)
    ticket_type_code = serializers.SerializerMethodField()
    has_outstanding_payments = serializers.BooleanField()

    def get_full_name(self, obj) -> str:
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_area_from_name(self, obj) -> str | None:
        return obj.area_from.area_name if obj.area_from else None

    def get_ticket_type_code(self, obj) -> str | None:
        # Relies on select_related('booking__ticket_set__ticket_type') or similar
        try:
            ticket = obj.booking.tickets.filter(attendee=obj).select_related('ticket_type').first()
            return ticket.ticket_type.code if ticket and ticket.ticket_type else None
        except Exception:
            return None
