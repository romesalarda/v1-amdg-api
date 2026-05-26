"""
Comprehensive tests for Stripe integration.

Tests cover:
- PaymentIntent creation and retrieval
- Webhook signature verification
- Webhook event processing
- Idempotency
- Refund flow
- Error handling
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, Mock, MagicMock
from datetime import timedelta
from decimal import Decimal
from djmoney.money import Money
import stripe

from apps.payments.models import (
    Payment, PaymentStatusChoices, PaymentMethod, PaymentMethodTypeChoices,
    RefundRequest, PaymentHistoryAction, StripeConnectedAccount
)
from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.connect import StripeConnectService
from apps.payments.services.stripe.payment_intents import PaymentIntentService
from apps.payments.services.stripe.refunds import RefundService
from apps.payments.services.stripe.webhooks import (
    verify_webhook_signature,
    process_webhook_event,
    PaymentIntentSucceededHandler,
    PaymentIntentPaymentFailedHandler,
    PaymentIntentCanceledHandler,
    ChargeRefundedHandler
)
from apps.payments.services.stripe.exceptions import (
    StripePaymentError,
    StripeValidationError,
    StripeWebhookError
)
from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation
from apps.products.models import Order, OrderStatusChoices
from apps.common.models.verification import VerificationStatus

User = get_user_model()


class StripeClientTestCase(TestCase):
    """Test Stripe client initialization and configuration."""
    
    def test_client_initialization(self):
        """Test that StripeClient initializes correctly."""
        StripeClient.initialize()
        self.assertTrue(StripeClient._initialized)
        self.assertIsNotNone(stripe.api_key)
    
    def test_is_test_mode(self):
        """Test test mode detection."""
        StripeClient.initialize()
        # Should be True in test environment
        self.assertTrue(StripeClient.is_test_mode())
    
    def test_get_publishable_key(self):
        """Test publishable key retrieval."""
        key = StripeClient.get_publishable_key()
        self.assertIsNotNone(key)
        # Test keys start with pk_test_
        if StripeClient.is_test_mode():
            self.assertTrue(key.startswith('pk_test_') or key == '')


class PaymentIntentServiceTestCase(TestCase):
    """Test PaymentIntent service methods."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Test Event Type',
            code='TEST',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            display_identifier='TE2025TEST001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
            is_active=True,
            created_by=self.user
        )
        self.stripe_account_id = 'acct_test123'
    
    @patch('stripe.PaymentIntent.create')
    def test_create_payment_intent_success(self, mock_create):
        """Test successful PaymentIntent creation."""
        # Mock Stripe response
        mock_payment_intent = Mock()
        mock_payment_intent.id = 'pi_test123'
        mock_payment_intent.client_secret = 'pi_test123_secret_abc'
        mock_payment_intent.status = 'requires_payment_method'
        mock_create.return_value = mock_payment_intent
        
        # Create PaymentIntent
        payment_intent = PaymentIntentService.create(
            amount=Money(50, 'GBP'),
            currency='GBP',
            payment_reference='PAY-TEST-001',
            metadata={'test': 'data'},
            customer_email='test@example.com',
            description='Test payment',
            stripe_account_id=self.stripe_account_id,
        )
        
        # Assert
        self.assertEqual(payment_intent.id, 'pi_test123')
        self.assertEqual(payment_intent.client_secret, 'pi_test123_secret_abc')
        
        # Verify Stripe API was called correctly
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs['amount'], 5000)  # 50 GBP in pence
        self.assertEqual(call_kwargs['currency'], 'gbp')
        self.assertEqual(call_kwargs['metadata'], {'test': 'data'})
        self.assertEqual(call_kwargs['idempotency_key'], 'PAY-TEST-001')

    @patch('stripe.PaymentIntent.create')
    def test_create_payment_intent_with_connected_account(self, mock_create):
        """Test PaymentIntent creation passes the connected Stripe account."""
        mock_payment_intent = Mock()
        mock_payment_intent.id = 'pi_test123'
        mock_payment_intent.client_secret = 'pi_test123_secret_abc'
        mock_payment_intent.status = 'requires_payment_method'
        mock_create.return_value = mock_payment_intent

        payment_intent = PaymentIntentService.create(
            amount=Money(50, 'GBP'),
            currency='GBP',
            payment_reference='PAY-TEST-004',
            metadata={'test': 'data'},
            customer_email='test@example.com',
            description='Test payment',
            stripe_account_id='acct_test123',
        )

        self.assertEqual(payment_intent.id, 'pi_test123')
        self.assertEqual(mock_create.call_args[1]['stripe_account'], 'acct_test123')
    
    @patch('stripe.PaymentIntent.create')
    def test_create_payment_intent_invalid_amount(self, mock_create):
        """Test PaymentIntent creation with invalid amount."""
        with self.assertRaises(StripeValidationError) as cm:
            PaymentIntentService.create(
                amount=Money(0, 'GBP'),
                currency='GBP',
                payment_reference='PAY-TEST-002',
                metadata={}
            )
        
        self.assertIn('Invalid amount', str(cm.exception))
        mock_create.assert_not_called()
    
    @patch('stripe.PaymentIntent.create')
    def test_create_payment_intent_stripe_error(self, mock_create):
        """Test PaymentIntent creation with Stripe error."""
        # Create a mock CardError that inherits from stripe.CardError
        mock_error = stripe.CardError(
            'Your card was declined',
            param='card',
            code='card_declined'
        )
        mock_create.side_effect = mock_error
        
        with self.assertRaises(StripePaymentError) as cm:
            PaymentIntentService.create(
                amount=Money(50, 'GBP'),
                currency='GBP',
                payment_reference='PAY-TEST-003',
                metadata={},
                stripe_account_id=self.stripe_account_id,
            )
        
        self.assertIn('card', str(cm.exception.user_message).lower())
    
    @patch('stripe.PaymentIntent.retrieve')
    def test_retrieve_payment_intent(self, mock_retrieve):
        """Test PaymentIntent retrieval."""
        mock_payment_intent = Mock()
        mock_payment_intent.id = 'pi_test123'
        mock_payment_intent.status = 'succeeded'
        mock_retrieve.return_value = mock_payment_intent
        
        payment_intent = PaymentIntentService.retrieve('pi_test123', stripe_account_id=self.stripe_account_id)
        
        self.assertEqual(payment_intent.id, 'pi_test123')
        self.assertEqual(payment_intent.status, 'succeeded')
        mock_retrieve.assert_called_once_with('pi_test123', stripe_account='acct_test123')
    
    @patch('stripe.PaymentIntent.cancel')
    def test_cancel_payment_intent(self, mock_cancel):
        """Test PaymentIntent cancellation."""
        mock_payment_intent = Mock()
        mock_payment_intent.id = 'pi_test123'
        mock_payment_intent.status = 'canceled'
        mock_cancel.return_value = mock_payment_intent
        
        payment_intent = PaymentIntentService.cancel(
            'pi_test123',
            'requested_by_customer',
            stripe_account_id=self.stripe_account_id,
        )
        
        self.assertEqual(payment_intent.status, 'canceled')
        mock_cancel.assert_called_once()


