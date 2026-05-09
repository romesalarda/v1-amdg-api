"""Serializers for attendee pre-removal summary payloads."""

from rest_framework import serializers
from drf_spectacular.utils import (
    PolymorphicProxySerializer,
    extend_schema_field,
    extend_schema_serializer,
)


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


class StrictFieldsSerializer(serializers.Serializer):
    """Serializer that rejects unknown fields for stricter union item validation."""

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('Expected an object for blocker item.')

        unknown_fields = set(data.keys()) - set(self.fields.keys())
        if unknown_fields:
            raise serializers.ValidationError(
                {
                    key: ['Unexpected field for blocker item type.']
                    for key in sorted(unknown_fields)
                }
            )

        return super().to_internal_value(data)


class PaymentContextSerializer(StrictFieldsSerializer):
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


@extend_schema_serializer(component_name='PaymentBlockerItem')
class PaymentBlockerItemSerializer(PaymentContextSerializer):
    type = serializers.ChoiceField(choices=['payment'])


@extend_schema_serializer(component_name='TicketBlockerItem')
class TicketBlockerItemSerializer(PaymentContextSerializer):
    type = serializers.ChoiceField(choices=['ticket'])
    ticket_id = serializers.CharField()
    ticket_code = serializers.CharField(required=False, allow_null=True)
    ticket_type = serializers.CharField(required=False, allow_null=True)
    ticket_scope = serializers.CharField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_null=True)


@extend_schema_serializer(component_name='OrderBlockerItem')
class OrderBlockerItemSerializer(PaymentContextSerializer):
    type = serializers.ChoiceField(choices=['order'])
    order_id = serializers.CharField()
    order_reference = serializers.CharField(required=False, allow_null=True)
    order_amount = serializers.CharField(required=False, allow_null=True)
    order_attendee_id = serializers.CharField(required=False, allow_null=True)
    order_attendee_name = serializers.CharField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_null=True)


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name='AttendeePreRemovalBlockerItemUnion',
        serializers=[
            PaymentBlockerItemSerializer,
            TicketBlockerItemSerializer,
            OrderBlockerItemSerializer,
        ],
        resource_type_field_name='type',
        many=True,
    )
)
class AttendeePreRemovalBlockerItemsField(serializers.ListField):
    """Discriminated list of blocker items keyed by the item `type` field."""

    default_error_messages = {
        'invalid_type': 'Blocker item type must be one of: payment, ticket, order.',
        'missing_type': 'Blocker item must include a type discriminator.',
    }

    item_serializer_map = {
        'payment': PaymentBlockerItemSerializer,
        'ticket': TicketBlockerItemSerializer,
        'order': OrderBlockerItemSerializer,
    }

    def _select_serializer_class(self, item):
        item_type = item.get('type') if isinstance(item, dict) else None
        if not item_type:
            self.fail('missing_type')

        serializer_class = self.item_serializer_map.get(item_type)
        if not serializer_class:
            self.fail('invalid_type')
        return serializer_class

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError('Expected a list of blocker items.')

        validated_items = []
        item_errors = {}
        for index, item in enumerate(data):
            try:
                serializer_class = self._select_serializer_class(item)
                serializer = serializer_class(data=item)
                serializer.is_valid(raise_exception=True)
                validated_items.append(serializer.validated_data)
            except serializers.ValidationError as exc:
                item_errors[index] = exc.detail

        if item_errors:
            raise serializers.ValidationError(item_errors)

        return validated_items

    def to_representation(self, data):
        return [self._serialize_item(item) for item in data]

    def _serialize_item(self, item):
        serializer_class = self._select_serializer_class(item)
        return serializer_class(item).data


class AttendeePreRemovalBlockerItemSerializer(StrictFieldsSerializer):
    """Backward-compatible alias serializer for external imports."""

    type = serializers.ChoiceField(choices=['payment', 'ticket', 'order'])


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
    items = AttendeePreRemovalBlockerItemsField()
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
    total_blockers = serializers.IntegerField(required=False)
    high_priority_blockers = serializers.IntegerField(required=False)
    medium_priority_blockers = serializers.IntegerField(required=False)


class AttendeePreRemovalSuggestedActionSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()


class AttendeePreRemovalSummarySerializer(serializers.Serializer):
    attendee = AttendeePreRemovalSummaryAttendeeSerializer()
    can_delete = serializers.BooleanField()
    blockers = AttendeePreRemovalBlockerSerializer(many=True)
    summary_counts = AttendeePreRemovalSummaryCountsSerializer()
    suggested_actions = AttendeePreRemovalSuggestedActionSerializer(many=True)
