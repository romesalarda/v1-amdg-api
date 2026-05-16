"""
Order Checkout Flow API Tests

Tests the complete order checkout flow via API endpoints with all payment methods:
- STRIPE: Tests client_secret return and payment intent creation
- BANK_TRANSFER: Tests bank reference generation and manual verification
- CASH: Tests pending approval workflow
- FREE: Tests free order checkout (£0 total)
- Edge cases: Stock validation, quantity limits, inactive products, payment verification
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money
from unittest.mock import patch, MagicMock

from apps.products.models import (
    Product, ProductVariant, ProductSizeChoices,
    Order, OrderStatusChoices, OrderItem
)
from apps.payments.models import (
    Payment, PaymentMethod, PaymentMethodTypeChoices,
    PaymentStatusChoices, BankTransferEvidence,
    Discount, DiscountRule, DiscountType, DiscountRuleTypeChoices,
)
from apps.events.models import Event, EventType, EventStatusChoices, EventSettings
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.bookings.models import Booking
from apps.organisations.models import Organisation

import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class OrderCheckoutAPITestCase(TestCase):
    """Test order checkout API endpoint with various payment methods."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123',
            is_staff=True
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event 2026',
            display_code='TE2026',
            display_identifier='TE2026CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create booking and attendee
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TEST-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Test',
            last_name='User',
            user=self.user,
            event=self.event,
            date_of_birth=date(1995, 5, 15),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        # Create product
        self.product = Product.objects.create(
            title='Conference T-Shirt',
            description='Official merchandise',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        # Create product variant
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=50,
            max_stock_quantity=100,
            max_purchase_quantity_per_order=5,
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        # Create payment methods
        self.stripe_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit Card',
            is_active=True,
            created_by=self.user
        )
        
        self.bank_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            title='Bank Transfer',
            is_active=True,
            created_by=self.user
        )
        
        self.cash_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.CASH,
            title='Cash',
            is_active=True,
            created_by=self.user
        )
    
    def create_order_with_items(self, variants_and_quantities):
        """Helper to create an order with items."""
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        for variant, quantity in variants_and_quantities:
            order.add_order_item(variant, quantity)
        
        order.refresh_from_db()
        # order.transition_to(OrderStatusChoices.PENDING)
        return order
    
    @patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.create')
    def test_stripe_checkout_success(self, mock_create_intent):
        """Test successful STRIPE checkout flow."""
        # Mock Stripe response
        mock_create_intent.return_value = {
            'id': 'pi_test123',
            'client_secret': 'pi_test123_secret_abc',
            'amount': 2000,
            'currency': 'gbp',
            'status': 'requires_payment_method'
        }
        
        # Create order
        order = self.create_order_with_items([(self.variant, 1)])
        self.assertEqual(order.total_amount, Money(20, 'GBP'))
        
        # Checkout with STRIPE
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('stripe_client_secret', response.data)
        self.assertEqual(response.data['stripe_client_secret'], 'pi_test123_secret_abc')
        self.assertEqual(response.data['total_amount'], '20.00')
        self.assertEqual(response.data['currency'], 'GBP')
        
        # Verify payment was created
        order.refresh_from_db()
        self.assertIsNotNone(order.payment)
        self.assertEqual(order.payment.status, PaymentStatusChoices.PENDING)
        self.assertEqual(order.payment.base_amount, Money(20, 'GBP'))
        self.assertEqual(order.payment.target, order)
        
        # Order should remain in PENDING status until payment is completed
        self.assertEqual(order.status, OrderStatusChoices.PENDING)
        
        # Verify Stripe service was called correctly
        mock_create_intent.assert_called_once()
        call_kwargs = mock_create_intent.call_args[1]
        self.assertEqual(call_kwargs['amount'], Money(20, 'GBP'))
        self.assertEqual(call_kwargs['currency'], 'GBP')
        self.assertIn('metadata', call_kwargs)
    
    def test_bank_transfer_checkout_success(self):
        """Test successful BANK_TRANSFER checkout flow."""
        # Create order
        order = self.create_order_with_items([(self.variant, 1)])
        
        # Checkout with BANK_TRANSFER
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.bank_method.id
        }
        
        response = self.client.post(url, data, format='json')
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('bank_transfer_reference', response.data)
        self.assertIn('bank_transfer_instructions', response.data)
        self.assertEqual(response.data['total_amount'], '20.00')
        self.assertEqual(response.data['currency'], 'GBP')
        
        # Verify payment was created
        order.refresh_from_db()
        self.assertIsNotNone(order.payment)
        self.assertEqual(order.payment.status, PaymentStatusChoices.PENDING)
        self.assertIsNotNone(order.payment.bank_transfer_reference)
        
        # Verify bank reference is in response
        self.assertEqual(
            response.data['bank_transfer_reference'],
            order.payment.bank_transfer_reference
        )

    def test_bank_transfer_checkout_immediate_requirement_rejects_missing_evidence(self):
        """Immediate evidence policy should reject checkout without bank_transfer_evidence payload."""
        self.bank_method.bank_transfer_required_immediately = True
        self.bank_method.save(update_fields=['bank_transfer_required_immediately'])

        order = self.create_order_with_items([(self.variant, 1)])
        url = f'/api/products/orders/{order.order_id}/checkout/'
        response = self.client.post(url, {'payment_method_id': self.bank_method.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('bank_transfer_evidence', response.data)

    def test_bank_transfer_checkout_immediate_with_evidence_creates_record(self):
        """Immediate evidence policy accepts multipart payload and persists evidence atomically."""
        self.bank_method.bank_transfer_required_immediately = True
        self.bank_method.save(update_fields=['bank_transfer_required_immediately'])

        order = self.create_order_with_items([(self.variant, 1)])
        url = f'/api/products/orders/{order.order_id}/checkout/'
        evidence_file = SimpleUploadedFile(
            'evidence.png',
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR',
            content_type='image/png'
        )

        response = self.client.post(
            url,
            {
                'payment_method_id': str(self.bank_method.id),
                'bank_transfer_evidence.evidence_file': evidence_file,
                'bank_transfer_evidence.payer_name': 'Order Payer',
                'bank_transfer_evidence.payer_account_last4': '1234',
                'bank_transfer_evidence.amount_on_evidence': '20.00',
            },
            format='multipart'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'pending_verification')
        self.assertIn('bank_transfer_evidence_id', response.data)
        self.assertIsNotNone(response.data['bank_transfer_evidence_id'])

        order.refresh_from_db()
        self.assertIsNotNone(order.payment)
        evidence = BankTransferEvidence.objects.get(payment=order.payment)
        self.assertEqual(evidence.transfer_id, order.payment.bank_transfer_reference)
        self.assertEqual(evidence.payer_name, 'Order Payer')
        self.assertEqual(evidence.payer_account_last4, '1234')
    
    def test_cash_checkout_success(self):
        """Test successful CASH checkout flow."""
        # Create order
        order = self.create_order_with_items([(self.variant, 1)])
        
        # Checkout with CASH
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.cash_method.id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('message', response.data)
        self.assertIn('venue', response.data['message'].lower())
        self.assertEqual(response.data['total_amount'], '20.00')
        self.assertEqual(response.data['currency'], 'GBP')
        
        # Verify payment was created
        order.refresh_from_db()
        self.assertIsNotNone(order.payment)
        self.assertEqual(order.payment.status, PaymentStatusChoices.PENDING)
    
    def test_free_order_checkout(self):
        """Test checkout for a free order (£0 total)."""
        # Create a free product
        free_product = Product.objects.create(
            title='Free Sticker',
            event=self.event,
            base_amount=Money(0, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        free_variant = ProductVariant.objects.create(
            product=free_product,
            size=ProductSizeChoices.ONE_SIZE,
            color='#FFFFFF',
            stock_quantity=100,
            max_stock_quantity=200,
            max_purchase_quantity_per_order=10,
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        # Create order
        order = self.create_order_with_items([(free_variant, 1)])
        self.assertEqual(order.total_amount, Money(0, 'GBP'))
        
        # Checkout (payment method required by serializer even for free orders)
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.bank_method.id
        }
        
        response = self.client.post(url, data, format='json')
        logger.info(f"Free order checkout response data: {response.data}")
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('message', response.data)
        self.assertIn('free', response.data['message'].lower())
        
        # Verify free order transitioned directly to PROCESSING (no payment needed)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.PROCESSING)
        self.assertIsNone(order.payment)
    
    def test_checkout_wrong_payment_method_event(self):
        """Test checkout fails when payment method is for different event."""
        # Create another event
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OE2026',
            display_identifier='OE2026CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=60),
            end_datetime=timezone.now() + timedelta(days=62),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create payment method for other event
        other_method = PaymentMethod.objects.create(
            event=other_event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Other Stripe',
            is_active=True,
            created_by=self.user
        )
        
        # Create order
        order = self.create_order_with_items([(self.variant, 1)])
        
        # Try to checkout with wrong event payment method
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': other_method.id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('payment_method_id', response.data)
    
    def test_checkout_order_not_pending(self):
        """Test checkout fails if order is not in PENDING status."""
        # Create order and submit it (PENDING)
        order = self.create_order_with_items([(self.variant, 1)])
        
        # Transition to PROCESSING (bypass checkout)
        order.transition_to(OrderStatusChoices.PENDING)
        order.transition_to(OrderStatusChoices.PROCESSING)
        
        # Try to checkout
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_requires_attendee_event_context(self):
        """Checkout should fail when order attendee/event context is missing."""
        order = self.create_order_with_items([(self.variant, 1)])
        order.attendee = None
        order.save(update_fields=['attendee'])

        url = f'/api/products/orders/{order.order_id}/checkout/'
        response = self.client.post(
            url,
            {'payment_method_id': self.stripe_method.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('order', response.data)
    
    def test_checkout_inactive_payment_method(self):
        """Test checkout fails with inactive payment method."""
        # Deactivate payment method
        self.stripe_method.is_active = False
        self.stripe_method.save()
        
        # Create order
        order = self.create_order_with_items([(self.variant, 1)])
        
        # Try to checkout
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('payment_method_id', response.data)
    
    def test_checkout_creates_payment_metadata(self):
        """Test that checkout stores order metadata in payment."""
        # Create order with multiple items
        order = self.create_order_with_items([(self.variant, 2)])
        
        # Checkout
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.bank_method.id
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify payment metadata
        order.refresh_from_db()
        payment = order.payment
        self.assertIsNotNone(payment.metadata)
        self.assertIn('order', payment.metadata)
        
        order_metadata = payment.metadata['order']
        self.assertIn('order_items', order_metadata)
        self.assertEqual(len(order_metadata['order_items']), 1)
        
        item_metadata = order_metadata['order_items'][0]
        self.assertEqual(item_metadata['quantity'], 2)
        self.assertEqual(item_metadata['product_title'], 'Conference T-Shirt')
    
    def test_multiple_checkouts_same_order(self):
        """Test that multiple checkout attempts on the same order are handled."""
        # Create order
        order = self.create_order_with_items([(self.variant, 1)])
        
        # First checkout
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.bank_method.id
        }
        
        response1 = self.client.post(url, data, format='json')
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        
        # Order should remain in PENDING status but now has a payment
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.PENDING)
        self.assertIsNotNone(order.payment)
        
        # Second checkout attempt should fail (order already has payment)
        response2 = self.client.post(url, data, format='json')
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_bank_transfer_verification_for_order(self):
        """Test bank transfer verification flow for orders."""
        # Create and checkout order
        order = self.create_order_with_items([(self.variant, 1)])
        
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.bank_method.id
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        order.refresh_from_db()
        payment = order.payment

        evidence = BankTransferEvidence.objects.create(
            transfer_id='BT-ORDER-VERIFY-001',
            evidence_file=SimpleUploadedFile(
                'proof.pdf',
                b'%PDF-1.4 order bank transfer evidence',
                content_type='application/pdf',
            ),
            payment=payment,
            payer_name='Order Payer',
            payer_account_last4='1234',
            amount_on_evidence=payment.base_amount,
        )
        evidence.mark_verified(self.admin_user)
        
        # Admin verifies bank transfer
        self.client.force_authenticate(user=self.admin_user)
        
        verify_url = f'/api/payments/list/{payment.payment_id}/verify-bank-transfer/'
        verify_data = {
            'verified': True
        }
        
        response = self.client.post(verify_url, verify_data, format='json')
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify payment status updated
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        
        # Verify order transitioned to PROCESSING
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.PROCESSING)
    
    def test_checkout_with_quantity_validation(self):
        """Test that checkout validates stock quantity."""
        # Reduce stock
        self.variant.stock_quantity = 2
        self.variant.save()
        
        # Try to create order with more than available stock
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        # Should fail when adding too many items
        with self.assertRaises(Exception):
            order.add_order_item(self.variant, 5)
    
    def test_checkout_updates_order_payment_reference(self):
        """Test that checkout properly links payment to order."""
        # Create order
        order = self.create_order_with_items([(self.variant, 1)])
        
        # Checkout
        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.bank_method.id
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify order.payment is set
        order.refresh_from_db()
        self.assertIsNotNone(order.payment)
        self.assertEqual(order.payment.target, order)
        self.assertEqual(order.status, OrderStatusChoices.PENDING)
        
        # Verify payment references order in metadata
        self.assertIn('order_reference_id', order.payment.metadata)
        self.assertEqual(
            order.payment.metadata['order_reference_id'],
            order.order_reference_id
        )

    # ------------------------------------------------------------------
    # Reserved-payment negative tests
    # ------------------------------------------------------------------

    def test_checkout_stale_reserved_payment_rejected(self):
        """Reserved payment that is no longer in DRAFTING status must be rejected with 400."""
        order = self.create_order_with_items([(self.variant, 1)])

        stale_payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.stripe_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.PENDING,  # Not DRAFTING → stale
            target=order,
        )

        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id,
            'payment_id': str(stale_payment.payment_id),
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_reserved_payment_wrong_user_rejected(self):
        """Reserved payment belonging to a different user must be rejected with 400."""
        other_user = User.objects.create_user(
            username='other_ser_rp',
            email='other_rp@example.com',
            password='pass12345',
        )
        order = self.create_order_with_items([(self.variant, 1)])

        other_payment = Payment.objects.create(
            user=other_user,  # different user
            event=self.event,
            method=self.stripe_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.DRAFTING,
        )

        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id,
            'payment_id': str(other_payment.payment_id),
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_reserved_payment_wrong_event_rejected(self):
        """Reserved payment tied to a different event must be rejected with 400."""
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OE2026',
            display_identifier='OE2026CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=60),
            end_datetime=timezone.now() + timedelta(days=62),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )
        order = self.create_order_with_items([(self.variant, 1)])

        mismatched_payment = Payment.objects.create(
            user=self.user,
            event=other_event,  # wrong event
            method=self.stripe_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.DRAFTING,
        )

        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id,
            'payment_id': str(mismatched_payment.payment_id),
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_reserved_payment_nonexistent_rejected(self):
        """Passing a payment_id that does not exist must return 400."""
        import uuid
        order = self.create_order_with_items([(self.variant, 1)])

        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id,
            'payment_id': str(uuid.uuid4()),
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # Bank transfer evidence negative tests
    # ------------------------------------------------------------------

    def test_checkout_evidence_payload_rejected_for_stripe_method(self):
        """Evidence payload submitted against a Stripe payment method must be rejected."""
        order = self.create_order_with_items([(self.variant, 1)])

        dummy_file = SimpleUploadedFile('receipt.pdf', b'dummy content', content_type='application/pdf')

        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.stripe_method.id,
            'bank_transfer_evidence.evidence_file': dummy_file,
            'bank_transfer_evidence.payer_name': 'Test User',
            'bank_transfer_evidence.payer_account_last4': '1234',
            'bank_transfer_evidence.amount_on_evidence': '20.00',
        }

        # Use multipart format because evidence_file is a file upload
        with patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.create') as mock_pi:
            mock_pi.return_value = MagicMock(id='pi_evidence_test', client_secret='secret')
            response = self.client.post(url, data, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_evidence_payload_missing_file_rejected(self):
        """Partial evidence payload (no evidence_file) must be rejected with 400."""
        order = self.create_order_with_items([(self.variant, 1)])

        url = f'/api/products/orders/{order.order_id}/checkout/'
        data = {
            'payment_method_id': self.bank_method.id,
            # Intentionally omit evidence_file — only text fields
            'bank_transfer_evidence.payer_name': 'Test User',
            'bank_transfer_evidence.payer_account_last4': '1234',
            'bank_transfer_evidence.amount_on_evidence': '20.00',
        }

        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OrderCompletionAPITestCase(TestCase):
    """Test order completion API endpoint (staff only)."""

    def setUp(self):
        """Set up test data."""
        # Create users
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='staff123',
            is_staff=True
        )
        
        self.client = APIClient()
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event 2026',
            display_code='TE2026',
            display_identifier='TE2026CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create booking and attendee
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TEST-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Test',
            last_name='User',
            user=self.user,
            event=self.event,
            date_of_birth=date(1995, 5, 15),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        # Create product
        self.product = Product.objects.create(
            title='Conference T-Shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=50,
            max_stock_quantity=100,
            max_purchase_quantity_per_order=5,
            added_by=self.user,
            verified=True,
            is_active=True
        )
    
    def test_staff_can_complete_processing_order(self):
        """Test that staff can mark a processing order as completed."""
        # Create order in PROCESSING status
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        order.add_order_item(self.variant, 1)
        order.refresh_from_db()
        order.transition_to(OrderStatusChoices.PENDING)
        order.transition_to(OrderStatusChoices.PROCESSING)
        
        # Staff user completes the order
        self.client.force_authenticate(user=self.staff_user)
        
        url = f'/api/products/orders/{order.order_id}/complete/'
        response = self.client.post(url)
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'success')
        self.assertIn('completed', response.data['message'].lower())
        
        # Verify order status changed
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.COMPLETED)
    
    def test_non_staff_cannot_complete_order(self):
        """Test that regular users cannot complete orders."""
        # Create order in PROCESSING status
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        order.add_order_item(self.variant, 1)
        order.refresh_from_db()
        order.transition_to(OrderStatusChoices.PENDING)
        order.transition_to(OrderStatusChoices.PROCESSING)
        
        # Regular user tries to complete the order
        self.client.force_authenticate(user=self.user)
        
        url = f'/api/products/orders/{order.order_id}/complete/'
        response = self.client.post(url)
        
        # Verify permission denied
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Verify order status unchanged
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.PROCESSING)
    
    def test_cannot_complete_pending_order(self):
        """Test that orders in PENDING status cannot be completed directly."""
        # Create order in PENDING status
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        order.add_order_item(self.variant, 1)
        order.refresh_from_db()
        order.transition_to(OrderStatusChoices.PENDING)
        
        # Staff user tries to complete pending order
        self.client.force_authenticate(user=self.staff_user)
        
        url = f'/api/products/orders/{order.order_id}/complete/'
        response = self.client.post(url)
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Verify order status unchanged
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.PENDING)


