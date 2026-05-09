"""Tests for pre-removal discriminated blocker item serialization."""

from django.test import SimpleTestCase

from apps.attendee.api.serializers import AttendeePreRemovalSummarySerializer


class PreRemovalSummarySerializerTests(SimpleTestCase):
    def _base_payload(self):
        return {
            'attendee': {
                'attendee_id': 'b093798a-26de-4308-ae53-cd4b51fef994',
                'attendee_display_id': 'ATT-1001',
                'full_name': 'Jane Doe',
            },
            'can_delete': False,
            'summary_counts': {
                'linked_payments': 1,
                'outstanding_payments': 1,
                'active_refund_requests': 0,
                'active_tickets': 0,
                'unresolved_orders': 0,
                'open_attendance': 0,
                'family_memberships': 0,
                'total_blockers': 1,
                'high_priority_blockers': 1,
                'medium_priority_blockers': 0,
            },
            'suggested_actions': [],
            'blockers': [],
        }

    def test_payment_item_serializes_with_type(self):
        payload = self._base_payload()
        payload['blockers'] = [
            {
                'code': 'outstanding_payments',
                'severity': 'high',
                'count': 1,
                'message': 'Has unresolved payments.',
                'action_hint': 'Resolve payment.',
                'pagination': {
                    'count': 1,
                    'page': 1,
                    'page_size': 20,
                    'total_pages': 1,
                    'has_next': False,
                    'has_previous': False,
                    'next_page': None,
                    'previous_page': None,
                },
                'items': [
                    {
                        'type': 'payment',
                        'payment_id': 'a71f29c8-95c8-43a8-93da-39507157b824',
                        'payment_reference': 'PAY-1001',
                        'payment_type': 'booking',
                        'payment_descriptor': 'Booking Payment',
                        'payment_status': 'COMPLETED',
                        'payment_status_bucket': 'settled',
                        'amount': '10.00',
                        'currency': 'GBP',
                        'method_type': 'CARD',
                        'method_title': 'Card',
                        'can_request_refund': True,
                        'refund_block_reason': None,
                        'booking_id': '1',
                        'booking_reference': 'BK-1',
                        'booking_attendee_count': 2,
                    }
                ],
            }
        ]

        serializer = AttendeePreRemovalSummarySerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['blockers'][0]['items'][0]['type'], 'payment')

    def test_ticket_item_rejects_order_field_leak(self):
        payload = self._base_payload()
        payload['blockers'] = [
            {
                'code': 'active_tickets',
                'severity': 'high',
                'count': 1,
                'message': 'Has active tickets.',
                'action_hint': 'Cancel ticket.',
                'items': [
                    {
                        'type': 'ticket',
                        'ticket_id': '32db82bc-f7a1-4d86-af75-124f71e95af5',
                        'ticket_code': 'TKT-1',
                        'ticket_type': 'General',
                        'ticket_scope': 'event',
                        'status': 'ACTIVE',
                        'payment_id': 'a71f29c8-95c8-43a8-93da-39507157b824',
                        'order_id': 'b8f12f6f-eaf1-489f-88aa-f3072116fa0f',
                    }
                ],
            }
        ]

        serializer = AttendeePreRemovalSummarySerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('blockers', serializer.errors)

    def test_order_item_serializes_with_type(self):
        payload = self._base_payload()
        payload['summary_counts']['unresolved_orders'] = 1
        payload['blockers'] = [
            {
                'code': 'unresolved_orders',
                'severity': 'medium',
                'count': 1,
                'message': 'Has unresolved orders.',
                'action_hint': 'Resolve order.',
                'items': [
                    {
                        'type': 'order',
                        'order_id': 'b8f12f6f-eaf1-489f-88aa-f3072116fa0f',
                        'order_reference': 'ORD-1',
                        'order_amount': '18.00',
                        'order_attendee_id': 'b093798a-26de-4308-ae53-cd4b51fef994',
                        'order_attendee_name': 'Jane Doe',
                        'status': 'PENDING',
                        'payment_id': 'a71f29c8-95c8-43a8-93da-39507157b824',
                    }
                ],
            }
        ]

        serializer = AttendeePreRemovalSummarySerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['blockers'][0]['items'][0]['type'], 'order')

    def test_order_item_requires_type_discriminator(self):
        payload = self._base_payload()
        payload['blockers'] = [
            {
                'code': 'unresolved_orders',
                'severity': 'medium',
                'count': 1,
                'message': 'Has unresolved orders.',
                'action_hint': 'Resolve order.',
                'items': [
                    {
                        'order_id': 'b8f12f6f-eaf1-489f-88aa-f3072116fa0f',
                        'order_reference': 'ORD-1',
                        'order_amount': '18.00',
                        'order_attendee_id': 'b093798a-26de-4308-ae53-cd4b51fef994',
                        'order_attendee_name': 'Jane Doe',
                        'status': 'PENDING',
                    }
                ],
            }
        ]

        serializer = AttendeePreRemovalSummarySerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('blockers', serializer.errors)
