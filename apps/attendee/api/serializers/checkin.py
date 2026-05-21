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