class RefundServiceTestCase(TestCase):
    """Test Refund service methods."""
    
    @patch('stripe.Refund.create')
    def test_create_refund_full_amount(self, mock_create):
        """Test full refund creation."""
        mock_refund = Mock()
        mock_refund.id = 're_test123'
        mock_refund.status = 'succeeded'
        mock_refund.amount = 5000
        mock_create.return_value = mock_refund
        
        refund = RefundService.create(
            payment_intent_id='pi_test123',
            reason=RefundService.REASON_REQUESTED_BY_CUSTOMER,
            stripe_account_id='acct_test123'
        )
        
        self.assertEqual(refund.id, 're_test123')
        self.assertEqual(refund.status, 'succeeded')
        
        # Verify no amount specified (full refund)
        call_kwargs = mock_create.call_args[1]
        self.assertNotIn('amount', call_kwargs)
    
    @patch('stripe.Refund.create')
    def test_create_refund_partial_amount(self, mock_create):
        """Test partial refund creation."""
        mock_refund = Mock()
        mock_refund.id = 're_test123'
        mock_refund.status = 'succeeded'
        mock_refund.amount = 2000
        mock_create.return_value = mock_refund
        
        refund = RefundService.create(
            payment_intent_id='pi_test123',
            amount=Money(20, 'GBP'),
            reason=RefundService.REASON_REQUESTED_BY_CUSTOMER,
            refund_reference='REF-TEST-001',
            stripe_account_id='acct_test123'
        )
        
        self.assertEqual(refund.id, 're_test123')
        
        # Verify amount and idempotency key
        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs['amount'], 2000)
        self.assertEqual(call_kwargs['idempotency_key'], 'REF-TEST-001')

    @patch('stripe.Refund.create')
    def test_create_refund_with_connected_account(self, mock_create):
        """Test refund creation passes the connected Stripe account."""
        mock_refund = Mock()
        mock_refund.id = 're_test123'
        mock_refund.status = 'succeeded'
        mock_refund.amount = 5000
        mock_create.return_value = mock_refund

        refund = RefundService.create(
            payment_intent_id='pi_test123',
            reason=RefundService.REASON_REQUESTED_BY_CUSTOMER,
            stripe_account_id='acct_test123'
        )

        self.assertEqual(refund.id, 're_test123')
        self.assertEqual(mock_create.call_args[1]['stripe_account'], 'acct_test123')
    
    @patch('stripe.Refund.create')
    def test_create_refund_invalid_amount(self, mock_create):
        """Test refund creation with invalid amount."""
        with self.assertRaises(StripeValidationError):
            RefundService.create(
                payment_intent_id='pi_test123',
                amount=Money(0, 'GBP')
            )
        
        mock_create.assert_not_called()


