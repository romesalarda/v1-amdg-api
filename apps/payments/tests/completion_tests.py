"""Tests for explicit payment completion / fulfilment (replaces the old post_save signal)."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from djmoney.money import Money

from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation
from apps.payments.models import Payment, PaymentMethod, PaymentMethodTypeChoices, PaymentStatusChoices
from apps.payments.services import completion
from apps.payments.services.completion import (
    complete_payment,
    fulfil_outstanding_payments,
    fulfil_payment,
)
from django.contrib.auth import get_user_model

User = get_user_model()


class PaymentFulfilmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='u', email='u@example.com', password='x')
        event_type = EventType.objects.create(title='Conf', code='CONF', created_by=cls.user)
        org = Organisation.objects.create(title='Org', created_by=cls.user)
        cls.event = Event.objects.create(
            title='Ev', display_code='EV2026', display_identifier='EV2026CONF001',
            created_by=cls.user, event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN, organisation=org,
        )
        cls.method = PaymentMethod.objects.create(
            event=cls.event, method_type=PaymentMethodTypeChoices.STRIPE,
            title='Card', is_active=True, created_by=cls.user,
        )

    def _payment(self, status=PaymentStatusChoices.PENDING):
        return Payment.objects.create(
            user=self.user, event=self.event, method=self.method,
            base_amount=Money(10, 'GBP'), status=status,
        )

    def test_saving_completed_payment_has_no_side_effects(self):
        payment = self._payment(PaymentStatusChoices.COMPLETED)
        with patch.object(completion, '_run_fulfilment') as run:
            payment.save()
        run.assert_not_called()
        payment.refresh_from_db()
        self.assertIsNone(payment.fulfilled_at)

    def test_complete_payment_schedules_fulfilment_on_commit(self):
        payment = self._payment()
        with patch.object(completion, '_run_fulfilment') as run:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                complete_payment(payment)
        self.assertEqual(len(callbacks), 1)
        run.assert_called_once()
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertIsNotNone(payment.fulfilled_at)

    def test_fulfilment_is_idempotent(self):
        payment = self._payment(PaymentStatusChoices.COMPLETED)
        with patch.object(completion, '_run_fulfilment') as run:
            self.assertTrue(fulfil_payment(payment.pk))
            self.assertFalse(fulfil_payment(payment.pk))
        run.assert_called_once()

    def test_non_completed_payment_is_skipped(self):
        payment = self._payment()
        with patch.object(completion, '_run_fulfilment') as run:
            self.assertFalse(fulfil_payment(payment.pk))
        run.assert_not_called()

    def test_failure_flags_manual_review_and_leaves_unfulfilled(self):
        payment = self._payment(PaymentStatusChoices.COMPLETED)
        with patch.object(completion, '_run_fulfilment', side_effect=RuntimeError('boom')):
            self.assertFalse(fulfil_payment(payment.pk))
        payment.refresh_from_db()
        self.assertIsNone(payment.fulfilled_at)
        self.assertTrue(payment.metadata['requires_manual_review'])
        self.assertEqual(payment.metadata['processing_error'], 'boom')

    def test_sweeper_retries_stale_unfulfilled_but_skips_flagged_and_fresh(self):
        stale = self._payment(PaymentStatusChoices.COMPLETED)
        flagged = self._payment(PaymentStatusChoices.COMPLETED)
        fresh = self._payment(PaymentStatusChoices.COMPLETED)
        old = timezone.now() - timedelta(hours=1)
        Payment.objects.filter(pk__in=[stale.pk, flagged.pk]).update(updated_at=old)
        Payment.objects.filter(pk=flagged.pk).update(metadata={'requires_manual_review': True})

        with patch.object(completion, '_run_fulfilment'):
            result = fulfil_outstanding_payments()

        self.assertEqual(result['fulfilled'], 1)
        stale.refresh_from_db(); flagged.refresh_from_db(); fresh.refresh_from_db()
        self.assertIsNotNone(stale.fulfilled_at)
        self.assertIsNone(flagged.fulfilled_at)
        self.assertIsNone(fresh.fulfilled_at)
