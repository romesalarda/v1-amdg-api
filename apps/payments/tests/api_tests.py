"""
Comprehensive API tests for the payments app.

Tests all endpoints, permissions, serialization, filtering, and business logic
for payments, refunds, donations, discounts, and payment methods.

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from djmoney.money import Money
from decimal import Decimal
from unittest.mock import Mock, patch

from apps.payments.models import (
    Payment, PaymentMethod, PaymentStatusChoices, PaymentMethodTypeChoices,
    Discount, DiscountRule, DiscountType, DiscountRuleTypeChoices,
    RefundRequest, RefundPolicy, RefundPolicyTypeChoices,
    Donation, PaymentHistoryAction,
    CreditExpense, CreditExpenseTypeChoices, BankTransferEvidence,
    StripeConnectedAccount,
    DebitExpense, DebitExpenseTypeChoices, BudgetProposal,
)
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventType, EventRole, EventRoleAssignment, EventRoleCategoryChoices, EventStatusChoices, EventStaff
from apps.bookings.models import Booking, BookingPackage, TicketType, Ticket, TicketScopeChoices, TicketStatusChoices
from apps.products.models import (
    Order,
    OrderItem,
    OrderStatusChoices,
    OrderItemStatusChoices,
    Product,
    ProductVariant,
    ProductSizeChoices,
    StockAuditLog,
)
from apps.organisations.models import EventSponsor, EventSponsorPackage
from apps.attendee.models import Attendee, AttendeeRelationship

import datetime
User = get_user_model()


class PaymentAPITestCase(APITestCase):
    """Test suite for Payment API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        self.other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )
        
        # Create organisation
        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        # Create event
        event_type = EventType.objects.create(
            title='Conference',
            code='CONF'
        )
        self.event = Event.objects.create(
            title='Test Event',
            display_code='PAY001',
            display_identifier='PAY001TEST001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create administrative role and assignment
        self.admin_role = EventRole.objects.create(
            name='Event Admin',
            code='EVADM',
            category=EventRoleCategoryChoices.ADMINISTRATIVE
        )
        
        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.regular_user,
            role=self.admin_role
        )

        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.admin_user,
            role=self.admin_role
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            title='Bank Transfer',
            event=self.event,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            is_active=True,
            provided_details={
                'account_name': 'Test Account',
                'sort_code': '12-34-56',
                'account_number': '12345678'
            }
        )

        self.cash_payment_method = PaymentMethod.objects.create(
            title='Cash',
            event=self.event,
            method_type=PaymentMethodTypeChoices.CASH,
            is_active=True,
        )
        
        # Create test payment
        self.payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )

        self.booking = Booking.objects.create(
            event=self.event,
            made_by=self.regular_user,
        )

        self.order = Order.objects.create(
            customer=self.regular_user,
            created_by=self.admin_user,
            total_amount=Money(25, 'GBP'),
            status='draft',
        )

        self.audit_product = Product.objects.create(
            title='Audit Hoodie',
            event=self.event,
            base_amount=Money(30, 'GBP'),
            added_by=self.admin_user,
            verified=True,
        )
        self.audit_variant = ProductVariant.objects.create(
            product=self.audit_product,
            size=ProductSizeChoices.MEDIUM,
            color='#111111',
            stock_quantity=25,
            added_by=self.admin_user,
        )
        
        self.client = APIClient()
    
    def test_list_payments_as_admin(self):
        """Admin should see all payments."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_payments_as_owner(self):
        """User should see their own payments."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:payment-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_list_payments_as_other_user(self):
        """Other users should not see payments they don't own."""
        self.client.force_authenticate(user=self.other_user)
        url = reverse('payments:payment-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)
    
    def test_retrieve_payment_details(self):
        """Test retrieving detailed payment information."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:payment-detail', kwargs={'payment_id': self.payment.payment_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('base_amount', response.data)
        self.assertIn('modified_amount', response.data)
        self.assertIn('history_actions', response.data)
        # Verify target fields are not exposed for security
        self.assertNotIn('target_type', response.data)
        self.assertNotIn('target_id', response.data)
        self.assertNotIn('target_details', response.data)
        self.assertNotIn('target_model', response.data)

    def test_stock_audit_list_requires_event_scope(self):
        """Stock audit list should be empty unless event scope is provided."""
        StockAuditLog.objects.create(
            product_variant=self.audit_variant,
            old_quantity=25,
            new_quantity=24,
            change_amount=-1,
            change_reason=StockAuditLog.ChangeReasonChoices.INITIAL_ORDER_DEDUCTION,
            payment_id=self.payment.payment_id,
            actor=self.regular_user,
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:stockauditlog-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'], [])

    def test_stock_audit_list_returns_only_owner_logs_for_event(self):
        """Regular users should only see stock logs tied to their own payments in event scope."""
        other_payment = Payment.objects.create(
            user=self.other_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(55, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
        )

        own_log = StockAuditLog.objects.create(
            product_variant=self.audit_variant,
            old_quantity=25,
            new_quantity=23,
            change_amount=-2,
            change_reason=StockAuditLog.ChangeReasonChoices.INITIAL_ORDER_DEDUCTION,
            payment_id=self.payment.payment_id,
            actor=self.regular_user,
        )
        StockAuditLog.objects.create(
            product_variant=self.audit_variant,
            old_quantity=23,
            new_quantity=21,
            change_amount=-2,
            change_reason=StockAuditLog.ChangeReasonChoices.INITIAL_ORDER_DEDUCTION,
            payment_id=other_payment.payment_id,
            actor=self.other_user,
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:stockauditlog-list')
        response = self.client.get(url, {'event_id': str(self.event.event_id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], str(own_log.id))
        self.assertEqual(response.data['results'][0]['payment_id'], str(self.payment.payment_id))

    def test_stock_audit_list_infers_event_and_payment_fields(self):
        """Serializer should expose inferred event and payment metadata via payment_id."""
        StockAuditLog.objects.create(
            product_variant=self.audit_variant,
            old_quantity=25,
            new_quantity=24,
            change_amount=-1,
            change_reason=StockAuditLog.ChangeReasonChoices.INITIAL_ORDER_DEDUCTION,
            payment_id=self.payment.payment_id,
            actor=self.regular_user,
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:stockauditlog-list')
        response = self.client.get(url, {'event_id': str(self.event.event_id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        payload = response.data['results'][0]
        self.assertEqual(payload['event_id'], str(self.event.event_id))
        self.assertEqual(payload['event_title'], self.event.title)
        self.assertEqual(payload['payment_reference'], self.payment.payment_reference)

    def test_stock_audit_admin_can_see_all_event_logs(self):
        """Admins can see all stock logs for the selected event scope."""
        other_payment = Payment.objects.create(
            user=self.other_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(60, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
        )

        StockAuditLog.objects.create(
            product_variant=self.audit_variant,
            old_quantity=25,
            new_quantity=24,
            change_amount=-1,
            change_reason=StockAuditLog.ChangeReasonChoices.INITIAL_ORDER_DEDUCTION,
            payment_id=self.payment.payment_id,
            actor=self.regular_user,
        )
        StockAuditLog.objects.create(
            product_variant=self.audit_variant,
            old_quantity=24,
            new_quantity=22,
            change_amount=-2,
            change_reason=StockAuditLog.ChangeReasonChoices.INITIAL_ORDER_DEDUCTION,
            payment_id=other_payment.payment_id,
            actor=self.other_user,
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:stockauditlog-list')
        response = self.client.get(url, {'event_id': str(self.event.event_id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)

    def test_admin_cancel_payment_cancels_linked_orders(self):
        """Cancelling a pending payment should cancel linked pending orders for stock safety."""
        pending_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(75, 'GBP'),
            status=PaymentStatusChoices.PENDING,
        )
        linked_order = Order.objects.create(
            customer=self.regular_user,
            created_by=self.admin_user,
            total_amount=Money(75, 'GBP'),
            status=OrderStatusChoices.PENDING,
            payment=pending_payment,
        )

        OrderItem.objects.create(
            order=linked_order,
            product_variant=self.audit_variant,
            quantity=1,
            unit_price=Money(75, 'GBP'),
            total_price=Money(75, 'GBP'),
            status=OrderItemStatusChoices.PENDING,
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-cancel', kwargs={'payment_id': pending_payment.payment_id})
        response = self.client.post(url)
        print(response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pending_payment.refresh_from_db()
        linked_order.refresh_from_db()
        self.assertEqual(pending_payment.status, PaymentStatusChoices.CANCELLED)
        self.assertEqual(linked_order.status, OrderStatusChoices.CANCELLED)
    
    def test_create_payment(self):
        """Test creating a new payment."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        data = {
            'user': self.regular_user.id,
            'event': self.event.id,
            'method': self.payment_method.id,
            'base_amount': '50.00',
            'base_amount_currency': 'GBP',
            'description': 'Test payment'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Payment.objects.count(), 2)

    def test_create_payment_with_booking_target(self):
        """Test creating a payment with safe booking target fields."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        data = {
            'user': self.regular_user.id,
            'event': self.event.id,
            'method': self.payment_method.id,
            'base_amount': '50.00',
            'base_amount_currency': 'GBP',
            'target': 'booking',
            'target_id': str(self.booking.id),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.latest('created_at')
        self.assertEqual(payment.target_type.model, 'booking')
        self.assertEqual(payment.target_id, str(self.booking.pk))

    def test_create_payment_with_order_uuid_target(self):
        """Test creating a payment with UUID target_id that resolves to internal PK."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        data = {
            'user': self.regular_user.id,
            'event': self.event.id,
            'method': self.payment_method.id,
            'base_amount': '60.00',
            'base_amount_currency': 'GBP',
            'target': 'order',
            'target_id': str(self.order.order_id),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.latest('created_at')
        self.assertEqual(payment.target_type.model, 'order')
        self.assertEqual(payment.target_id, str(self.order.pk))

    def test_create_payment_with_none_target(self):
        """Test creating a payment with explicit no-target payload."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        data = {
            'user': self.regular_user.id,
            'event': self.event.id,
            'method': self.payment_method.id,
            'base_amount': '35.00',
            'base_amount_currency': 'GBP',
            'target': 'none',
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.latest('created_at')
        self.assertIsNone(payment.target_type)
        self.assertIsNone(payment.target_id)

    def test_create_payment_with_sponsorship_target(self):
        """Test creating a payment with sponsorship alias resolves to EventSponsor."""
        sponsor_package = EventSponsorPackage.objects.create(
            event=self.event,
            package_name='Silver Sponsor',
            base_amount=Money(120, 'GBP'),
            tier=7,
        )
        sponsor = EventSponsor.objects.create(
            name='Sponsor One',
            organisation=self.organisation,
            event=self.event,
            package=sponsor_package,
            added_by=self.admin_user,
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        data = {
            'user': self.regular_user.id,
            'event': self.event.id,
            'method': self.payment_method.id,
            'base_amount': '120.00',
            'base_amount_currency': 'GBP',
            'target': 'sponsorship',
            'target_id': str(sponsor.sponsor_id),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.latest('created_at')
        self.assertEqual(payment.target_type.model, 'eventsponsor')
        self.assertEqual(payment.target_id, str(sponsor.pk))

    def test_create_payment_rejects_unknown_target(self):
        """Test validation error for unsupported target aliases."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        data = {
            'user': self.regular_user.id,
            'event': self.event.id,
            'method': self.payment_method.id,
            'base_amount': '35.00',
            'base_amount_currency': 'GBP',
            'target': 'donation',
            'target_id': '1',
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('target', response.data)

    def test_create_payment_legacy_target_fields_still_supported(self):
        """Test backward compatibility for legacy target_type + target_id payloads."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        booking_ct = ContentType.objects.get_for_model(Booking)
        data = {
            'user': self.regular_user.id,
            'event': self.event.id,
            'method': self.payment_method.id,
            'base_amount': '50.00',
            'base_amount_currency': 'GBP',
            'target_type': booking_ct.id,
            'target_id': str(self.booking.id),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.latest('created_at')
        self.assertEqual(payment.target_type_id, booking_ct.id)
        self.assertEqual(payment.target_id, str(self.booking.pk))
    
    def test_filter_payments_by_status(self):
        """Test filtering payments by status."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        response = self.client.get(url, {'status': PaymentStatusChoices.COMPLETED})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for payment in response.data['results']:
            self.assertEqual(payment['status'], PaymentStatusChoices.COMPLETED)
    
    def test_search_payments(self):
        """Test searching payments by reference."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-list')
        response = self.client.get(url, {'search': self.payment.payment_reference[:10]})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_mark_payment_completed(self):
        """Test marking payment as completed."""
        pending_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.cash_payment_method,
            base_amount=Money(75, 'GBP'),
            status=PaymentStatusChoices.PENDING
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-mark-completed', kwargs={'payment_id': pending_payment.payment_id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pending_payment.refresh_from_db()
        self.assertEqual(pending_payment.status, PaymentStatusChoices.COMPLETED)
    
    def test_non_admin_cannot_mark_completed(self):
        """Non-admin users cannot mark payments as completed."""
        pending_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(75, 'GBP'),
            status=PaymentStatusChoices.PENDING
        )
        
        self.client.force_authenticate(user=self.other_user)
        url = reverse('payments:payment-mark-completed', kwargs={'payment_id': pending_payment.payment_id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_verify_bank_transfer_marks_sponsor_official(self):
        """Verifying a sponsorship bank transfer should finalize the sponsor state."""
        sponsor_package = EventSponsorPackage.objects.create(
            event=self.event,
            package_name='Gold Sponsor',
            base_amount=Money(220, 'GBP'),
            tier=8,
        )
        sponsor = EventSponsor.objects.create(
            name='Sponsor Finalize',
            organisation=self.organisation,
            event=self.event,
            package=sponsor_package,
            added_by=self.admin_user,
        )
        sponsor_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(220, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            target=sponsor,
        )

        evidence = BankTransferEvidence.objects.create(
            transfer_id='SPONSOR-VERIFY-001',
            evidence_file=SimpleUploadedFile(
                'proof.pdf',
                b'%PDF-1.4 sponsor transfer evidence',
                content_type='application/pdf',
            ),
            payment=sponsor_payment,
            payer_name='Sponsor Payer',
            payer_account_last4='1234',
        )
        evidence.mark_verified(self.admin_user)

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:payment-verify-bank-transfer', kwargs={'payment_id': sponsor_payment.payment_id})
        response = self.client.post(url, {'verified': True, 'notes': 'received'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sponsor.refresh_from_db()
        sponsor_payment.refresh_from_db()
        self.assertEqual(sponsor_payment.status, PaymentStatusChoices.COMPLETED)
        self.assertTrue(sponsor.is_verified)
        self.assertTrue(sponsor.is_processed)

    def test_create_credit_expense(self):
        """Event administrative users can create credits."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:creditexpense-list')
        response = self.client.post(
            url,
            {
                'event': self.event.id,
                'amount': '15.00',
                'description': 'Venue deposit for test event',
                'expense_type': CreditExpenseTypeChoices.VENUE_COST,
                'paid_date': timezone.now().date().isoformat(),
                'is_settled': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CreditExpense.objects.count(), 1)
        credit = CreditExpense.objects.get()
        self.assertEqual(credit.created_by, self.regular_user)

    def test_credit_expense_rejects_target_fields_from_api(self):
        """Generic target fields should not be writable from the API."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:creditexpense-list')
        response = self.client.post(
            url,
            {
                'event': self.event.id,
                'amount': '15.00',
                'description': 'Venue deposit for test event',
                'expense_type': CreditExpenseTypeChoices.VENUE_COST,
                'target_type': 1,
                'target_id': '1',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CreditExpense.objects.count(), 0)

    def test_create_and_confirm_bank_transfer_evidence(self):
        """Evidence upload should allow confirmation and verification by an event admin."""
        evidence_file = SimpleUploadedFile(
            'bank-proof.pdf',
            b'%PDF-1.4 test bank transfer evidence',
            content_type='application/pdf',
        )

        self.client.force_authenticate(user=self.regular_user)
        create_url = reverse('payments:banktransferevidence-list')
        response = self.client.post(
            create_url,
            {
                'transfer_id': 'TRX-ABC-123',
                'evidence_file': evidence_file,
                'payment': self.payment.id,
                'payer_name': 'Test Payer',
                'payer_account_last4': '1234',
                'amount_on_evidence': '100.00',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        evidence = BankTransferEvidence.objects.get()
        self.assertEqual(evidence.payment, self.payment)

        self.client.force_authenticate(user=self.admin_user)
        confirm_url = reverse('payments:banktransferevidence-confirm-payment-match', kwargs={'bank_transfer_id': evidence.bank_transfer_id})
        confirm_response = self.client.post(confirm_url)

        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)
        evidence.refresh_from_db()
        self.assertEqual(evidence.verification_status, 'verified')


class PaymentMethodAPITestCase(APITestCase):
    """Test suite for PaymentMethod API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )

        # Create organisation
        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            display_code='PMT001',
            display_identifier='PMT001TEST001',
            created_by=self.admin_user,
            organisation=self.organisation,
        )
        
        self.payment_method = PaymentMethod.objects.create(
            title='Stripe',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True,
            created_by=self.admin_user
        )
        
        self.client = APIClient()
    
    def test_list_payment_methods_as_admin(self):
        """Admin can list payment methods."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:paymentmethod-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    # def test_list_payment_methods_as_regular_user(self):
    #     """Regular users cannot list payment methods."""
    #     self.client.force_authenticate(user=self.regular_user)
    #     url = reverse('payments:paymentmethod-list')
    #     response = self.client.get(url)
        
    #     self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_create_payment_method(self):
        """Admin can create payment method."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:paymentmethod-list')
        data = {
            'title': 'Bank Transfer',
            'event': self.event.id,
            'method_type': PaymentMethodTypeChoices.BANK_TRANSFER,
            'is_active': True,
            'provided_details': {
                'account_name': 'Test',
                'sort_code': '12-34-56',
                'account_number': '12345678'
            }
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PaymentMethod.objects.count(), 2)
    
    def test_filter_payment_methods_by_type(self):
        """Test filtering payment methods by type."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:paymentmethod-list')
        response = self.client.get(url, {'method_type': PaymentMethodTypeChoices.STRIPE})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for method in response.data['results']:
            self.assertEqual(method['method_type'], PaymentMethodTypeChoices.STRIPE)

    def test_create_stripe_payment_method_rejects_other_user_connected_account(self):
        """Creating a Stripe payment method should reject account IDs owned by another user."""
        StripeConnectedAccount.objects.create(
            user=self.regular_user,
            stripe_account_id='acct_other_user_123',
            charges_enabled=True,
            details_submitted=True,
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:paymentmethod-list')
        data = {
            'title': 'Stripe Invalid Ownership',
            'event': self.event.id,
            'method_type': PaymentMethodTypeChoices.STRIPE,
            'is_active': True,
            'provided_details': {
                'stripe_account_id': 'acct_other_user_123'
            }
        }

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('provided_details', response.data)

    def test_create_stripe_payment_method_accepts_owned_connected_account(self):
        """Creating a Stripe payment method should accept account IDs owned by the authenticated user."""
        StripeConnectedAccount.objects.create(
            user=self.admin_user,
            stripe_account_id='acct_admin_user_123',
            charges_enabled=True,
            details_submitted=True,
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:paymentmethod-list')
        data = {
            'title': 'Stripe Owned Account',
            'event': self.event.id,
            'method_type': PaymentMethodTypeChoices.STRIPE,
            'is_active': True,
            'provided_details': {
                'stripe_account_id': 'acct_admin_user_123'
            }
        }

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class StripeConnectedAccountAPITestCase(APITestCase):
    """Test suite for user-scoped Stripe connected account management endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='stripeowner',
            email='stripeowner@test.com',
            password='testpass123',
        )
        self.other_user = User.objects.create_user(
            username='stripeother',
            email='stripeother@test.com',
            password='testpass123',
        )
        self.client = APIClient()

        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Stripe Test Org',
            created_by=self.other_user,
        )
        self.event_type = EventType.objects.create(title='Stripe Event Type', code='STRIPE')
        self.event = Event.objects.create(
            title='Stripe Staff Event',
            display_code='STR001',
            display_identifier='STR001TEST001',
            created_by=self.other_user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=7),
            end_datetime=timezone.now() + timezone.timedelta(days=8),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )

    def _stripe_account_mock(self, account_id='acct_new_123'):
        mock_account = Mock()
        mock_account.id = account_id
        mock_account.type = 'express'
        mock_account.country = 'GB'
        mock_account.email = 'stripeowner@test.com'
        mock_account.business_type = 'individual'
        mock_account.charges_enabled = False
        mock_account.payouts_enabled = False
        mock_account.details_submitted = False
        mock_account.requirements = {'disabled_reason': ''}
        mock_account.capabilities = {'card_payments': {'requested': True}}
        mock_account.metadata = {}
        return mock_account

    def test_list_returns_only_authenticated_users_accounts(self):
        StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_user_1')
        StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_user_2')
        StripeConnectedAccount.objects.create(user=self.other_user, stripe_account_id='acct_other_1')

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('payments:stripe-connect-accounts-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        returned_ids = {item['stripe_account_id'] for item in response.data["results"]}
        self.assertEqual(returned_ids, {'acct_user_1', 'acct_user_2'})

    @patch('apps.payments.services.stripe.connect.StripeConnectService.retrieve_account')
    def test_create_connected_account(self, mock_retrieve_account):
        mock_retrieve_account.return_value = self._stripe_account_mock(account_id='acct_create_1')

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('payments:stripe-connect-accounts-list'),
            {
                'stripe_account_id': 'acct_create_1',
                'display_name': 'Primary Wallet',
                'is_primary': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['stripe_account_id'], 'acct_create_1')
        self.assertEqual(response.data['display_name'], 'Primary Wallet')
        self.assertTrue(response.data['is_primary'])

    @patch('apps.payments.services.stripe.connect.StripeConnectService.retrieve_account')
    def test_create_rejects_duplicate_for_same_user(self, mock_retrieve_account):
        mock_retrieve_account.return_value = self._stripe_account_mock(account_id='acct_dup_1')
        StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_dup_1')

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('payments:stripe-connect-accounts-list'),
            {
                'stripe_account_id': 'acct_dup_1',
                'display_name': 'Duplicate',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('stripe_account_id', response.data)

    @patch('apps.payments.services.stripe.connect.StripeConnectService.retrieve_account')
    def test_create_rejects_account_registered_by_another_user(self, mock_retrieve_account):
        mock_retrieve_account.return_value = self._stripe_account_mock(account_id='acct_taken_1')
        StripeConnectedAccount.objects.create(user=self.other_user, stripe_account_id='acct_taken_1')

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('payments:stripe-connect-accounts-list'),
            {
                'stripe_account_id': 'acct_taken_1',
                'display_name': 'Taken',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('stripe_account_id', response.data)

    def test_retrieve_denies_other_users_account(self):
        StripeConnectedAccount.objects.create(user=self.other_user, stripe_account_id='acct_private_1')

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            reverse('payments:stripe-connect-accounts-detail', kwargs={'stripe_account_id': 'acct_private_1'})
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_allows_event_staff_when_account_linked_to_event_method(self):
        account = StripeConnectedAccount.objects.create(
            user=self.other_user,
            stripe_account_id='acct_event_shared_1',
        )
        EventStaff.objects.create(event=self.event, user=self.user, assigned_by=self.other_user)
        PaymentMethod.objects.create(
            title='Stripe Event Method',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True,
            provided_details={'stripe_account_id': account.stripe_account_id},
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            reverse('payments:stripe-connect-accounts-detail', kwargs={'stripe_account_id': account.stripe_account_id}),
            {'event': self.event.url_safe_title},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['stripe_account_id'], account.stripe_account_id)

    def test_retrieve_denies_event_staff_when_account_not_linked_to_event_method(self):
        account = StripeConnectedAccount.objects.create(
            user=self.other_user,
            stripe_account_id='acct_event_not_linked_1',
        )
        EventStaff.objects.create(event=self.event, user=self.user, assigned_by=self.other_user)
        PaymentMethod.objects.create(
            title='Different Stripe Event Method',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True,
            provided_details={'stripe_account_id': 'acct_other_value_1'},
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            reverse('payments:stripe-connect-accounts-detail', kwargs={'stripe_account_id': account.stripe_account_id}),
            {'event': self.event.url_safe_title},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_still_denies_non_owner_even_with_event_param(self):
        account = StripeConnectedAccount.objects.create(
            user=self.other_user,
            stripe_account_id='acct_event_read_only_1',
        )
        EventStaff.objects.create(event=self.event, user=self.user, assigned_by=self.other_user)
        PaymentMethod.objects.create(
            title='Stripe Read Only Method',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True,
            provided_details={'stripe_account_id': account.stripe_account_id},
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f"{reverse('payments:stripe-connect-accounts-detail', kwargs={'stripe_account_id': account.stripe_account_id})}?event={self.event.url_safe_title}",
            {'display_name': 'Attempted Update'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_updates_allowed_fields(self):
        account = StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_patch_1')

        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            reverse('payments:stripe-connect-accounts-detail', kwargs={'stripe_account_id': 'acct_patch_1'}),
            {
                'display_name': 'Updated Name',
                'is_active': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        account.refresh_from_db()
        self.assertEqual(account.display_name, 'Updated Name')
        self.assertFalse(account.is_active)

    def test_patch_rejects_immutable_stripe_account_id(self):
        StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_immutable_1')

        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            reverse('payments:stripe-connect-accounts-detail', kwargs={'stripe_account_id': 'acct_immutable_1'}),
            {
                'stripe_account_id': 'acct_new_value',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_patch_set_primary_unsets_other_accounts(self):
        primary = StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_primary_1', is_primary=True)
        secondary = StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_secondary_1', is_primary=False)

        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            reverse('payments:stripe-connect-accounts-detail', kwargs={'stripe_account_id': secondary.stripe_account_id}),
            {
                'is_primary': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        primary.refresh_from_db()
        secondary.refresh_from_db()
        self.assertFalse(primary.is_primary)
        self.assertTrue(secondary.is_primary)

    def test_set_primary_action_unsets_other_accounts(self):
        first = StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_action_first', is_primary=True)
        second = StripeConnectedAccount.objects.create(user=self.user, stripe_account_id='acct_action_second', is_primary=False)

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('payments:stripe-connect-accounts-set-primary', kwargs={'stripe_account_id': second.stripe_account_id}),
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)


class RefundRequestAPITestCase(APITestCase):
    """Test suite for RefundRequest API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='REF001',
            display_identifier='REF001TEST001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )
        
        self.payment_method = PaymentMethod.objects.create(
            title='Stripe',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True
        )
        
        self.payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        
        self.client = APIClient()

    def _create_booking_payment_fixture(self, ticket_status=TicketStatusChoices.ACTIVE):
        booking = Booking.objects.create(event=self.event, made_by=self.regular_user)

        attendee = Attendee.objects.create(
            first_name='Alex',
            last_name='Doe',
            event=self.event,
            user=self.regular_user,
            booking=booking,
            date_of_birth=datetime.date(1990, 1, 1),
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.regular_user,
        )

        ticket_type = TicketType.objects.create(
            event=self.event,
            code=f'TICKET-{str(timezone.now().timestamp()).replace(".", "")[:10]}',
            title='General Admission',
            scope=TicketScopeChoices.FULL_EVENT,
            created_by=self.admin_user,
        )

        booking_package = BookingPackage.objects.create(
            name=f'Package-{timezone.now().timestamp()}',
            event=self.event,
            ticket_type=ticket_type,
            base_amount=Money(50, 'GBP'),
            created_by=self.admin_user,
        )

        booking_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target_type=ContentType.objects.get_for_model(Booking),
            target_id=str(booking.id),
            metadata={
                'ticket_breakdown': {}
            }
        )

        ticket = Ticket.objects.create(
            ticket_type=ticket_type,
            attendee=attendee,
            package=booking_package,
            payment=booking_payment,
            status=ticket_status,
        )

        booking_payment.metadata['ticket_breakdown'][str(ticket.ticket_id)] = {
            'amount': '50.00',
            'currency': 'GBP',
        }
        booking_payment.save(update_fields=['metadata'])

        return booking_payment, attendee, ticket

    def _create_booking_hybrid_refund_fixture(self):
        booking = Booking.objects.create(event=self.event, made_by=self.regular_user)

        attendee = Attendee.objects.create(
            first_name='Hybrid',
            last_name='Refund',
            event=self.event,
            user=self.regular_user,
            booking=booking,
            date_of_birth=datetime.date(1992, 2, 2),
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.regular_user,
        )

        ticket_type = TicketType.objects.create(
            event=self.event,
            code=f'HYBRID-{str(timezone.now().timestamp()).replace(".", "")[:10]}',
            title='Hybrid Admission',
            scope=TicketScopeChoices.FULL_EVENT,
            created_by=self.admin_user,
        )

        booking_package = BookingPackage.objects.create(
            name=f'Hybrid-Package-{timezone.now().timestamp()}',
            event=self.event,
            ticket_type=ticket_type,
            base_amount=Money('50.00', 'GBP'),
            created_by=self.admin_user,
        )

        payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money('70.00', 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target_type=ContentType.objects.get_for_model(Booking),
            target_id=str(booking.id),
            metadata={'ticket_breakdown': {}},
        )

        ticket = Ticket.objects.create(
            ticket_type=ticket_type,
            attendee=attendee,
            package=booking_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
        )

        payment.metadata['ticket_breakdown'][str(ticket.ticket_id)] = {
            'amount': '50.00',
            'currency': 'GBP',
        }
        payment.save(update_fields=['metadata'])

        order = Order.objects.create(
            customer=self.regular_user,
            attendee=attendee,
            created_by=self.regular_user,
            total_amount=Money('20.00', 'GBP'),
            status=OrderStatusChoices.COMPLETED,
            payment=payment,
        )
        order_item = OrderItem.objects.create(
            order=order,
            product_variant=None,
            quantity=1,
            unit_price=Money('20.00', 'GBP'),
            total_price=Money('20.00', 'GBP'),
            status=OrderItemStatusChoices.COMPLETED,
        )
        order.recalculate_total_amount()

        return payment, attendee, ticket, order_item

    def _create_attendee_for_booking(self, booking, first_name, last_name):
        return Attendee.objects.create(
            first_name=first_name,
            last_name=last_name,
            event=self.event,
            booking=booking,
            date_of_birth=datetime.date(1990, 1, 1),
            relationship_to_user=AttendeeRelationship.OTHER,
            defined_by=self.regular_user,
        )

    def _create_ticket_for_attendee(self, attendee, payment, amount='50.00'):
        suffix = str(timezone.now().timestamp()).replace('.', '')[-8:]
        ticket_type = TicketType.objects.create(
            event=self.event,
            code=f'TKT-{attendee.id}-{suffix}',
            title=f'Admission-{attendee.id}',
            scope=TicketScopeChoices.FULL_EVENT,
            created_by=self.admin_user,
        )
        booking_package = BookingPackage.objects.create(
            name=f'Pkg-{attendee.id}-{suffix}',
            event=self.event,
            ticket_type=ticket_type,
            base_amount=Money(amount, 'GBP'),
            created_by=self.admin_user,
        )
        ticket = Ticket.objects.create(
            ticket_type=ticket_type,
            attendee=attendee,
            package=booking_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
        )
        payment.metadata = payment.metadata or {}
        payment.metadata.setdefault('ticket_breakdown', {})
        payment.metadata['ticket_breakdown'][str(ticket.ticket_id)] = {
            'amount': amount,
            'currency': 'GBP',
        }
        payment.save(update_fields=['metadata'])
        return ticket

    def _create_order_for_attendee(self, attendee, payment, amount='30.00'):
        order = Order.objects.create(
            customer=self.regular_user,
            attendee=attendee,
            created_by=self.regular_user,
            total_amount=Money(amount, 'GBP'),
            status=OrderStatusChoices.DRAFT,
            payment=payment,
        )
        # Add an order item matching the total so Order.clean() passes on subsequent saves.
        OrderItem.objects.create(
            order=order,
            product_variant=None,
            quantity=1,
            unit_price=Money(amount, 'GBP'),
            total_price=Money(amount, 'GBP'),
        )
        order.transition_to(OrderStatusChoices.PENDING)
        order.transition_to(OrderStatusChoices.PROCESSING)
        order.transition_to(OrderStatusChoices.COMPLETED)
        order.refresh_from_db()
        return order

    def _create_order_payment_fixture(self):
        payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money('85.00', 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
        )
        order = Order.objects.create(
            customer=self.regular_user,
            created_by=self.regular_user,
            total_amount=Money('85.00', 'GBP'),
            status=OrderStatusChoices.COMPLETED,
            payment=payment,
        )
        payment.target_type = ContentType.objects.get_for_model(Order)
        payment.target_id = str(order.pk)
        payment.save(update_fields=['target_type', 'target_id'])
        item_one = OrderItem.objects.create(
            order=order,
            product_variant=None,
            quantity=1,
            unit_price=Money('25.00', 'GBP'),
            total_price=Money('25.00', 'GBP'),
        )
        item_two = OrderItem.objects.create(
            order=order,
            product_variant=None,
            quantity=2,
            unit_price=Money('30.00', 'GBP'),
            total_price=Money('60.00', 'GBP'),
        )
        order.recalculate_total_amount()
        order.refresh_from_db()
        return payment, order, item_one, item_two

    def _create_stock_backed_order_payment_fixture(self):
        product = Product.objects.create(
            title=f'Refund Stock Product {timezone.now().timestamp()}',
            event=self.event,
            base_amount=Money('30.00', 'GBP'),
            added_by=self.admin_user,
            verified=True,
            is_active=True,
        )
        variant = ProductVariant.objects.create(
            product=product,
            size=ProductSizeChoices.MEDIUM,
            color='#222222',
            stock_quantity=5,
            added_by=self.admin_user,
            verified=True,
            is_active=True,
        )

        payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money('60.00', 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
        )
        order = Order.objects.create(
            customer=self.regular_user,
            created_by=self.regular_user,
            total_amount=Money('0.00', 'GBP'),
            status=OrderStatusChoices.DRAFT,
            payment=payment,
        )
        payment.target_type = ContentType.objects.get_for_model(Order)
        payment.target_id = str(order.pk)
        payment.save(update_fields=['target_type', 'target_id'])

        order_item = OrderItem.objects.create(
            order=order,
            product_variant=variant,
            quantity=2,
            unit_price=Money('30.00', 'GBP'),
            total_price=Money('60.00', 'GBP'),
            status=OrderItemStatusChoices.COMPLETED,
        )
        variant.decrement_stock(
            2,
            reason='initial_order_deduction',
            actor=self.regular_user,
            order_id=order.order_id,
            payment_id=payment.payment_id,
            order_item_id=order_item.id,
            notes='Seed fixture reserved stock for refund flow test.',
        )

        order.recalculate_total_amount()
        return payment, order, order_item, variant
    
    def test_create_refund_request(self):
        """User can request refund for their payment."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:refundrequest-list')
        data = {
            'payment': self.payment.payment_id,
            'amount': '100.00',
            'amount_currency': 'GBP',
            'reason': 'Cannot attend the event due to personal reasons.'
        }
        response = self.client.post(url, data)
        print(response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(RefundRequest.objects.count(), 1)
    
    def test_cannot_request_refund_for_others_payment(self):
        """User cannot request refund for someone else's payment."""
        other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )
        
        self.client.force_authenticate(user=other_user)
        url = reverse('payments:refundrequest-list')
        data = {
            'payment': self.payment.payment_id,
            'amount': '100.00',
            'amount_currency': 'GBP',
            'reason': 'Cannot attend the event.'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_verify_refund_request(self):
        """Admin can verify refund request."""
        refund = RefundRequest.objects.create(
            payment=self.payment,
            amount=Money(100, 'GBP'),
            reason='Test refund reason that is long enough.',
            requested_by=self.regular_user
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:refundrequest-verify', kwargs={'refund_id': refund.refund_id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        refund.refresh_from_db()
        self.assertEqual(refund.verification_status, VerificationStatus.VERIFIED)
    
    def test_process_refund_request(self):
        """Admin can process verified refund request."""
        refund = RefundRequest.objects.create(
            payment=self.payment,
            amount=Money(100, 'GBP'),
            reason='Test refund reason that is long enough.',
            requested_by=self.regular_user
        )
        refund.mark_verified(self.admin_user)
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:refundrequest-process', kwargs={'refund_id': refund.refund_id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        refund.refresh_from_db()
        self.assertEqual(refund.verification_status, VerificationStatus.PROCESSED)
    
    def test_reject_refund_request(self):
        """Admin can reject refund request."""
        refund = RefundRequest.objects.create(
            payment=self.payment,
            amount=Money(100, 'GBP'),
            reason='Test refund reason that is long enough.',
            requested_by=self.regular_user
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:refundrequest-reject', kwargs={'refund_id': refund.refund_id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        refund.refresh_from_db()
        self.assertEqual(refund.verification_status, VerificationStatus.REJECTED)

    def test_reject_refund_restores_order_and_payment_to_completed(self):
        """Rejecting a pending order refund restores both order and payment to completed."""
        payment, order, item_one, item_two = self._create_order_payment_fixture()
        OrderItem.objects.filter(id__in=[item_one.id, item_two.id]).update(status=OrderItemStatusChoices.COMPLETED)

        self.client.force_authenticate(user=self.regular_user)
        create_response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '25.00',
                'amount_currency': 'GBP',
                'reason': 'Refunding one order item pending review.',
                'refund_items': [
                    {
                        'order_item_id': item_one.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.PENDING_REFUND)
        self.assertEqual(order.status, OrderStatusChoices.PENDING_REFUND)

        refund = RefundRequest.objects.get(payment=payment)
        self.client.force_authenticate(user=self.admin_user)
        reject_response = self.client.post(
            reverse('payments:refundrequest-reject', kwargs={'refund_id': refund.refund_id})
        )
        self.assertEqual(reject_response.status_code, status.HTTP_200_OK)

        refund.refresh_from_db()
        payment.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(refund.verification_status, VerificationStatus.REJECTED)
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(order.status, OrderStatusChoices.COMPLETED)

    def test_reject_refund_restores_order_and_payment_to_partially_refunded(self):
        """Rejecting a new refund on partially-refunded payment returns entities to partially-refunded state."""
        payment, order, item_one, item_two = self._create_order_payment_fixture()
        OrderItem.objects.filter(id=item_one.id).update(status=OrderItemStatusChoices.REFUNDED)
        OrderItem.objects.filter(id=item_two.id).update(status=OrderItemStatusChoices.COMPLETED)
        order.transition_to(OrderStatusChoices.PENDING_REFUND)
        order.transition_to(OrderStatusChoices.PARTIALLY_REFUNDED)
        payment.transition_to(PaymentStatusChoices.PARTIALLY_REFUNDED)

        self.client.force_authenticate(user=self.regular_user)
        create_response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '30.00',
                'amount_currency': 'GBP',
                'reason': 'Additional partial refund request for remaining item.',
                'refund_items': [
                    {
                        'order_item_id': item_two.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.PENDING_REFUND)
        self.assertEqual(order.status, OrderStatusChoices.PENDING_REFUND)

        refund = RefundRequest.objects.get(payment=payment)
        self.client.force_authenticate(user=self.admin_user)
        reject_response = self.client.post(
            reverse('payments:refundrequest-reject', kwargs={'refund_id': refund.refund_id})
        )
        self.assertEqual(reject_response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.PARTIALLY_REFUNDED)
        self.assertEqual(order.status, OrderStatusChoices.PARTIALLY_REFUNDED)

    def test_reject_refund_fallback_restores_when_snapshot_missing(self):
        """Reject rollback falls back safely when rollback snapshot metadata is absent."""
        payment, order, item_one, item_two = self._create_order_payment_fixture()
        OrderItem.objects.filter(id__in=[item_one.id, item_two.id]).update(status=OrderItemStatusChoices.COMPLETED)

        self.client.force_authenticate(user=self.regular_user)
        create_response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '25.00',
                'amount_currency': 'GBP',
                'reason': 'Refund request used to validate snapshot fallback path.',
                'refund_items': [
                    {
                        'order_item_id': item_one.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        refund = RefundRequest.objects.get(payment=payment)
        metadata = refund.metadata or {}
        metadata.pop('rollback_snapshot', None)
        refund.metadata = metadata
        refund.save(update_fields=['metadata'])

        self.client.force_authenticate(user=self.admin_user)
        reject_response = self.client.post(
            reverse('payments:refundrequest-reject', kwargs={'refund_id': refund.refund_id})
        )
        self.assertEqual(reject_response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(order.status, OrderStatusChoices.COMPLETED)
    
    def test_filter_refunds_by_status(self):
        """Test filtering refunds by verification status."""
        RefundRequest.objects.create(
            payment=self.payment,
            amount=Money(50, 'GBP'),
            reason='Test refund reason that is long enough.',
            requested_by=self.regular_user
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:refundrequest-list')
        response = self.client.get(url, {'verification_status': VerificationStatus.PENDING})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for refund in response.data['results']:
            self.assertEqual(refund['verification_status'], VerificationStatus.PENDING)

    def test_partial_booking_refund_requires_attendee_ids(self):
        """Partial booking refunds must include attendee_ids."""
        booking_payment, _, _ = self._create_booking_payment_fixture()

        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:refundrequest-list')
        data = {
            'payment': booking_payment.payment_id,
            'amount': '20.00',
            'amount_currency': 'GBP',
            'reason': 'Attendee cannot attend and requests a partial refund.',
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('attendee_ids', response.data)

    def test_used_ticket_refund_blocked_without_override(self):
        """Used tickets are blocked for attendee-scoped booking refunds by default."""
        booking_payment, attendee, _ = self._create_booking_payment_fixture(ticket_status=TicketStatusChoices.USED)

        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:refundrequest-list')
        data = {
            'payment': booking_payment.payment_id,
            'amount': '50.00',
            'amount_currency': 'GBP',
            'reason': 'Attendee cannot attend and requests refund for booked items.',
            'attendee_ids': [str(attendee.attendee_id)],
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('attendee_ids', response.data)

    def test_full_order_refund_without_refund_items(self):
        """Order full refunds should succeed without refund_items."""
        payment, _, _, _ = self._create_order_payment_fixture()

        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '85.00',
                'amount_currency': 'GBP',
                'reason': 'Customer requested full refund for this order payment.',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        refund = RefundRequest.objects.get(payment=payment)
        self.assertEqual(refund.amount, Money('85.00', 'GBP'))
        self.assertEqual((refund.metadata or {}).get('refund_scope'), 'full_target')

    def test_partial_order_refund_requires_refund_items(self):
        """Order partial refunds must provide refund_items for granular targeting."""
        payment, _, _, _ = self._create_order_payment_fixture()

        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '25.00',
                'amount_currency': 'GBP',
                'reason': 'Partial refund requested without item selection.',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('refund_items', response.data)

    def test_hybrid_booking_refund_supports_attendee_and_order_items_in_one_request(self):
        """Booking refunds can combine attendee ticket scope and selected booking order items in a single request."""
        payment, attendee, _, order_item = self._create_booking_hybrid_refund_fixture()

        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '70.00',
                'amount_currency': 'GBP',
                'reason': 'Refund attendee package plus selected booking order item together.',
                'attendee_ids': [str(attendee.attendee_id)],
                'refund_items': [
                    {
                        'attendee_id': str(attendee.attendee_id),
                        'order_item_id': order_item.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        refund = RefundRequest.objects.get(payment=payment)
        metadata = refund.metadata or {}
        self.assertEqual(metadata.get('refund_scope'), 'hybrid_booking_attendees_and_products')
        self.assertEqual(refund.associations.count(), 2)
        association_models = {
            association.target_type.model
            for association in refund.associations.select_related('target_type').all()
        }
        self.assertIn('ticket', association_models)
        self.assertIn('orderitem', association_models)

    def test_partial_order_refund_single_item(self):
        """Order partial refunds support single item targeting with exact amount matching."""
        payment, _, item_one, _ = self._create_order_payment_fixture()

        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '25.00',
                'amount_currency': 'GBP',
                'reason': 'Refunding one item from the larger order.',
                'refund_items': [
                    {
                        'order_item_id': item_one.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        refund = RefundRequest.objects.get(payment=payment)
        self.assertEqual((refund.metadata or {}).get('refund_scope'), 'targeted_order_items')
        self.assertEqual(len((refund.metadata or {}).get('selected_refund_items', [])), 1)
        self.assertEqual(refund.associations.count(), 1)
        association = refund.associations.first()
        self.assertEqual(getattr(association.target_object, 'id', None), item_one.id)

    def test_partial_order_refund_amount_mismatch_rejected(self):
        """Order targeted refunds must match amount to selected item total."""
        payment, _, item_one, _ = self._create_order_payment_fixture()

        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '30.00',
                'amount_currency': 'GBP',
                'reason': 'Refunding one item with incorrect amount provided.',
                'refund_items': [
                    {
                        'order_item_id': item_one.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)

    def test_itemized_refunds_update_stock_and_order_item_totals(self):
        """Processing itemized partial/full refunds should restore stock and reduce order-item totals progressively."""
        payment, order, order_item, variant = self._create_stock_backed_order_payment_fixture()
        self.assertEqual(variant.stock_quantity, 3)

        self.client.force_authenticate(user=self.regular_user)
        first_refund_response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '30.00',
                'amount_currency': 'GBP',
                'reason': 'Partial refund for one unit from the order item.',
                'refund_items': [
                    {
                        'order_item_id': order_item.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(first_refund_response.status_code, status.HTTP_201_CREATED)

        first_refund = RefundRequest.objects.filter(payment=payment).latest('requested_at')
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-verify', kwargs={'refund_id': first_refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-process', kwargs={'refund_id': first_refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )

        order_item.refresh_from_db()
        order.refresh_from_db()
        payment.refresh_from_db()
        variant.refresh_from_db()

        self.assertEqual(variant.stock_quantity, 4)
        self.assertEqual(order_item.quantity, 1)
        self.assertEqual(order_item.total_price, Money('30.00', 'GBP'))
        self.assertEqual(order_item.status, OrderItemStatusChoices.COMPLETED)
        self.assertEqual(order.total_amount, Money('30.00', 'GBP'))
        self.assertEqual(order.status, OrderStatusChoices.PARTIALLY_REFUNDED)
        self.assertEqual(payment.status, PaymentStatusChoices.PARTIALLY_REFUNDED)

        self.client.force_authenticate(user=self.regular_user)
        second_refund_response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '30.00',
                'amount_currency': 'GBP',
                'reason': 'Final refund for remaining unit from the order item.',
                'refund_items': [
                    {
                        'order_item_id': order_item.id,
                        'quantity': 1,
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(second_refund_response.status_code, status.HTTP_201_CREATED)

        second_refund = RefundRequest.objects.filter(payment=payment).latest('requested_at')
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-verify', kwargs={'refund_id': second_refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-process', kwargs={'refund_id': second_refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )

        order_item.refresh_from_db()
        order.refresh_from_db()
        payment.refresh_from_db()
        variant.refresh_from_db()

        self.assertEqual(variant.stock_quantity, 5)
        self.assertEqual(order_item.quantity, 0)
        self.assertEqual(order_item.total_price, Money('0.00', 'GBP'))
        self.assertEqual(order_item.status, OrderItemStatusChoices.REFUNDED)
        self.assertEqual(order.total_amount, Money('0.00', 'GBP'))
        self.assertEqual(order.status, OrderStatusChoices.REFUNDED)
        self.assertEqual(payment.status, PaymentStatusChoices.REFUNDED)

    def test_scenario_single_attendee_full_refund_invalidates_ticket_and_order(self):
        """Scenario 1: one attendee full refund invalidates linked ticket and order."""
        booking = Booking.objects.create(event=self.event, made_by=self.regular_user)
        attendee = self._create_attendee_for_booking(booking, 'Solo', 'User')

        payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money('80.00', 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target_type=ContentType.objects.get_for_model(Booking),
            target_id=str(booking.id),
            metadata={'ticket_breakdown': {}},
        )
        ticket = self._create_ticket_for_attendee(attendee, payment, amount='50.00')
        order = self._create_order_for_attendee(attendee, payment, amount='30.00')

        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:refundrequest-list')
        create_data = {
            'payment': payment.payment_id,
            'amount': '80.00',
            'amount_currency': 'GBP',
            'reason': 'Full attendee cancellation refund for single booking attendee.',
            'reason_code': 'single_attendee_full',
        }
        with self.assertLogs('apps.payments.api.viewsets', level='INFO') as create_logs:
            create_response = self.client.post(url, create_data, format='json')

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(any('Refund request created' in entry for entry in create_logs.output))

        refund = RefundRequest.objects.get(payment=payment)
        self.client.force_authenticate(user=self.admin_user)
        verify_url = reverse('payments:refundrequest-verify', kwargs={'refund_id': refund.refund_id})
        verify_response = self.client.post(verify_url)
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)

        process_url = reverse('payments:refundrequest-process', kwargs={'refund_id': refund.refund_id})
        with self.assertLogs('apps.payments.services.attendee_refunds', level='INFO') as finalize_logs:
            process_response = self.client.post(process_url)

        self.assertEqual(process_response.status_code, status.HTTP_200_OK)
        self.assertTrue(any('Refund finalized' in entry for entry in finalize_logs.output))

        ticket.refresh_from_db()
        order.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(ticket.status, TicketStatusChoices.CANCELLED)
        self.assertEqual(ticket.uses, 0)
        self.assertEqual(order.status, OrderStatusChoices.REFUNDED)
        self.assertEqual(payment.status, PaymentStatusChoices.REFUNDED)

    def test_scenario_two_attendees_full_refund_invalidates_both(self):
        """Scenario 2: two-attendee booking full refund invalidates both attendees' tickets."""
        booking = Booking.objects.create(event=self.event, made_by=self.regular_user)
        attendee_one = self._create_attendee_for_booking(booking, 'Parent', 'One')
        attendee_two = self._create_attendee_for_booking(booking, 'Child', 'Two')

        payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money('100.00', 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target_type=ContentType.objects.get_for_model(Booking),
            target_id=str(booking.id),
            metadata={'ticket_breakdown': {}},
        )

        ticket_one = self._create_ticket_for_attendee(attendee_one, payment, amount='50.00')
        ticket_two = self._create_ticket_for_attendee(attendee_two, payment, amount='50.00')

        self.client.force_authenticate(user=self.regular_user)
        create_response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '100.00',
                'amount_currency': 'GBP',
                'reason': 'Full booking refund for two attendees due to cancellation.',
                'reason_code': 'two_attendee_full',
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        refund = RefundRequest.objects.get(payment=payment)
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-verify', kwargs={'refund_id': refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-process', kwargs={'refund_id': refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )

        ticket_one.refresh_from_db()
        ticket_two.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(ticket_one.status, TicketStatusChoices.CANCELLED)
        self.assertEqual(ticket_two.status, TicketStatusChoices.CANCELLED)
        self.assertEqual(payment.status, PaymentStatusChoices.REFUNDED)

    def test_scenario_two_attendees_partial_refund_selected_attendee_only(self):
        """Scenario 3: partial booking refund only affects selected attendee and marks payment partial."""
        booking = Booking.objects.create(event=self.event, made_by=self.regular_user)
        attendee_one = self._create_attendee_for_booking(booking, 'Selected', 'Attendee')
        attendee_two = self._create_attendee_for_booking(booking, 'Unaffected', 'Attendee')

        payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money('100.00', 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target_type=ContentType.objects.get_for_model(Booking),
            target_id=str(booking.id),
            metadata={'ticket_breakdown': {}},
        )

        selected_ticket = self._create_ticket_for_attendee(attendee_one, payment, amount='50.00')
        unaffected_ticket = self._create_ticket_for_attendee(attendee_two, payment, amount='50.00')

        self.client.force_authenticate(user=self.regular_user)
        create_response = self.client.post(
            reverse('payments:refundrequest-list'),
            {
                'payment': payment.payment_id,
                'amount': '50.00',
                'amount_currency': 'GBP',
                'reason': 'Partial attendee refund selecting one attendee from booking.',
                'reason_code': 'two_attendee_partial',
                'attendee_ids': [str(attendee_one.attendee_id)],
            },
            format='json',
        )
        print(create_response.data)
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        refund = RefundRequest.objects.get(payment=payment)
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-verify', kwargs={'refund_id': refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )

        selected_ticket.refresh_from_db()
        unaffected_ticket.refresh_from_db()
        payment.refresh_from_db()

        # Verify-stage blocking means selected ticket cannot be used, but is not finalized yet.
        self.assertFalse(selected_ticket.is_valid)
        self.assertTrue(unaffected_ticket.is_valid)
        self.assertEqual(payment.status, PaymentStatusChoices.PARTIALLY_REFUNDED)

        self.assertEqual(
            self.client.post(reverse('payments:refundrequest-process', kwargs={'refund_id': refund.refund_id})).status_code,
            status.HTTP_200_OK,
        )

        selected_ticket.refresh_from_db()
        unaffected_ticket.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(selected_ticket.status, TicketStatusChoices.CANCELLED)
        self.assertEqual(unaffected_ticket.status, TicketStatusChoices.ACTIVE)
        self.assertEqual(payment.status, PaymentStatusChoices.PARTIALLY_REFUNDED)


class DiscountAPITestCase(APITestCase):
    """Test suite for Discount API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='DIS001',
            display_identifier='DIS001TEST001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        from django.contrib.contenttypes.models import ContentType
        # Note: target_type and target_id should be set internally via business logic,
        # not through the API. For testing model creation directly, we still use them.
        self.discount = Discount.objects.create(
            name='Early Bird',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            target_type=ContentType.objects.get_for_model(self.event),
            target_id=self.event.id,
            active=True,
            created_by=self.admin_user
        )
        
        self.client = APIClient()
    
    def test_list_discounts_as_admin(self):
        """Admin can list discounts."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:discount-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    # def test_list_discounts_as_regular_user(self):
    #     """Regular users cannot list discounts."""
    #     self.client.force_authenticate(user=self.regular_user)
    #     url = reverse('payments:discount-list')
    #     response = self.client.get(url)
        
    #     self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ! You cannot create percentage discounts via payments in general as they need target info
    
    # def test_create_percentage_discount(self): 
    #     """Admin can create percentage discount.
        
    #     Note: target_type and target_id are internal fields and should not be
    #     set via API in production. They should be set programmatically.
    #     """
    #     self.client.force_authenticate(user=self.admin_user)
    #     url = reverse('payments:discount-list')
        
    #     # Create discount without target fields (as would happen in production)
    #     data = {
    #         'name': 'Student Discount',
    #         'discount_type': DiscountType.PERCENTAGE,
    #         'percentage': '15.00',
    #         'active': True,
    #     }
    #     response = self.client.post(url, data)
        
    #     self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    #     self.assertEqual(Discount.objects.count(), 2)
    #     # Verify target fields are not exposed in response
    #     self.assertNotIn('target_type', response.data)
    #     self.assertNotIn('target_id', response.data)
    #     self.assertNotIn('target_details', response.data)
    
    # def test_create_fixed_discount(self):
    #     """Admin can create fixed amount discount.
        
    #     Note: target_type and target_id are internal fields and should not be
    #     set via API in production. They should be set programmatically.
    #     """
    #     self.client.force_authenticate(user=self.admin_user)
    #     url = reverse('payments:discount-list')
        
    #     # Create discount without target fields (as would happen in production)
    #     data = {
    #         'name': 'Loyalty Discount',
    #         'discount_type': DiscountType.FIXED,
    #         'amount': '25.00',
    #         'amount_currency': 'GBP',
    #         'active': True
    #     }
    #     response = self.client.post(url, data)
        
    #     self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    #     # Verify target fields are not exposed in response
    #     self.assertNotIn('target_type', response.data)
    #     self.assertNotIn('target_id', response.data)
    #     self.assertNotIn('target_details', response.data)


class DonationAPITestCase(APITestCase):
    """Test suite for Donation API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )

        self.other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )

        self.non_admin_user = User.objects.create_user(
            username='member',
            email='member@test.com',
            password='testpass123'
        )
        
        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='DON001',
            display_identifier='DON001TEST001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.payment_method = PaymentMethod.objects.create(
            title='Stripe',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True
        )

        self.cash_method = PaymentMethod.objects.create(
            title='Cash',
            event=self.event,
            method_type=PaymentMethodTypeChoices.CASH,
            is_active=True
        )

        admin_role = EventRole.objects.create(
            name='Event Admin',
            code='EVADM2',
            category=EventRoleCategoryChoices.ADMINISTRATIVE,
        )
        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.admin_user,
            role=admin_role,
        )

        Attendee.objects.create(
            first_name='Other',
            last_name='User',
            relationship_to_user='self',
            event=self.event,
            user=self.other_user,
            defined_by=self.admin_user,
            date_of_birth=datetime.date(1990, 1, 1)
        )
        
        self.payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        
        self.client = APIClient()
    
    def test_create_donation(self):
        """User can create donation on their completed payment."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:donation-list')
        data = {
            'payment': self.payment.id,
            'amount': '20.00',
            'amount_currency': 'GBP'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Donation.objects.count(), 1)
    
    def test_cannot_donate_on_pending_payment(self):
        """Cannot create donation on pending payment."""
        pending_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.PENDING
        )
        
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:donation-list')
        data = {
            'payment': pending_payment.id,
            'amount': '10.00',
            'amount_currency': 'GBP'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_list_donations(self):
        """User can list their donations."""
        Donation.objects.create(
            payment=self.payment,
            amount=Money(15, 'GBP'),
            donated_by=self.regular_user
        )
        
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:donation-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_create_donation_with_payment_for_selected_user_as_admin(self):
        """Event admin can create donation+payment for a selected event attendee user."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:donation-create-with-payment')
        data = {
            'amount': '30.00',
            'payment_method_id': self.cash_method.id,
            'event_id': str(self.event.event_id),
            'user_id': self.other_user.id,
            'message': 'Admin recorded donation',
        }

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        donation = Donation.objects.get(donation_id=response.data['donation_id'])
        self.assertEqual(donation.donated_by, self.other_user)
        self.assertIsNotNone(donation.payment)
        self.assertEqual(donation.payment.user, self.other_user)

    def test_create_donation_with_payment_rejects_non_admin_selected_user(self):
        """Non-admin users cannot create donation+payment on behalf of other users."""
        self.client.force_authenticate(user=self.non_admin_user)
        url = reverse('payments:donation-create-with-payment')
        data = {
            'amount': '20.00',
            'payment_method_id': self.cash_method.id,
            'event_id': str(self.event.event_id),
            'user_id': self.other_user.id,
        }

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('user_id', response.data)

    def test_create_donation_with_payment_rejects_user_outside_event(self):
        """Selected donor must belong to event attendee/service-team membership."""
        outsider = User.objects.create_user(
            username='outsider',
            email='outsider@test.com',
            password='testpass123',
        )
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:donation-create-with-payment')
        data = {
            'amount': '20.00',
            'payment_method_id': self.cash_method.id,
            'event_id': str(self.event.event_id),
            'user_id': outsider.id,
        }

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('user_id', response.data)

    @patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.create')
    def test_create_donation_with_stripe_payment_uses_connected_account(self, mock_create):
        """Stripe donation checkout should pass the connected Stripe account to PaymentIntent creation."""
        self.payment_method.provided_details = {'stripe_account_id': 'acct_test123'}
        self.payment_method.save(update_fields=['provided_details'])

        mock_payment_intent = Mock()
        mock_payment_intent.id = 'pi_test123'
        mock_payment_intent.client_secret = 'pi_test123_secret_abc'
        mock_create.return_value = mock_payment_intent

        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:donation-create-with-payment')
        data = {
            'amount': '20.00',
            'payment_method_id': self.payment_method.id,
            'event_id': str(self.event.event_id),
        }

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(mock_create.call_args.kwargs['stripe_account_id'], 'acct_test123')


class PermissionsTestCase(APITestCase):
    """Test suite for payment permissions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.superuser = User.objects.create_user(
            username='super',
            email='super@test.com',
            password='testpass123',
            is_superuser=True
        )
        
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@test.com',
            password='testpass123',
            is_staff=True
        )
        
        self.admin_role_user = User.objects.create_user(
            username='eventadmin',
            email='eventadmin@test.com',
            password='testpass123'
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.superuser
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='PER001',
            display_identifier='PER001TEST001',
            created_by=self.superuser,
            event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create administrative role
        admin_role = EventRole.objects.create(
            name='Event Admin',
            code='EVADM',
            category=EventRoleCategoryChoices.ADMINISTRATIVE
        )
        
        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.admin_role_user,
            role=admin_role
        )
        
        self.payment_method = PaymentMethod.objects.create(
            title='Stripe',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True
        )
        
        self.payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        
        self.client = APIClient()
    
    def test_superuser_has_full_access(self):
        """Superuser has full access to all payments."""
        self.client.force_authenticate(user=self.superuser)
        url = reverse('payments:payment-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_staff_user_has_full_access(self):
        """Staff user has full access to all payments."""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('payments:payment-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_event_admin_has_access_to_event_payments(self):
        """User with ADMINISTRATIVE role can access event payments."""
        self.client.force_authenticate(user=self.admin_role_user)
        url = reverse('payments:payment-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_payment_owner_can_view_own_payment(self):
        """Payment owner can view their own payment."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:payment-detail', kwargs={'payment_id': self.payment.payment_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_unauthenticated_user_denied(self):
        """Unauthenticated users are denied access."""
        url = reverse('payments:payment-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class FilteringTestCase(APITestCase):
    """Test suite for advanced filtering."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_superuser=True
        )
        
        self.user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        from apps.organisations.models import Organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='FIL001',
            display_identifier='FIL001TEST001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.payment_method = PaymentMethod.objects.create(
            title='Stripe',
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True
        )
        
        # Create multiple payments with different statuses and amounts
        Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.PENDING
        )
        
        Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        
        Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(150, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)
    
    def test_filter_by_status(self):
        """Test filtering by payment status."""
        url = reverse('payments:payment-list')
        response = self.client.get(url, {'status': PaymentStatusChoices.COMPLETED})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
    
    def test_filter_by_amount_range(self):
        """Test filtering by amount range."""
        url = reverse('payments:payment-list')
        response = self.client.get(url, {'min_amount': '75', 'max_amount': '125'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_filter_by_user(self):
        """Test filtering by user."""
        url = reverse('payments:payment-list')
        response = self.client.get(url, {'user': self.user.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 3)


# ============================================================================
# DEBIT EXPENSE API TESTS
# ============================================================================

class DebitExpenseAPITestCase(APITestCase):
    """Test suite for DebitExpense API endpoints."""

    def setUp(self):
        from apps.organisations.models import Organisation
        self.admin_user = User.objects.create_user(
            username='debit_admin', email='debit_admin@test.com', password='pass', is_staff=True, is_superuser=True
        )
        self.event_manager = User.objects.create_user(
            username='debit_mgr', email='debit_mgr@test.com', password='pass'
        )
        self.other_user = User.objects.create_user(
            username='debit_other', email='debit_other@test.com', password='pass'
        )
        self.org = Organisation.objects.create(title='Debit Org', created_by=self.admin_user)
        event_type = EventType.objects.create(title='Conference', code='DCONF')
        self.event = Event.objects.create(
            title='Debit Event', display_code='DEB001', display_identifier='DEB001TEST001',
            created_by=self.admin_user, event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN, organisation=self.org
        )
        admin_role = EventRole.objects.create(name='Admin', code='ADM1', category=EventRoleCategoryChoices.ADMINISTRATIVE)
        EventRoleAssignment.objects.create(event=self.event, user=self.event_manager, role=admin_role)

        self.payment_method = PaymentMethod.objects.create(
            method_type=PaymentMethodTypeChoices.CASH, 
            title='Cash', 
            created_by=self.admin_user,
            event=self.event
        )
        self.client = APIClient()

    def _create_debit(self, user=None, event=None, quantity=2, unit_price='50.00', description='Estimated ticket sales'):
        user = user or self.event_manager
        event = event or self.event
        client = APIClient()
        client.force_authenticate(user=user)
        url = reverse('payments:debitexpense-list')
        data = client.post(url, {
            'event': str(event.url_safe_title),
            'quantity': quantity,
            'unit_price': unit_price,
            'description': description,
            'expense_type': DebitExpenseTypeChoices.TICKET_SALES,
        }, format='json')

        self.assertEqual(data.status_code, status.HTTP_201_CREATED, msg=f"Debit creation failed: {data.data}")
        self.assertIn('debit_id', data.data, msg=f"Response missing debit_id: {data.data}")
        return data

    def test_create_debit_expense(self):
        """Authenticated event manager can create a debit expense."""
        response = self._create_debit()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('debit_id', response.data)

    def test_debit_amount_auto_computed(self):
        """amount = quantity × unit_price on save."""
        response = self._create_debit(quantity=3, unit_price='50.00')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        debit = DebitExpense.objects.get(debit_id=response.data['debit_id'])
        self.assertEqual(debit.amount.amount, Decimal('150.00'))

    def test_debit_rejects_target_fields_from_api(self):
        """target_type and target_id must not be accepted via API."""
        self.client.force_authenticate(user=self.event_manager)
        url = reverse('payments:debitexpense-list')
        response = self.client.post(url, {
            'event': str(self.event.event_id),
            'quantity': 1,
            'unit_price': '10.00',
            'description': 'Test should be 10 chars long',
            'expense_type': DebitExpenseTypeChoices.TICKET_SALES,
            'target_type': 1,
            'target_id': 1,
        }, format='json')
        # Must succeed but target fields silently ignored (not persisted)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=f"API should reject target fields: {response.data}")

    def test_debit_rejects_amount_field_from_api(self):
        """Providing amount in payload does not override computed value."""
        self.client.force_authenticate(user=self.event_manager)
        url = reverse('payments:debitexpense-list')
        response = self.client.post(url, {
            'event': str(self.event.event_id),
            'quantity': 2,
            'unit_price': '25.00',
            'description': 'Test should be 10 chars long',
            'expense_type': DebitExpenseTypeChoices.TICKET_SALES,
            'amount': '999.00',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=f"API should reject amount field: {response.data}")

    def test_debit_verification_status_transitions(self):
        """Pending → verified → processed status transitions work via PATCH."""
        create_resp = self._create_debit()
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        debit_id = create_resp.data['debit_id']

        # Mark verified (admin)
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:debitexpense-detail', kwargs={'debit_id': debit_id})
        resp = self.client.patch(url, {'verification_status': 'verified'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['verification_status'], 'verified')

        # Mark processed
        resp = self.client.patch(url, {'verification_status': 'processed'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['verification_status'], 'processed')

    def test_debit_permission_unauthenticated(self):
        """Unauthenticated access to debit list is denied."""
        url = reverse('payments:debitexpense-list')
        response = APIClient().get(url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


# ============================================================================
# BUDGET PROPOSAL API TESTS
# ============================================================================

class BudgetProposalAPITestCase(APITestCase):
    """Test suite for BudgetProposal API endpoints."""

    def setUp(self):
        from apps.organisations.models import Organisation
        self.admin_user = User.objects.create_user(
            username='bp_admin', email='bp_admin@test.com', password='pass', is_staff=True, is_superuser=True
        )
        self.event_manager = User.objects.create_user(
            username='bp_mgr', email='bp_mgr@test.com', password='pass'
        )
        self.org = Organisation.objects.create(title='BP Org', created_by=self.admin_user)
        event_type = EventType.objects.create(title='Workshop', code='BPWKS')
        self.event = Event.objects.create(
            title='BP Event', display_code='BP0001', display_identifier='BP0001TEST001',
            created_by=self.admin_user, event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN, organisation=self.org
        )
        self.other_event = Event.objects.create(
            title='Other Event', display_code='BP0002', display_identifier='BP0002TEST001',
            created_by=self.admin_user, event_type=event_type,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
            end_datetime=timezone.now() + timezone.timedelta(days=32),
            status=EventStatusChoices.OPEN, organisation=self.org
        )
        admin_role = EventRole.objects.create(name='BP Admin', code='BPADM', category=EventRoleCategoryChoices.ADMINISTRATIVE)
        EventRoleAssignment.objects.create(event=self.event, user=self.event_manager, role=admin_role)

        self.payment_method = PaymentMethod.objects.create(
            method_type=PaymentMethodTypeChoices.CASH, 
            title='BPCash', 
            created_by=self.admin_user,
            event=self.event
        )

        # Create a credit and debit for self.event
        self.credit = CreditExpense.objects.create(
            event=self.event, amount=Money(200, 'GBP'), description='Venue hire',
            expense_type=CreditExpenseTypeChoices.VENUE_COST, created_by=self.event_manager
        )
        self.debit = DebitExpense.objects.create(
            event=self.event, quantity=10, unit_price=Money(30, 'GBP'),
            description='Ticket sales', expense_type=DebitExpenseTypeChoices.TICKET_SALES,
            created_by=self.event_manager
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.event_manager)

    def _create_proposal(self, title='Q1 Budget', event=None):
        event = event or self.event
        url = reverse('payments:budgetproposal-list')
        data = self.client.post(url, {
            'event': str(event.url_safe_title),
            'proposal_title': title,
            'proposal_description': 'Test budget',
        }, format='json')
        self.assertEqual(data.status_code, status.HTTP_201_CREATED)
        self.assertIn('proposal_id', data.data)
        return data

    def test_create_budget_proposal(self):
        """Authenticated event manager can create a budget proposal."""
        response = self._create_proposal()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('proposal_id', response.data)

    def test_add_credit_to_proposal(self):
        """POST add-credit/ links a credit expense to the proposal."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        url = reverse('payments:budgetproposal-add-credit', kwargs={'proposal_id': proposal_id})
        response = self.client.post(url, {'credit_id': str(self.credit.credit_id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_add_debit_to_proposal(self):
        """POST add-debit/ links a debit expense to the proposal."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        url = reverse('payments:budgetproposal-add-debit', kwargs={'proposal_id': proposal_id})
        response = self.client.post(url, {'debit_id': str(self.debit.debit_id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_remove_credit_from_proposal(self):
        """POST remove-credit/ unlinks a credit expense from the proposal."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        add_url = reverse('payments:budgetproposal-add-credit', kwargs={'proposal_id': proposal_id})
        self.client.post(add_url, {'credit_id': str(self.credit.credit_id)}, format='json')
        remove_url = reverse('payments:budgetproposal-remove-credit', kwargs={'proposal_id': proposal_id})
        response = self.client.post(remove_url, {'credit_id': str(self.credit.credit_id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        proposal = BudgetProposal.objects.get(proposal_id=proposal_id)
        self.assertNotIn(self.credit, proposal.credit_expenses.all())

    def test_proposal_statistics_endpoint(self):
        """GET {id}/statistics/ returns budget summary figures."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        # Attach credit and debit
        self.client.post(
            reverse('payments:budgetproposal-add-credit', kwargs={'proposal_id': proposal_id}),
            {'credit_id': str(self.credit.credit_id)}, format='json'
        )
        self.client.post(
            reverse('payments:budgetproposal-add-debit', kwargs={'proposal_id': proposal_id}),
            {'debit_id': str(self.debit.debit_id)}, format='json'
        )
        url = reverse('payments:budgetproposal-statistics', kwargs={'proposal_id': proposal_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('estimated_inbound', response.data)
        self.assertIn('total_outgoing', response.data)
        self.assertIn('health_status', response.data)

    def test_event_budget_statistics_endpoint(self):
        """GET event-statistics/?event_id=... returns aggregated stats for the event."""
        self._create_proposal()
        url = reverse('payments:budgetproposal-event-statistics')
        response = self.client.get(url, {'event_id': str(self.event.event_id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('event_id', response.data)

    def test_proposal_verification_workflow(self):
        """Proposal can be verified and processed by admin."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('payments:budgetproposal-detail', kwargs={'proposal_id': proposal_id})
        resp = self.client.patch(url, {'verification_status': 'verified'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['verification_status'], 'verified')

    def test_credit_must_belong_to_same_event_as_proposal(self):
        """Cannot link a credit from a different event to a proposal."""
        # Create a credit on the other event
        other_credit = CreditExpense.objects.create(
            event=self.other_event, amount=Money(100, 'GBP'), description='Other',
            expense_type=CreditExpenseTypeChoices.VENUE_COST, created_by=self.admin_user
        )
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        url = reverse('payments:budgetproposal-add-credit', kwargs={'proposal_id': proposal_id})
        response = self.client.post(url, {'credit_id': str(other_credit.credit_id)}, format='json')
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN])

    def test_debit_must_belong_to_same_event_as_proposal(self):
        """Cannot link a debit from a different event to a proposal."""
        other_debit = DebitExpense.objects.create(
            event=self.other_event, quantity=1, unit_price=Money(10, 'GBP'),
            description='Other', expense_type=DebitExpenseTypeChoices.TICKET_SALES,
            created_by=self.admin_user
        )
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        url = reverse('payments:budgetproposal-add-debit', kwargs={'proposal_id': proposal_id})
        response = self.client.post(url, {'debit_id': str(other_debit.debit_id)}, format='json')
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN])

    def test_health_status_surplus(self):
        """Health status is SURPLUS when real inbound > total outgoing."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        # Attach credit (£200 outgoing)
        self.client.post(
            reverse('payments:budgetproposal-add-credit', kwargs={'proposal_id': proposal_id}),
            {'credit_id': str(self.credit.credit_id)}, format='json'
        )
        # Create a completed payment of £500 (more than £200 outgoing)
        Payment.objects.create(
            user=self.event_manager, event=self.event, method=self.payment_method,
            base_amount=Money(500, 'GBP'), status=PaymentStatusChoices.COMPLETED
        )
        url = reverse('payments:budgetproposal-statistics', kwargs={'proposal_id': proposal_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['health_status'], 'SURPLUS')

    def test_health_status_deficit(self):
        """Health status is DEFICIT when real inbound < total outgoing."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        # Attach credit (£200 outgoing)
        self.client.post(
            reverse('payments:budgetproposal-add-credit', kwargs={'proposal_id': proposal_id}),
            {'credit_id': str(self.credit.credit_id)}, format='json'
        )
        # Create a completed payment of £50 (less than £200 outgoing)
        Payment.objects.create(
            user=self.event_manager, event=self.event, method=self.payment_method,
            base_amount=Money(50, 'GBP'), status=PaymentStatusChoices.COMPLETED
        )
        url = reverse('payments:budgetproposal-statistics', kwargs={'proposal_id': proposal_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['health_status'], 'DEFICIT')

    def test_health_status_unknown_no_payments(self):
        """Health status is UNKNOWN when there are no completed payments."""
        proposal_resp = self._create_proposal()
        proposal_id = proposal_resp.data['proposal_id']
        url = reverse('payments:budgetproposal-statistics', kwargs={'proposal_id': proposal_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['health_status'], 'UNKNOWN')