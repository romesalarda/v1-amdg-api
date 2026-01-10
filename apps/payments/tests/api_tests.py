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
from django.urls import reverse
from django.utils import timezone
from djmoney.money import Money
from decimal import Decimal

from apps.payments.models import (
    Payment, PaymentMethod, PaymentStatusChoices, PaymentMethodTypeChoices,
    Discount, DiscountRule, DiscountType, DiscountRuleTypeChoices,
    RefundRequest, RefundPolicy, RefundPolicyTypeChoices,
    Donation, PaymentHistoryAction
)
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventType, EventRole, EventRoleAssignment, EventRoleCategoryChoices, EventStatusChoices

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
        
        # Create test payment
        self.payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
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
            method=self.payment_method,
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
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


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
    
    def test_list_payment_methods_as_regular_user(self):
        """Regular users cannot list payment methods."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:paymentmethod-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
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
            organisation=self.organisation
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
    
    def test_create_refund_request(self):
        """User can request refund for their payment."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:refundrequest-list')
        data = {
            'payment': self.payment.id,
            'amount': '100.00',
            'amount_currency': 'GBP',
            'reason': 'Cannot attend the event due to personal reasons.'
        }
        response = self.client.post(url, data)
        
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
            'payment': self.payment.id,
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
    
    def test_list_discounts_as_regular_user(self):
        """Regular users cannot list discounts."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('payments:discount-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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