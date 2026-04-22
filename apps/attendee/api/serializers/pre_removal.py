"""Serializers for attendee pre-removal summary payloads."""

from rest_framework import serializers


class AttendeePreRemovalLinksSerializer(serializers.Serializer):
    self = serializers.CharField(required=False, allow_null=True)
    refund_requests = serializers.CharField(required=False, allow_null=True)
    method = serializers.CharField(required=False, allow_null=True)


class AttendeePreRemovalRefundSummarySerializer(serializers.Serializer):
    refund_id = serializers.CharField()
    tracking_reference = serializers.CharField()
    verification_status = serializers.CharField()
    is_active = serializers.BooleanField()
    amount = serializers.CharField()
    requested_at = serializers.CharField(required=False, allow_null=True)
    requested_by_name = serializers.CharField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class AttendeePreRemovalBlockerItemSerializer(serializers.Serializer):
    payment_id = serializers.CharField(required=False, allow_null=True)
    payment_reference = serializers.CharField(required=False, allow_null=True)
    payment_type = serializers.CharField(required=False, allow_null=True)
    payment_descriptor = serializers.CharField(required=False, allow_null=True)
    payment_status = serializers.CharField(required=False, allow_null=True)
    payment_status_bucket = serializers.CharField(required=False, allow_null=True)
    amount = serializers.CharField(required=False, allow_null=True)
    currency = serializers.CharField(required=False, allow_null=True)
    method_type = serializers.CharField(required=False, allow_null=True)
    method_title = serializers.CharField(required=False, allow_null=True)
    can_request_refund = serializers.BooleanField(required=False)
    refund_block_reason = serializers.CharField(required=False, allow_null=True)

    booking_id = serializers.CharField(required=False, allow_null=True)
    booking_reference = serializers.CharField(required=False, allow_null=True)
    booking_attendee_count = serializers.IntegerField(required=False)

    order_id = serializers.CharField(required=False, allow_null=True)
    order_reference = serializers.CharField(required=False, allow_null=True)
    order_status = serializers.CharField(required=False, allow_null=True)
    order_amount = serializers.CharField(required=False, allow_null=True)
    order_attendee_id = serializers.CharField(required=False, allow_null=True)
    order_attendee_name = serializers.CharField(required=False, allow_null=True)

    ticket_id = serializers.CharField(required=False, allow_null=True)
    ticket_code = serializers.CharField(required=False, allow_null=True)
    ticket_type = serializers.CharField(required=False, allow_null=True)
    ticket_scope = serializers.CharField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_null=True)

    event_id = serializers.CharField(required=False, allow_null=True)
    event_title = serializers.CharField(required=False, allow_null=True)
    check_in_time = serializers.CharField(required=False, allow_null=True)
    check_out_time = serializers.CharField(required=False, allow_null=True)
    attendance_id = serializers.CharField(required=False, allow_null=True)

    active_refunds = AttendeePreRemovalRefundSummarySerializer(many=True, required=False)
    active_refund_count = serializers.IntegerField(required=False)
    _links = AttendeePreRemovalLinksSerializer(required=False)


class AttendeePreRemovalBlockerPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()
    next_page = serializers.IntegerField(required=False, allow_null=True)
    previous_page = serializers.IntegerField(required=False, allow_null=True)


class AttendeePreRemovalBlockerSerializer(serializers.Serializer):
    code = serializers.CharField()
    severity = serializers.ChoiceField(choices=['critical', 'high', 'medium', 'low'])
    count = serializers.IntegerField()
    message = serializers.CharField()
    items = AttendeePreRemovalBlockerItemSerializer(many=True)
    pagination = AttendeePreRemovalBlockerPaginationSerializer(required=False)
    action_hint = serializers.CharField()


class AttendeePreRemovalSummaryAttendeeSerializer(serializers.Serializer):
    attendee_id = serializers.CharField()
    attendee_display_id = serializers.CharField()
    full_name = serializers.CharField()


class AttendeePreRemovalSummaryCountsSerializer(serializers.Serializer):
    linked_payments = serializers.IntegerField()
    outstanding_payments = serializers.IntegerField()
    active_refund_requests = serializers.IntegerField()
    active_tickets = serializers.IntegerField()
    unresolved_orders = serializers.IntegerField()
    open_attendance = serializers.IntegerField()
    family_memberships = serializers.IntegerField()


class AttendeePreRemovalSuggestedActionSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()


class AttendeePreRemovalSummarySerializer(serializers.Serializer):
    attendee = AttendeePreRemovalSummaryAttendeeSerializer()
    can_delete = serializers.BooleanField()
    blockers = AttendeePreRemovalBlockerSerializer(many=True)
    summary_counts = AttendeePreRemovalSummaryCountsSerializer()
    suggested_actions = AttendeePreRemovalSuggestedActionSerializer(many=True)