class OrderPaymentCompletionSignalTestCase(TransactionTestCase):
    """Test payment completion signal handling for orders."""
    
    def setUp(self):
        """Set up test data."""
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event 2026',
            display_code='TE2026',
            display_identifier='TE2026CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )

        self.event.settings.auto_complete_orders = True
        self.event.settings.orders_require_approval = False
        self.event.settings.product_selling_enabled = True
        self.event.settings.payment_enabled = True
        self.event.settings.save()
                
        # Create booking and attendee
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TEST-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Test',
            last_name='User',
            user=self.user,
            event=self.event,
            date_of_birth=date(1995, 5, 15),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        # Create product
        self.product = Product.objects.create(
            title='Test Product',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#000000',
            stock_quantity=50,
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit Card',
            is_active=True,
            created_by=self.user
        )
    
    def test_payment_completion_transitions_order_to_processing(self):
        """Test that completing payment transitions order to PROCESSING."""
        # Create order
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        order.add_order_item(self.variant, 1)
        order.refresh_from_db()
        order.transition_to(OrderStatusChoices.PENDING)
        
        # Create payment
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.PENDING,
            target=order,
            metadata=order.get_metadata()
        )
        
        order.payment = payment
        order.save()
        
        # Complete payment (triggers signal)
        payment.status = PaymentStatusChoices.COMPLETED
        payment.save()
        
        # Verify order transitioned to PROCESSING
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.PROCESSING)
    
    def test_payment_failure_does_not_transition_order(self):
        """Test that failed payment does not transition order."""
        # Create order
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        order.add_order_item(self.variant, 1)
        order.refresh_from_db()
        order.transition_to(OrderStatusChoices.PENDING)
        
        # Create payment
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.PENDING,
            target=order,
            metadata=order.get_metadata()
        )
        
        order.payment = payment
        order.save()
        
        # Fail payment
        payment.status = PaymentStatusChoices.FAILED
        payment.save()
        
        # Verify order remains PENDING
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatusChoices.PENDING)

    def test_payment_completion_missing_attendee_marks_manual_review(self):
        """Completion path should flag manual review when order attendee context is missing."""
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
        )

        order.add_order_item(self.variant, 1)
        order.refresh_from_db()
        order.transition_to(OrderStatusChoices.PENDING)
        order.attendee = None
        order.save(update_fields=['attendee'])

        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.PENDING,
            target=order,
            metadata={'order_reference_id': order.order_reference_id},
        )

        order.payment = payment
        order.save(update_fields=['payment'])

        payment.status = PaymentStatusChoices.COMPLETED
        payment.save(update_fields=['status'])

        payment.refresh_from_db()
        metadata = payment.metadata or {}
        self.assertTrue(metadata.get('requires_manual_review'))
        self.assertIn('processing_error', metadata)


