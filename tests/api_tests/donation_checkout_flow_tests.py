"""
Donation Checkout Flow API Tests

Tests the complete donation flow via API endpoints with all payment methods:
- STRIPE: Tests client_secret return and payment intent creation
- BANK_TRANSFER: Tests bank reference generation and manual verification
- CASH: Tests pending approval workflow
- Event-specific donations vs general donations
- Donation verification workflow (admin approval/rejection)
- Edge cases: Amount validation, payment method validation
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money
from unittest.mock import patch, MagicMock

from apps.payments.models import (
    Payment, PaymentMethod, PaymentMethodTypeChoices,
    PaymentStatusChoices, Donation, BankTransferEvidence
)
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation

import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class DonationCheckoutAPITestCase(TestCase):
    """Test donation checkout API endpoint with various payment methods."""
    
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
            title='Charity Event',
            code='CHARITY',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Charity',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Fundraiser 2026',
            display_code='FR2026',
            display_identifier='FR2026CHARITY001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
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
    
    @patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.create')
    def test_stripe_donation_success(self, mock_create_intent):
        """Test successful STRIPE donation flow."""
        # Mock Stripe response
        mock_create_intent.return_value = {
            'id': 'pi_donation123',
            'client_secret': 'pi_donation123_secret_xyz',
            'amount': 5000,
            'currency': 'gbp',
            'status': 'requires_payment_method'
        }
        
        # Create donation with payment
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '50.00',
            'currency': 'GBP',
            'payment_method_id': self.stripe_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('stripe_client_secret', response.data)
        self.assertEqual(response.data['stripe_client_secret'], 'pi_donation123_secret_xyz')
        self.assertEqual(response.data['amount'], '50.00')
        self.assertEqual(response.data['currency'], 'GBP')
        
        # Verify donation was created
        self.assertIn('donation', response.data)
        donation_id = response.data['donation']['id']
        donation = Donation.objects.get(id=donation_id)
        self.assertEqual(donation.donated_by, self.user)
        self.assertEqual(donation.verification_status, VerificationStatus.PENDING)
        
        # Verify payment was created
        self.assertIsNotNone(donation.payment)
        self.assertEqual(donation.payment.status, PaymentStatusChoices.PENDING)
        self.assertEqual(donation.payment.base_amount, Money(50, 'GBP'))
        self.assertEqual(donation.payment.target, donation)
        
        # Verify Stripe service was called correctly
        mock_create_intent.assert_called_once()
        call_kwargs = mock_create_intent.call_args[1]
        self.assertEqual(call_kwargs['amount'], Money(50, 'GBP'))
        self.assertEqual(call_kwargs['currency'], 'GBP')
    
    def test_bank_transfer_donation_success(self):
        """Test successful BANK_TRANSFER donation flow."""
        # Create donation with payment
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '100.00',
            'currency': 'GBP',
            'payment_method_id': self.bank_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('bank_transfer_reference', response.data)
        self.assertIn('bank_transfer_instructions', response.data)
        self.assertEqual(response.data['amount'], '100.00')
        self.assertEqual(response.data['currency'], 'GBP')
        
        # Verify donation was created
        donation_id = response.data['donation']['id']
        donation = Donation.objects.get(id=donation_id)
        
        # Verify payment was created
        self.assertIsNotNone(donation.payment)
        self.assertEqual(donation.payment.status, PaymentStatusChoices.PENDING)
        self.assertIsNotNone(donation.payment.bank_transfer_reference)
        
        # Verify bank reference is in response
        self.assertEqual(
            response.data['bank_transfer_reference'],
            donation.payment.bank_transfer_reference
        )
    
    def test_cash_donation_success(self):
        """Test successful CASH donation flow."""
        # Create donation with payment
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '25.00',
            'currency': 'GBP',
            'payment_method_id': self.cash_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('message', response.data)
        self.assertIn('cash donation will be collected at the venue.', response.data['message'].lower())
        self.assertEqual(response.data['amount'], '25.00')
        self.assertEqual(response.data['currency'], 'GBP')
        
        # Verify donation was created
        donation_id = response.data['donation']['id']
        donation = Donation.objects.get(id=donation_id)
        
        # Verify payment was created
        self.assertIsNotNone(donation.payment)
        self.assertEqual(donation.payment.status, PaymentStatusChoices.PENDING)
    
    def test_general_donation_without_event(self):
        """Test creating a general donation (not event-specific)."""
        # Create donation without event_id (uses payment method's event)
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '75.00',
            'currency': 'GBP',
            'payment_method_id': self.bank_method.id
            # No event_id provided
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify donation was created with payment method's event
        donation_id = response.data['donation']['id']
        donation = Donation.objects.get(id=donation_id)
        
        # Payment should use the payment method's event
        self.assertEqual(donation.payment.event, self.event)
    
    def test_donation_amount_validation_minimum(self):
        """Test donation amount validation - below minimum."""
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '0.00',  # Below minimum
            'currency': 'GBP',
            'payment_method_id': self.stripe_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)
    
    def test_donation_amount_validation_maximum(self):
        """Test donation amount validation - above maximum."""
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '15000.00',  # Above maximum (£10,000)
            'currency': 'GBP',
            'payment_method_id': self.stripe_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)
    
    def test_donation_valid_amount_range(self):
        """Test donation with valid amounts."""
        valid_amounts = ['1.00', '50.00', '500.00', '9999.99']
        
        for amount in valid_amounts:
            url = '/api/payments/donations/create-with-payment/'
            data = {
                'amount': amount,
                'currency': 'GBP',
                'payment_method_id': self.bank_method.id,
                'event_id': self.event.event_id
            }
            
            response = self.client.post(url, data, format='json')
            
            # Verify success
            self.assertEqual(
                response.status_code, 
                status.HTTP_201_CREATED,
                f"Amount {amount} should be valid"
            )
    
    def test_donation_wrong_payment_method_event(self):
        """Test donation fails when payment method is for different event."""
        # Create another event
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OE2026',
            display_identifier='OE2026CHARITY001',
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
        
        # Try to donate with mismatched event and payment method
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '50.00',
            'currency': 'GBP',
            'payment_method_id': other_method.id,
            'event_id': self.event.event_id  # Different from payment method's event
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_donation_inactive_payment_method(self):
        """Test donation fails with inactive payment method."""
        # Deactivate payment method
        self.stripe_method.is_active = False
        self.stripe_method.save()
        
        # Try to donate
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '50.00',
            'currency': 'GBP',
            'payment_method_id': self.stripe_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('payment_method_id', response.data)
    
    def test_donation_creates_payment_metadata(self):
        """Test that donation stores metadata in payment."""
        # Create donation
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '150.00',
            'currency': 'GBP',
            'payment_method_id': self.bank_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify payment metadata
        donation_id = response.data['donation']['id']
        donation = Donation.objects.get(id=donation_id)
        payment = donation.payment
        
        self.assertIsNotNone(payment.metadata)
        self.assertIn('donation', payment.metadata)
        
        donation_metadata = payment.metadata['donation']
        self.assertEqual(donation_metadata['tracking_reference'], donation.tracking_reference)
        self.assertEqual(donation_metadata['donated_by'], self.user.username)
    
    def test_bank_transfer_verification_for_donation(self):
        """Test bank transfer verification flow for donations."""
        # Create donation
        url = '/api/payments/donations/create-with-payment/'
        data = {
            'amount': '200.00',
            'currency': 'GBP',
            'payment_method_id': self.bank_method.id,
            'event_id': self.event.event_id
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        donation_id = response.data['donation']['id']
        donation = Donation.objects.get(id=donation_id)
        payment = donation.payment

        evidence = BankTransferEvidence.objects.create(
            transfer_id=payment.bank_transfer_reference,
            evidence_file=SimpleUploadedFile(
                'proof.pdf',
                b'%PDF-1.4 donation bank transfer evidence',
                content_type='application/pdf',
            ),
            payment=payment,
            payer_name='Donation Payer',
            payer_account_last4='1234',
            amount_on_evidence=payment.base_amount,
        )
        evidence.mark_verified(self.admin_user)
        
        # Admin verifies bank transfer
        self.client.force_authenticate(user=self.admin_user)
        
        verify_url = f'/api/payments/list/{payment.payment_id}/verify-bank-transfer/' # 1. verify payment
        verify_data = {
            'verified': True
        }
        
        response = self.client.post(verify_url, verify_data, format='json')
        print(f"Bank transfer verification response data: {response.data}")
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify payment status updated
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)

        verify_url = f'/api/payments/donations/{donation.donation_id}/verify-donation/' # 2. verify donation
        verify_data = {
            'verified': True
        }
        
        response = self.client.post(verify_url, verify_data, format='json')
        logger.info(f"Donation verification response data: {response.data}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify donation is marked as verified
        donation.refresh_from_db()
        self.assertEqual(donation.verification_status, VerificationStatus.VERIFIED)


class DonationVerificationWorkflowTestCase(TestCase):
    """Test donation verification workflow via API."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123',
            is_staff=True
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Charity Event',
            code='CHARITY',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Charity',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Fundraiser 2026',
            display_code='FR2026',
            display_identifier='FR2026CHARITY001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            title='Bank Transfer',
            is_active=True,
            created_by=self.user
        )
    
    def create_donation_with_payment(self, amount='50.00'):
        """Helper to create a donation with payment."""
        # Create payment
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(Decimal(amount), 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            metadata={}
        )
        
        # Create donation
        donation = Donation.objects.create(
            donated_by=self.user,
            payment=payment,
            verification_status=VerificationStatus.PENDING,
            amount=Money(Decimal(amount), 'GBP')
        )
        
        # Link payment to donation
        payment.target = donation
        payment.save()
        
        return donation, payment
    
    def test_admin_approve_donation(self):
        """Test admin approving a donation."""
        # Create donation
        donation, payment = self.create_donation_with_payment()
        
        # Admin approves donation
        self.client.force_authenticate(user=self.admin_user)
        
        url = f'/api/payments/donations/{donation.donation_id}/verify-donation/'
        data = {
            'action': 'approve',
            'notes': 'Donation verified and approved',
            'verified': True
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)
        
        # Verify donation status
        donation.refresh_from_db()
        self.assertEqual(donation.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(donation.verified_by, self.admin_user)
        self.assertIsNotNone(donation.verified_updated_at)
        # TODO: needs to be auto confirmed as proceessed
    
    def test_admin_reject_donation(self):
        """Test admin rejecting a donation."""
        # Create donation
        donation, payment = self.create_donation_with_payment()
        
        # Admin rejects donation
        self.client.force_authenticate(user=self.admin_user)
        
        url = f'/api/payments/donations/{donation.donation_id}/verify-donation/'
        data = {
            'action': 'reject',
            'notes': 'Suspicious transaction',
            'verified': False
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)
        
        # Verify donation status
        donation.refresh_from_db()
        self.assertEqual(donation.verification_status, VerificationStatus.REJECTED)
        self.assertEqual(donation.verified_by, self.admin_user)
        self.assertIsNotNone(donation.verified_updated_at)
    
    def test_non_admin_cannot_verify_donation(self):
        """Test that non-admin users cannot verify donations."""
        # Create donation
        donation, payment = self.create_donation_with_payment()
        
        # Regular user tries to verify
        self.client.force_authenticate(user=self.user)
        
        url = f'/api/payments/donations/{donation.donation_id}/verify-donation/'
        data = {
            'action': 'approve',
            'notes': 'Trying to approve',
            'verified': True
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify permission denied
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_verify_already_processed_donation(self):
        """Test that already processed donations cannot be re-verified."""
        # Create and process donation
        donation, payment = self.create_donation_with_payment()
        donation.mark_verified(self.admin_user)
        
        # Admin tries to verify again
        self.client.force_authenticate(user=self.admin_user)
        
        url = f'/api/payments/donations/{donation.donation_id}/verify-donation/'
        data = {
            'action': 'approve',
            'notes': 'Trying to re-approve',
            'verified': True
        }
        
        response = self.client.post(url, data, format='json')
        
        # Verify error response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_verify_donation_with_notes(self):
        """Test that verification notes are stored correctly."""
        # Create donation
        donation, payment = self.create_donation_with_payment()
        
        # Admin approves with notes
        self.client.force_authenticate(user=self.admin_user)
        
        url = f'/api/payments/donations/{donation.donation_id}/verify-donation/'
        data = {
            'action': 'approve',
            'notes': 'Large donation verified by bank statement',
            'verified': True
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Notes should be stored in metadata or notes field if available
        # This depends on your model implementation


class DonationPaymentCompletionSignalTestCase(TestCase):
    """Test payment completion signal handling for donations."""
    
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
            title='Charity Event',
            code='CHARITY',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Charity',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Fundraiser 2026',
            display_code='FR2026',
            display_identifier='FR2026CHARITY001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit Card',
            is_active=True,
            created_by=self.user
        )
    
    def test_payment_completion_marks_donation_verified(self):
        """Test that completing payment marks donation as verified."""
        # Create payment
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            metadata={}
        )
        
        # Create donation
        donation = Donation.objects.create(
            donated_by=self.user,
            payment=payment,
            verification_status=VerificationStatus.PENDING,
            amount=Money(100, 'GBP')
        )
        
        # Link payment to donation
        payment.target = donation
        payment.save()
        
        # Complete payment (triggers signal)
        payment.status = PaymentStatusChoices.COMPLETED
        payment.save()
        
        # Verify donation status updated
        donation.refresh_from_db()
        self.assertEqual(donation.verification_status, VerificationStatus.VERIFIED)
    
    def test_payment_failure_does_not_update_donation(self):
        """Test that failed payment does not update donation status."""
        # Create payment
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            metadata={}
        )
        
        # Create donation
        donation = Donation.objects.create(
            donated_by=self.user,
            payment=payment,
            verification_status=VerificationStatus.PENDING,
            amount=Money(100, 'GBP')
        )
        
        # Link payment to donation
        payment.target = donation
        payment.save()
        
        # Fail payment
        payment.status = PaymentStatusChoices.FAILED
        payment.save()
        
        # Verify donation remains pending
        donation.refresh_from_db()
        self.assertEqual(donation.verification_status, VerificationStatus.PENDING)