class StripeConnectServiceTestCase(TestCase):
    """Test Stripe Connect account service helpers."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='connectuser',
            email='connect@example.com',
            password='testpass123'
        )

        self.event_type = EventType.objects.create(
            title='Connect Event Type',
            code='CONNECT',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Connect Org',
            created_by=self.user
        )

        self.event = Event.objects.create(
            title='Connect Event',
            display_code='CE2025',
            display_identifier='CE2025CONNECT001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )

    @patch('stripe.Account.create')
    def test_create_or_refresh_account_creates_local_record(self, mock_create):
        """Creating a connected account should persist the Stripe account ID locally."""
        mock_account = Mock()
        mock_account.id = 'acct_test123'
        mock_account.type = 'express'
        mock_account.country = 'GB'
        mock_account.email = 'connect@example.com'
        mock_account.business_type = 'individual'
        mock_account.charges_enabled = False
        mock_account.payouts_enabled = False
        mock_account.details_submitted = False
        mock_account.requirements = {'disabled_reason': ''}
        mock_account.capabilities = {'card_payments': {'requested': True}}
        mock_account.metadata = {}
        mock_create.return_value = mock_account

        account_record, stripe_account = StripeConnectService.create_or_refresh_account(self.user)

        self.assertEqual(account_record.stripe_account_id, 'acct_test123')
        self.assertEqual(stripe_account.id, 'acct_test123')
        self.assertTrue(StripeConnectedAccount.objects.filter(user=self.user, stripe_account_id='acct_test123').exists())

    def test_resolve_payment_method_stripe_account_id(self):
        """The helper should read stripe_account_id from payment method details."""
        payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe with account',
            is_active=True,
            created_by=self.user,
            provided_details={'stripe_account_id': 'acct_test456'}
        )

        stripe_account_id = StripeConnectService.resolve_payment_method_stripe_account_id(payment_method)

        self.assertEqual(stripe_account_id, 'acct_test456')

    def test_first_account_defaults_to_primary(self):
        """The first Stripe account for a user should automatically become primary."""
        account = StripeConnectedAccount.objects.create(
            user=self.user,
            stripe_account_id='acct_primary_default_1',
        )

        self.assertTrue(account.is_primary)

    def test_set_primary_unsets_other_accounts(self):
        """Setting one account as primary should unset all other accounts for the same user."""
        first = StripeConnectedAccount.objects.create(
            user=self.user,
            stripe_account_id='acct_primary_switch_1',
            is_primary=True,
        )
        second = StripeConnectedAccount.objects.create(
            user=self.user,
            stripe_account_id='acct_primary_switch_2',
            is_primary=False,
        )

        StripeConnectService.set_primary(second)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

    def test_get_user_account_prefers_active_primary(self):
        """User account resolution should prefer active primary accounts first."""
        older = StripeConnectedAccount.objects.create(
            user=self.user,
            stripe_account_id='acct_resolution_older',
            is_active=True,
            is_primary=False,
        )
        preferred = StripeConnectedAccount.objects.create(
            user=self.user,
            stripe_account_id='acct_resolution_primary',
            is_active=True,
            is_primary=True,
        )
        StripeConnectedAccount.objects.create(
            user=self.user,
            stripe_account_id='acct_resolution_inactive',
            is_active=False,
            is_primary=True,
        )

        resolved = StripeConnectService.get_user_account(self.user)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.pk, preferred.pk)
        self.assertNotEqual(resolved.pk, older.pk)


class WebhookTestCase(TestCase):
    """Test webhook signature verification and event processing."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='webhookuser',
            email='webhook@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Webhook Event Type',
            code='WEBHOOK',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Webhook Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Webhook Event',
            display_code='WE2025',
            display_identifier='WE2025WEBHOOK001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
            is_active=True,
            created_by=self.user
        )
        
        self.payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            stripe_payment_intent='pi_test123'
        )
    
    @patch('stripe.Webhook.construct_event')
    def test_verify_webhook_signature_success(self, mock_construct):
        """Test successful webhook signature verification."""
        mock_event = Mock()
        mock_event.id = 'evt_test123'
        mock_event.type = 'payment_intent.succeeded'
        mock_construct.return_value = mock_event
        
        event = verify_webhook_signature(b'test payload', 'test_signature')
        
        self.assertEqual(event.id, 'evt_test123')
        mock_construct.assert_called_once()
    
    @patch('stripe.Webhook.construct_event')
    def test_verify_webhook_signature_failure(self, mock_construct):
        """Test webhook signature verification failure."""
        # Create a mock SignatureVerificationError exception class
        class MockSignatureVerificationError(Exception):
            def __init__(self, message, sig_header=None):
                super().__init__(message)
                self.sig_header = sig_header
        
        MockSignatureVerificationError.__name__ = 'SignatureVerificationError'
        mock_construct.side_effect = MockSignatureVerificationError(
            'Invalid signature',
            sig_header='bad_signature'
        )
        
        with self.assertRaises(StripeWebhookError):
            verify_webhook_signature(b'test payload', 'bad_signature')
    
    def test_payment_intent_succeeded_handler(self):
        """Test payment_intent.succeeded webhook handler."""
        # Create mock event
        mock_event = Mock()
        mock_event.id = 'evt_test123'
        mock_event.type = 'payment_intent.succeeded'
        mock_event.data = Mock()
        mock_event.data.object = Mock()
        mock_event.data.object.id = 'pi_test123'
        mock_event.data.object.latest_charge = 'ch_test123'
        mock_event.data.object.amount_received = 5000
        mock_event.data.object.currency = 'gbp'
        
        # Process event
        handler = PaymentIntentSucceededHandler(mock_event)
        result = handler.handle()
        
        # Assert
        self.assertEqual(result['status'], 'success')
        
        # Verify payment updated
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(self.payment.stripe_charge_id, 'ch_test123')
        
        # Verify history action created
        self.assertTrue(
            PaymentHistoryAction.objects.filter(
                payment=self.payment,
                action='webhook_payment_succeeded'
            ).exists()
        )
    
    def test_payment_intent_succeeded_handler_idempotency(self):
        """Test idempotency of payment_intent.succeeded handler."""
        # First event
        mock_event1 = Mock()
        mock_event1.id = 'evt_test123'
        mock_event1.type = 'payment_intent.succeeded'
        mock_event1.data = Mock()
        mock_event1.data.object = Mock()
        mock_event1.data.object.id = 'pi_test123'
        mock_event1.data.object.latest_charge = 'ch_test123'
        mock_event1.data.object.amount_received = 5000
        mock_event1.data.object.currency = 'gbp'
        
        handler1 = PaymentIntentSucceededHandler(mock_event1)
        result1 = handler1.handle()
        self.assertEqual(result1['status'], 'success')
        
        # Second event (duplicate)
        handler2 = PaymentIntentSucceededHandler(mock_event1)
        result2 = handler2.handle()
        self.assertEqual(result2['status'], 'already_processed')
        
        # Payment should still be COMPLETED
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatusChoices.COMPLETED)

    def test_charge_refunded_handler_without_refunds_attribute(self):
        """charge.refunded payloads without refunds list should still process via amount_refunded."""
        # Arrange payment state for full refund transition
        self.payment.status = PaymentStatusChoices.COMPLETED
        self.payment.stripe_charge_id = 'ch_test123'
        self.payment.save(update_fields=['status', 'stripe_charge_id'])

        mock_event = Mock()
        mock_event.id = 'evt_refund_no_list'
        mock_event.type = 'charge.refunded'
        mock_event.data = Mock()
        mock_event.data.object = Mock()
        mock_event.data.object.id = 'ch_test123'
        mock_event.data.object.amount_refunded = 5000
        # Intentionally no .refunds attribute

        handler = ChargeRefundedHandler(mock_event)

        # Act
        result = handler.handle()

        # Assert
        self.assertEqual(result['status'], 'success')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatusChoices.REFUNDED)