# ============================================================================
# ORDER CHECKOUT DISCOUNT CODE TESTS
# ============================================================================

class OrderCheckoutDiscountCodeTests(TestCase):
    """
    Tests for discount code support in the order checkout flow.

    Covers:
    - validate-code endpoint (Product-level, ProductVariant-level, invalid, inactive)
    - preview-pricing with discount_code
    - checkout with discount_code (payment amount reflects discount)
    - Regression: no code → unchanged behaviour
    """

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='discountorder_user',
            email='discountorder@example.com',
            password='testpass123',
        )
        self.client.force_authenticate(user=self.user)

        self.admin_user = User.objects.create_user(
            username='discountorder_admin',
            email='discountorder_admin@example.com',
            password='admin123',
            is_staff=True,
        )

        self.event_type = EventType.objects.create(
            title='DiscountOrderConf',
            code='DOC',
            created_by=self.user,
        )
        self.organisation = Organisation.objects.create(
            title='Discount Order Org',
            created_by=self.user,
        )
        self.event = Event.objects.create(
            title='Discount Order Event',
            display_code='DOE26',
            display_identifier='DOE26CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )

        self.booking = Booking.objects.create(
            event=self.event,
            made_by=self.user,
        )
        self.attendee = Attendee.objects.create(
            first_name='Discount',
            last_name='Tester',
            user=self.user,
            event=self.event,
            date_of_birth=date(1995, 6, 1),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user,
        )

        self.product = Product.objects.create(
            title='Discount Test Product',
            event=self.event,
            base_amount=Money(50, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#FF0000',
            stock_quantity=100,
            max_stock_quantity=200,
            max_purchase_quantity_per_order=10,
            added_by=self.user,
            verified=True,
            is_active=True,
        )

        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            title='Bank Transfer',
            is_active=True,
            created_by=self.user,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_product_code_discount(self, code, amount=None, percentage=None, active=True):
        """Create a CODE_MATCHES Discount targeting self.product."""
        from django.contrib.contenttypes.models import ContentType
        discount_type = DiscountType.FIXED if amount is not None else DiscountType.PERCENTAGE
        discount = Discount.objects.create(
            name=f'Code Discount ({code})',
            discount_type=discount_type,
            amount=Money(amount, 'GBP') if amount is not None else None,
            percentage=percentage,
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.pk,
            active=active,
            created_by=self.user,
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            name=f'Code rule ({code})',
            discount=discount,
            value=code,
            active=True,
            added_by=self.user,
        )
        return discount

    def _create_variant_code_discount(self, code, amount=None, percentage=None, active=True):
        """Create a CODE_MATCHES Discount targeting self.variant."""
        from django.contrib.contenttypes.models import ContentType
        discount_type = DiscountType.FIXED if amount is not None else DiscountType.PERCENTAGE
        discount = Discount.objects.create(
            name=f'Variant Code Discount ({code})',
            discount_type=discount_type,
            amount=Money(amount, 'GBP') if amount is not None else None,
            percentage=percentage,
            target_type=ContentType.objects.get_for_model(ProductVariant),
            target_id=self.variant.pk,
            active=active,
            created_by=self.user,
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            name=f'Variant code rule ({code})',
            discount=discount,
            value=code,
            active=True,
            added_by=self.user,
        )
        return discount

    def _create_order(self, quantity=1):
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
        )
        order.add_order_item(self.variant, quantity)
        order.refresh_from_db()
        return order

    # ------------------------------------------------------------------
    # validate-code tests
    # ------------------------------------------------------------------

    def test_validate_code_valid_product_level_returns_true(self):
        """A code targeting a Product in the order must be valid."""
        self._create_product_code_discount(code='PROD10', amount=10)
        order = self._create_order()

        response = self.client.post(
            '/api/products/orders/validate-code/',
            {'code': 'PROD10', 'order_id': str(order.order_id)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['valid'])

    def test_validate_code_valid_variant_level_returns_true(self):
        """A code targeting a ProductVariant in the order must be valid."""
        self._create_variant_code_discount(code='VAR15', amount=15)
        order = self._create_order()

        response = self.client.post(
            '/api/products/orders/validate-code/',
            {'code': 'VAR15', 'order_id': str(order.order_id)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['valid'])

    def test_validate_code_wrong_code_returns_false(self):
        """An unrecognised code must return valid=false."""
        order = self._create_order()

        response = self.client.post(
            '/api/products/orders/validate-code/',
            {'code': 'DOESNOTEXIST', 'order_id': str(order.order_id)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['valid'])

    def test_validate_code_inactive_discount_returns_false(self):
        """A code whose parent discount is inactive must return valid=false."""
        self._create_product_code_discount(code='INACTIVE20', amount=20, active=False)
        order = self._create_order()

        response = self.client.post(
            '/api/products/orders/validate-code/',
            {'code': 'INACTIVE20', 'order_id': str(order.order_id)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['valid'])

    def test_validate_code_requires_code_field(self):
        """Missing code field must return 400."""
        order = self._create_order()
        response = self.client.post(
            '/api/products/orders/validate-code/',
            {'order_id': str(order.order_id)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_code_requires_order_id_field(self):
        """Missing order_id field must return 400."""
        response = self.client.post(
            '/api/products/orders/validate-code/',
            {'code': 'ANYCODE'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_code_requires_authentication(self):
        """Unauthenticated requests must be rejected."""
        order = self._create_order()
        self.client.force_authenticate(user=None)
        response = self.client.post(
            '/api/products/orders/validate-code/',
            {'code': 'PROD10', 'order_id': str(order.order_id)},
            format='json',
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # ------------------------------------------------------------------
    # preview-pricing with discount_code
    # ------------------------------------------------------------------

    def test_preview_pricing_with_code_reduces_total(self):
        """preview-pricing with a valid code should return a lower total."""
        self._create_variant_code_discount(code='PREVIEW10', amount=10)

        response = self.client.post(
            '/api/products/orders/preview-pricing/',
            {
                'attendee_id': str(self.attendee.attendee_id),
                'discount_code': 'PREVIEW10',
                'items': [{'product_variant_id': str(self.variant.variant_id), 'quantity': 1}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['discount_code_applied'], 'PREVIEW10')
        # Product base is £50, discount is £10 → total should be £40
        self.assertEqual(response.data['total_amount'], '40.00')
        self.assertEqual(response.data['total_discount'], '10.00')

        item = response.data['items'][0]
        self.assertEqual(item['unit_price'], '40.00')
        self.assertEqual(item['line_discount'], '10.00')
        self.assertEqual(len(item['applied_discounts']), 1)

    def test_preview_pricing_without_code_unchanged(self):
        """preview-pricing without a code must return the original total (regression)."""
        self._create_product_code_discount(code='NOTUSED', amount=10)

        response = self.client.post(
            '/api/products/orders/preview-pricing/',
            {
                'attendee_id': str(self.attendee.attendee_id),
                'items': [{'product_variant_id': str(self.variant.variant_id), 'quantity': 1}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['discount_code_applied'])
        self.assertEqual(response.data['total_amount'], '50.00')
        self.assertEqual(response.data['total_discount'], '0.00')

    def test_preview_pricing_with_wrong_code_no_discount(self):
        """An unrecognised code in preview must not apply any discount."""
        response = self.client.post(
            '/api/products/orders/preview-pricing/',
            {
                'attendee_id': str(self.attendee.attendee_id),
                'discount_code': 'WRONGCODE',
                'items': [{'product_variant_id': str(self.variant.variant_id), 'quantity': 1}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Code is passed through but yields no discount
        self.assertEqual(response.data['discount_code_applied'], 'WRONGCODE')
        self.assertEqual(response.data['total_amount'], '50.00')
        self.assertEqual(response.data['total_discount'], '0.00')

    def test_preview_pricing_with_percentage_code(self):
        """Percentage-type code discounts must be correctly applied in preview."""
        self._create_variant_code_discount(code='PERCENT20', percentage=20)

        response = self.client.post(
            '/api/products/orders/preview-pricing/',
            {
                'attendee_id': str(self.attendee.attendee_id),
                'discount_code': 'PERCENT20',
                'items': [{'product_variant_id': str(self.variant.variant_id), 'quantity': 2}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 20% of £50 = £10 per unit; 2 units → total discount £20, total amount £80
        self.assertEqual(response.data['total_discount'], '20.00')
        self.assertEqual(response.data['total_amount'], '80.00')

    # ------------------------------------------------------------------
    # checkout with discount_code
    # ------------------------------------------------------------------

    def test_checkout_with_code_creates_discounted_payment(self):
        """Checkout with a valid code must create a payment for the discounted amount."""
        self._create_variant_code_discount(code='CHECKOUT10', amount=10)
        order = self._create_order()

        response = self.client.post(
            f'/api/products/orders/{order.order_id}/checkout/',
            {'payment_method_id': self.payment_method.id, 'discount_code': 'CHECKOUT10'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['total_amount'], '40.00')
        self.assertEqual(response.data['discount_code_applied'], 'CHECKOUT10')

        order.refresh_from_db()
        self.assertIsNotNone(order.payment)
        # Payment amount must be the discounted total, not the original order total
        self.assertEqual(order.payment.base_amount, Money(40, 'GBP'))
        # Order total_amount must remain unchanged
        self.assertEqual(order.total_amount, Money(50, 'GBP'))

    def test_checkout_with_code_stores_metadata_snapshot(self):
        """Payment metadata must include discount_code and applied_discounts_snapshot."""
        self._create_variant_code_discount(code='SNAP10', amount=10)
        order = self._create_order()

        response = self.client.post(
            f'/api/products/orders/{order.order_id}/checkout/',
            {'payment_method_id': self.payment_method.id, 'discount_code': 'SNAP10'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        order.refresh_from_db()
        metadata = order.payment.metadata or {}
        self.assertEqual(metadata.get('discount_code'), 'SNAP10')

        snapshot = metadata.get('applied_discounts_snapshot')
        self.assertIsNotNone(snapshot)
        self.assertIsInstance(snapshot, list)
        self.assertEqual(len(snapshot), 1)

        entry = snapshot[0]
        self.assertEqual(entry['item_index'], 0)
        self.assertEqual(str(entry['variant_id']), str(self.variant.variant_id))
        self.assertEqual(len(entry['discount_breakdown']), 1)
        self.assertEqual(entry['total_discount'], '10.00')

    def test_checkout_without_code_payment_amount_unchanged(self):
        """Regression: checkout without a code must create a payment at the original order total."""
        self._create_product_code_discount(code='NOTUSED', amount=10)
        order = self._create_order()

        response = self.client.post(
            f'/api/products/orders/{order.order_id}/checkout/',
            {'payment_method_id': self.payment_method.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['total_amount'], '50.00')
        self.assertIsNone(response.data['discount_code_applied'])

        order.refresh_from_db()
        self.assertEqual(order.payment.base_amount, Money(50, 'GBP'))
        metadata = order.payment.metadata or {}
        self.assertIsNone(metadata.get('discount_code'))

    def test_checkout_with_inapplicable_code_no_discount(self):
        """A code that exists but targets a different product must not reduce the payment."""
        # Discount on a different product
        other_product = Product.objects.create(
            title='Other Product',
            event=self.event,
            base_amount=Money(30, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True,
        )
        from django.contrib.contenttypes.models import ContentType
        other_discount = Discount.objects.create(
            name='Other Discount',
            discount_type=DiscountType.FIXED,
            amount=Money(5, 'GBP'),
            target_type=ContentType.objects.get_for_model(Product),
            target_id=other_product.pk,
            active=True,
            created_by=self.user,
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            name='Other code rule',
            discount=other_discount,
            value='OTHERPROD',
            active=True,
            added_by=self.user,
        )

        order = self._create_order()
        response = self.client.post(
            f'/api/products/orders/{order.order_id}/checkout/',
            {'payment_method_id': self.payment_method.id, 'discount_code': 'OTHERPROD'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Code OTHERPROD targets a different product; no discount on this order's variant
        self.assertEqual(response.data['total_amount'], '50.00')

        order.refresh_from_db()
        self.assertEqual(order.payment.base_amount, Money(50, 'GBP'))

    def test_checkout_with_variant_level_code(self):
        """A code targeting the ProductVariant directly must be applied at checkout."""
        self._create_variant_code_discount(code='VARCODE5', amount=5)
        order = self._create_order()

        response = self.client.post(
            f'/api/products/orders/{order.order_id}/checkout/',
            {'payment_method_id': self.payment_method.id, 'discount_code': 'VARCODE5'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['total_amount'], '45.00')

        order.refresh_from_db()
        self.assertEqual(order.payment.base_amount, Money(45, 'GBP'))