class IdempotencyTestCase(TestCase):
    """Test idempotency of payment operations."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='idempuser',
            email='idemp@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Idemp Event Type',
            code='IDEMP',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Idemp Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Idemp Event',
            display_code='IE2025',
            display_identifier='IE2025IDEMP001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
            is_active=True,
            created_by=self.user
        )

        self.stripe_account_id = 'acct_test123'
    
    @patch('stripe.PaymentIntent.create')
    def test_payment_intent_creation_idempotency(self, mock_create):
        """Test that same idempotency key returns same PaymentIntent."""
        mock_payment_intent = Mock()
        mock_payment_intent.id = 'pi_test123'
        mock_payment_intent.client_secret = 'pi_test123_secret'
        mock_create.return_value = mock_payment_intent
        
        # Create first PaymentIntent
        pi1 = PaymentIntentService.create(
            amount=Money(50, 'GBP'),
            currency='GBP',
            payment_reference='PAY-IDEMP-001',
            metadata={},
            stripe_account_id=self.stripe_account_id,
        )
        
        # Create second PaymentIntent with same idempotency key
        pi2 = PaymentIntentService.create(
            amount=Money(50, 'GBP'),
            currency='GBP',
            payment_reference='PAY-IDEMP-001',  # Same key
            metadata={},
            stripe_account_id=self.stripe_account_id,
        )
        
        # Both should return same PaymentIntent ID
        self.assertEqual(pi1.id, pi2.id)
        
        # Stripe API should be called twice (Stripe handles idempotency)
        self.assertEqual(mock_create.call_count, 2)
        
        # Both calls should have same idempotency key
        call1_kwargs = mock_create.call_args_list[0][1]
        call2_kwargs = mock_create.call_args_list[1][1]
        self.assertEqual(
            call1_kwargs['idempotency_key'],
            call2_kwargs['idempotency_key']
        )


class PaymentModelTestCase(TestCase):
    """Test Payment model Stripe-specific methods."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='modeluser',
            email='model@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Model Event Type',
            code='MODEL',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Model Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Model Event',
            display_code='ME2025',
            display_identifier='ME2025MODEL001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
            is_active=True,
            created_by=self.user
        )
    
    def test_prepare_stripe_metadata(self):
        """Test metadata preparation for Stripe."""
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.DRAFTING
        )
        
        metadata = payment.prepare_stripe_metadata()
        
        # Assert required fields
        self.assertIn('payment_id', metadata)
        self.assertIn('payment_reference', metadata)
        self.assertIn('event_id', metadata)
        self.assertIn('user_email', metadata)
        
        # Assert values are strings (Stripe requirement)
        for key, value in metadata.items():
            self.assertIsInstance(key, str)
            self.assertTrue(
                isinstance(value, (str, int, bool)),
                f"Value for {key} must be string, int, or bool"
            )
    
    def test_transition_to_valid(self):
        """Test valid status transition."""
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.DRAFTING
        )
        
        # Valid transition
        payment.transition_to(PaymentStatusChoices.PENDING)
        self.assertEqual(payment.status, PaymentStatusChoices.PENDING)
    
    def test_transition_to_invalid(self):
        """Test invalid status transition."""
        from django.core.exceptions import ValidationError
        
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.DRAFTING
        )
        
        # Invalid transition (can't go directly to COMPLETED)
        with self.assertRaises(ValidationError):
            payment.transition_to(PaymentStatusChoices.COMPLETED)
    
    def test_transition_to_idempotent(self):
        """Test that transitioning to same status is idempotent."""
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.PENDING
        )
        
        # Transition to same status should be no-op
        payment.transition_to(PaymentStatusChoices.PENDING)
        self.assertEqual(payment.status, PaymentStatusChoices.PENDING)


class WebhookFailurePathTestCase(TestCase):
    """
    Integrity tests for webhook failure/cancellation paths.

    Verifies that:
    - payment_intent.payment_failed marks payment FAILED and cancels linked open Order
    - payment_intent.canceled marks payment CANCELLED and cancels linked open Order
    - Duplicate failed/canceled events are idempotent (already_processed returned)
    - Unknown payment_intent_id is gracefully ignored (no crash, 'ignored' status)
    - Duplicate payment_intent.succeeded with different event ID is also idempotent
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='wh_failpath_user',
            email='wh_failpath@example.com',
            password='pass12345',
        )
        self.event_type = EventType.objects.create(
            title='Fail Path Event Type',
            code='WHFP',
            created_by=self.user,
        )
        self.organisation = Organisation.objects.create(
            title='Fail Path Org',
            created_by=self.user,
        )
        self.django_event = Event.objects.create(
            title='Fail Path Event',
            display_code='FPEV26',
            display_identifier='FPEV26FAILPATH001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )
        self.payment_method = PaymentMethod.objects.create(
            event=self.django_event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
            is_active=True,
            created_by=self.user,
        )
        self.payment = Payment.objects.create(
            user=self.user,
            event=self.django_event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            stripe_payment_intent='pi_failpath001',
        )
        self.order = Order.objects.create(
            customer=self.user,
            status=OrderStatusChoices.PENDING,
            total_amount=Money(50, 'GBP'),
            created_by=self.user,
            payment=self.payment,
        )

    # ------------------------------------------------------------------
    # payment_intent.payment_failed
    # ------------------------------------------------------------------

    def _make_failed_event(self, event_id='evt_failed_001', pi_id='pi_failpath001'):
        mock_event = Mock()
        mock_event.id = event_id
        mock_event.type = 'payment_intent.payment_failed'
        mock_event.account = None
        mock_event.data = Mock()
        mock_event.data.object = Mock()
        mock_event.data.object.id = pi_id
        mock_event.data.object.last_payment_error = {'message': 'Your card was declined.'}
        return mock_event

    def _make_canceled_event(self, event_id='evt_canceled_001', pi_id='pi_failpath001'):
        mock_event = Mock()
        mock_event.id = event_id
        mock_event.type = 'payment_intent.canceled'
        mock_event.account = None
        mock_event.data = Mock()
        mock_event.data.object = Mock()
        mock_event.data.object.id = pi_id
        mock_event.data.object.cancellation_reason = 'requested_by_customer'
        return mock_event

    def test_payment_failed_handler_marks_payment_failed(self):
        """payment_intent.payment_failed should set payment status to FAILED."""
        handler = PaymentIntentPaymentFailedHandler(self._make_failed_event())
        result = handler.handle()

        self.assertEqual(result['status'], 'success')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatusChoices.FAILED)

    def test_payment_failed_cancels_linked_order(self):
        """Order should be cancelled after a payment failure to restore reserved stock."""
        handler = PaymentIntentPaymentFailedHandler(self._make_failed_event())
        handler.handle()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatusChoices.CANCELLED)

    def test_payment_failed_history_action_created(self):
        """A PaymentHistoryAction should be recorded for the failure."""
        handler = PaymentIntentPaymentFailedHandler(self._make_failed_event())
        handler.handle()

        self.assertTrue(
            PaymentHistoryAction.objects.filter(
                payment=self.payment,
                action='webhook_payment_failed',
            ).exists()
        )

    def test_payment_failed_idempotency_same_event_id(self):
        """Replaying the same failed event id should return already_processed."""
        handler = PaymentIntentPaymentFailedHandler(self._make_failed_event())
        first = handler.handle()
        self.assertEqual(first['status'], 'success')

        handler2 = PaymentIntentPaymentFailedHandler(self._make_failed_event())
        second = handler2.handle()
        self.assertEqual(second['status'], 'already_processed')

    def test_payment_failed_idempotency_already_failed_status(self):
        """If payment is already FAILED when the event arrives, return already_processed."""
        self.payment.status = PaymentStatusChoices.FAILED
        self.payment.save(update_fields=['status'])

        handler = PaymentIntentPaymentFailedHandler(
            self._make_failed_event(event_id='evt_failed_002')
        )
        result = handler.handle()
        self.assertEqual(result['status'], 'already_processed')

    # ------------------------------------------------------------------
    # payment_intent.canceled
    # ------------------------------------------------------------------

    def test_payment_canceled_handler_marks_payment_cancelled(self):
        """payment_intent.canceled should set payment status to CANCELLED."""
        handler = PaymentIntentCanceledHandler(self._make_canceled_event())
        result = handler.handle()

        self.assertEqual(result['status'], 'success')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatusChoices.CANCELLED)

    def test_payment_canceled_cancels_linked_order(self):
        """Order should be cancelled after payment cancellation to restore reserved stock."""
        handler = PaymentIntentCanceledHandler(self._make_canceled_event())
        handler.handle()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatusChoices.CANCELLED)

    def test_payment_canceled_history_action_created(self):
        """A PaymentHistoryAction should be recorded for the cancellation."""
        handler = PaymentIntentCanceledHandler(self._make_canceled_event())
        handler.handle()

        self.assertTrue(
            PaymentHistoryAction.objects.filter(
                payment=self.payment,
                action='webhook_payment_canceled',
            ).exists()
        )

    def test_payment_canceled_idempotency_same_event_id(self):
        """Replaying the same canceled event id should return already_processed."""
        handler = PaymentIntentCanceledHandler(self._make_canceled_event())
        first = handler.handle()
        self.assertEqual(first['status'], 'success')

        handler2 = PaymentIntentCanceledHandler(self._make_canceled_event())
        second = handler2.handle()
        self.assertEqual(second['status'], 'already_processed')

    def test_payment_canceled_idempotency_already_cancelled_status(self):
        """If payment is already CANCELLED when the event arrives, return already_processed."""
        self.payment.status = PaymentStatusChoices.CANCELLED
        self.payment.save(update_fields=['status'])

        handler = PaymentIntentCanceledHandler(
            self._make_canceled_event(event_id='evt_canceled_002')
        )
        result = handler.handle()
        self.assertEqual(result['status'], 'already_processed')

    # ------------------------------------------------------------------
    # Unknown payment_intent_id
    # ------------------------------------------------------------------

    def test_payment_failed_unknown_pi_id_is_ignored(self):
        """Unknown PaymentIntent ID in a failed event must return 'ignored', not raise."""
        handler = PaymentIntentPaymentFailedHandler(
            self._make_failed_event(pi_id='pi_unknown_xyz')
        )
        result = handler.handle()
        self.assertEqual(result['status'], 'ignored')

    def test_payment_canceled_unknown_pi_id_is_ignored(self):
        """Unknown PaymentIntent ID in a canceled event must return 'ignored', not raise."""
        handler = PaymentIntentCanceledHandler(
            self._make_canceled_event(pi_id='pi_unknown_xyz')
        )
        result = handler.handle()
        self.assertEqual(result['status'], 'ignored')

    def test_payment_succeeded_unknown_pi_id_is_ignored(self):
        """Unknown PaymentIntent ID in a succeeded event must return 'ignored', not raise."""
        mock_event = Mock()
        mock_event.id = 'evt_succ_unknown'
        mock_event.type = 'payment_intent.succeeded'
        mock_event.account = None
        mock_event.data = Mock()
        mock_event.data.object = Mock()
        mock_event.data.object.id = 'pi_unknown_xyz'
        mock_event.data.object.latest_charge = None
        mock_event.data.object.amount_received = 5000
        mock_event.data.object.currency = 'gbp'

        handler = PaymentIntentSucceededHandler(mock_event)
        result = handler.handle()
        self.assertEqual(result['status'], 'ignored')

    # ------------------------------------------------------------------
    # Duplicate succeeded with a *different* event ID (re-delivery scenario)
    # ------------------------------------------------------------------

    def test_payment_succeeded_duplicate_different_event_id_is_idempotent(self):
        """
        When Stripe re-delivers payment_intent.succeeded with a new event ID but the
        payment is already COMPLETED, the handler must return 'already_processed'
        without mutating the payment.
        """
        # First delivery
        mock_event = Mock()
        mock_event.id = 'evt_succ_first'
        mock_event.type = 'payment_intent.succeeded'
        mock_event.account = None
        mock_event.data = Mock()
        mock_event.data.object = Mock()
        mock_event.data.object.id = 'pi_failpath001'
        mock_event.data.object.latest_charge = 'ch_first'
        mock_event.data.object.amount_received = 5000
        mock_event.data.object.currency = 'gbp'

        PaymentIntentSucceededHandler(mock_event).handle()

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatusChoices.COMPLETED)

        # Second delivery — different Stripe event ID, same PaymentIntent
        mock_event2 = Mock()
        mock_event2.id = 'evt_succ_second'
        mock_event2.type = 'payment_intent.succeeded'
        mock_event2.account = None
        mock_event2.data = Mock()
        mock_event2.data.object = Mock()
        mock_event2.data.object.id = 'pi_failpath001'
        mock_event2.data.object.latest_charge = 'ch_first'
        mock_event2.data.object.amount_received = 5000
        mock_event2.data.object.currency = 'gbp'

        result2 = PaymentIntentSucceededHandler(mock_event2).handle()
        self.assertEqual(result2['status'], 'already_processed')

        # Payment state must be unchanged
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatusChoices.COMPLETED)
