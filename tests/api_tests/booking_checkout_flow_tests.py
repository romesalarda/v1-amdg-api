"""
Booking Checkout Flow API Tests

Tests the complete checkout flow via API endpoints with all payment methods:
- STRIPE: Tests client_secret return and payment intent creation
- BANK_TRANSFER: Tests bank reference generation and manual verification
- CASH: Tests immediate ticket creation
- FREE: Tests free event checkout
- Edge cases: Stock issues, expired intents, validation errors
"""
import json

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from types import SimpleNamespace
from djmoney.money import Money

from apps.bookings.models import (
    Booking, BookingIntent, BookingPackage,
    TicketType, Ticket, TicketScopeChoices
)
from apps.payments.models import (
    Payment, PaymentMethod, PaymentMethodTypeChoices,
    PaymentStatusChoices, Discount, DiscountType, DiscountRule, DiscountRuleTypeChoices,
    BankTransferEvidence
)
from apps.events.models import (
    Event, EventType, EventStatusChoices, EventAuthorization, EventAuthorizationStatusChoices,
    EventQuestion, EventQuestionOption, EventQuestionTypeChoices, EventQuestionAnswer
)
from apps.attendee.models import (
    Attendee, AttendeeRelationship, AttendeeStatus,
    Consent, AttendeeConsent,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    AccessibilityRequirement, AttendeeAccessibilityRequirement
)
from apps.attendee.models.personal.emergency import EmergencyContact
from apps.organisations.models import Organisation
from apps.products.models import Product, ProductVariant, ProductSizeChoices
from apps.bookings.models import PackageProduct
from apps.common.models import Resource
from apps.common.models.availability import AvailabilityWindow, AvailabilityTypeChoices
from apps.locations.models import (
    CountryLocation, ClusterLocation, ChapterLocation, AreaLocation,
    GeneralSectorType, SpecificSectorType,
)
from apps.products.models import Order

import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class CheckoutAPITestCase(TestCase):
    """Test checkout API endpoint with various payment methods."""
    
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

        AvailabilityWindow.objects.create(
            name='Registration Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=ContentType.objects.get_for_model(Event),
            target_id=self.event.id,
            available_from=timezone.now() - timedelta(days=1),
            available_to=timezone.now() + timedelta(days=60),
        )

        self.country = CountryLocation.objects.create(
            country='GB',
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE,
            active=True,
        )
        self.cluster = ClusterLocation.objects.create(
            cluster_name='London Cluster',
            country=self.country,
            active=True,
        )
        self.chapter = ChapterLocation.objects.create(
            chapter_name='London Chapter',
            cluster=self.cluster,
            active=True,
        )
        self.area = AreaLocation.objects.create(
            area_name='Central Area',
            chapter=self.chapter,
            active=True,
        )

        EventAuthorization.objects.create(
            event=self.event,
            status=EventAuthorizationStatusChoices.APPROVED,
            reviewed_by=self.admin_user
        )
            
        
        # Create ticket type
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='STANDARD',
            title='Standard Ticket',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.user
        )
        
        # Create booking package
        self.package = BookingPackage.objects.create(
            name='Standard Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(50, 'GBP'),
            created_by=self.user
        )
        
        # Create payment methods
        self.stripe_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
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
    
    def create_booking_intent(self, ticket_count=1):
        """Helper to create a booking intent."""
        return BookingIntent.objects.create(
            event=self.event,
            intended_ticket_count=ticket_count,
            made_by=self.user
        )
    
    def create_attendee(self, booking):
        """Helper to create an attendee."""
        return Attendee.objects.create(
            first_name='Test',
            last_name='Attendee',
            email='attendee@example.com',
            date_of_birth=date(1990, 1, 1),
            event=self.event,
            user=self.user,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            area_from=self.area,
            defined_by=self.user
        )

    def test_checkout_preview_validates_required_fields(self):
        """Test that checkout preview validates required fields."""
        response = self.client.post('/api/bookings/list/checkout-preview/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('booking_intent_id', response.data)
        self.assertIn('attendees', response.data)

    def test_checkout_preview_returns_discount_breakdown(self):
        """Test checkout preview returns package discount line items and total."""
        intent = self.create_booking_intent(ticket_count=1)
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-PREVIEW-001',
            made_by=self.user,
        )
        attendee = self.create_attendee(booking)

        discount = Discount.objects.create(
            name='Adult 10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id,
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Age over 18',
            discount=discount,
            value='18',
            active=True,
        )

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'attendees': [
                    {
                        'attendee_id': str(attendee.attendee_id),
                        'package_id': self.package.id,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_amount'], '45.00')
        self.assertEqual(response.data['currency'], 'GBP')
        self.assertTrue(response.data['soft_stock_reservation'])
        self.assertEqual(len(response.data['attendees']), 1)

        package_breakdown = response.data['attendees'][0]['package']
        self.assertEqual(package_breakdown['base_amount'], '50.00')
        self.assertEqual(package_breakdown['discount_total'], '5.00')
        self.assertEqual(package_breakdown['final_amount'], '45.00')
        self.assertEqual(len(package_breakdown['applied_discounts']), 1)
        self.assertEqual(package_breakdown['applied_discounts'][0]['name'], 'Adult 10% Off')

        self.assertEqual(Order.objects.count(), 0)

    def create_required_questions(self):
        """Helper to create required questions for draft checkout."""
        short_question = EventQuestion.objects.create(
            event=self.event,
            question_title='Diet preference',
            question_body='Provide dietary notes',
            question_type=EventQuestionTypeChoices.SHORT_ANSWER,
            required=True,
            public=True,
            order=1
        )

        upload_question = EventQuestion.objects.create(
            event=self.event,
            question_title='Upload ID',
            question_body='Upload a copy of your ID',
            question_type=EventQuestionTypeChoices.UPLOAD,
            required=True,
            public=True,
            order=2
        )

        return short_question, upload_question

    def create_upload_resource(self):
        """Helper to create a resource upload for question answers."""
        content_type = ContentType.objects.get_for_model(Event)
        upload = SimpleUploadedFile('id.txt', b'identity file', content_type='text/plain')

        return Resource.objects.create(
            name='ID Upload',
            description='ID document',
            resource_type='DOCUMENT',
            file=upload,
            public=False,
            tag='QUESTION_UPLOAD',
            target_type=content_type,
            target_id=self.event.id,
            added_by=self.user
        )
    
    def test_checkout_requires_authentication(self):
        """Test that checkout requires authentication."""
        self.client.force_authenticate(user=None)
        
        response = self.client.post('/api/bookings/list/checkout/', {})
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_checkout_validates_required_fields(self):
        """Test that checkout validates required fields."""
        response = self.client.post('/api/bookings/list/checkout/', {})
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('booking_intent_id', response.data)
        self.assertIn('payment_method_id', response.data)
        self.assertIn('attendees', response.data)
    
    def test_checkout_validates_intent_exists(self):
        """Test that checkout validates intent exists."""
        import uuid
        fake_intent_id = uuid.uuid4()
        
        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(fake_intent_id),
            'payment_method_id': self.stripe_method.id,
            'attendees': []
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('booking_intent_id', response.data)
    
    def test_checkout_validates_intent_is_active(self):
        """Test that checkout validates intent is active and not expired."""
        # Create expired intent
        intent = self.create_booking_intent()
        intent.expires_at = timezone.now() - timedelta(minutes=1)
        intent.save()
        
        # Create attendee for dummy booking (needed for validation)
        dummy_booking = Booking.objects.create(
            event=self.event,
            booking_reference='DUMMY',
            made_by=self.user
        )
        attendee = self.create_attendee(dummy_booking)
        
        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.stripe_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id
                }
            ]
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('booking_intent_id', response.data)
    
    def test_checkout_cash_creates_tickets_immediately(self):
        """Test that CASH payment creates tickets immediately."""
        intent = self.create_booking_intent(ticket_count=1)
        
        # Create booking and attendee first
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-CASH-001',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)
        
        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id
                }
            ]
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'confirmed')
        self.assertIn('tickets', response.data)
        self.assertIsNotNone(response.data['tickets'])
        self.assertGreater(len(response.data['tickets']), 0)
        
        # Verify payment was created and completed
        payment = Payment.objects.get(payment_reference=response.data['payment_reference'])
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        
        # Verify tickets were created
        tickets = Ticket.objects.filter(payment=payment)
        self.assertEqual(tickets.count(), 1)
    
    def test_checkout_bank_transfer_returns_reference(self):
        """Test that BANK_TRANSFER returns bank reference for manual payment."""
        intent = self.create_booking_intent(ticket_count=1)
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-BANK-001',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)
        
        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id
                }
            ]
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'pending_verification')
        self.assertIn('bank_transfer_reference', response.data)
        self.assertIsNotNone(response.data['bank_transfer_reference'])
        self.assertIn('bank_transfer_instructions', response.data)
        
        # Verify payment is pending
        payment = Payment.objects.get(payment_reference=response.data['payment_reference'])
        self.assertEqual(payment.status, PaymentStatusChoices.PENDING)
        
        # Verify NO tickets were created yet
        tickets = Ticket.objects.filter(payment=payment)
        self.assertEqual(tickets.count(), 0)

    def test_reserve_bank_transfer_reuses_existing_checkout_payment(self):
        """Reserve endpoint must return existing checkout payment instead of creating a new draft reservation."""
        intent = self.create_booking_intent(ticket_count=1)

        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-BANK-REUSE-001',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)

        checkout_response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id
                }
            ]
        }, format='json')

        self.assertEqual(checkout_response.status_code, status.HTTP_201_CREATED)

        checkout_payment = Payment.objects.get(payment_reference=checkout_response.data['payment_reference'])
        self.assertEqual(checkout_payment.metadata.get('payment_type'), 'booking_checkout_pending_finalization')

        reserve_response = self.client.post('/api/bookings/list/reserve-bank-transfer-payment/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
        }, format='json')

        self.assertEqual(reserve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(checkout_payment.payment_id), reserve_response.data['payment_id'])

        reservation_count = Payment.objects.filter(
            user=self.user,
            event=self.event,
            method=self.bank_method,
            metadata__checkout_intent_id=str(intent.booking_intent_id),
            metadata__payment_type='booking_checkout_reservation',
        ).count()
        self.assertEqual(reservation_count, 0)

    def test_reserve_then_checkout_then_reserve_does_not_create_extra_draft(self):
        """After a reserved payment is consumed by checkout, reserve endpoint must not create a new draft payment."""
        intent = self.create_booking_intent(ticket_count=1)

        reserve_one = self.client.post('/api/bookings/list/reserve-bank-transfer-payment/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
        }, format='json')

        self.assertEqual(reserve_one.status_code, status.HTTP_201_CREATED)
        reserved_payment_id = reserve_one.data['payment_id']

        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-BANK-REUSE-002',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)

        checkout_response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
            'payment_id': reserved_payment_id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id
                }
            ]
        }, format='json')

        self.assertEqual(checkout_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(checkout_response.data['payment_id']), reserved_payment_id)

        consumed_payment = Payment.objects.get(payment_id=reserved_payment_id)
        self.assertEqual(consumed_payment.status, PaymentStatusChoices.PENDING)
        self.assertEqual(consumed_payment.metadata.get('payment_type'), 'booking_checkout_pending_finalization')

        reserve_two = self.client.post('/api/bookings/list/reserve-bank-transfer-payment/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
        }, format='json')

        self.assertEqual(reserve_two.status_code, status.HTTP_200_OK)
        self.assertEqual(reserve_two.data['payment_id'], reserved_payment_id)

        total_payments_for_intent = Payment.objects.filter(
            user=self.user,
            event=self.event,
            method=self.bank_method,
            metadata__checkout_intent_id=str(intent.booking_intent_id),
        ).count()
        self.assertEqual(total_payments_for_intent, 1)

    def test_checkout_bank_transfer_requires_evidence_when_method_is_immediate(self):
        """Checkout must fail when immediate-evidence bank transfer method is used without evidence payload."""
        self.bank_method.bank_transfer_required_immediately = True
        self.bank_method.save(update_fields=['bank_transfer_required_immediately'])

        intent = self.create_booking_intent(ticket_count=1)

        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-BANK-IMM-001',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)

        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id
                }
            ]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('bank_transfer_evidence', response.data)

    def test_checkout_bank_transfer_creates_booking_and_attendee_from_draft(self):
        """Bank transfer checkout must create booking and attendee immediately for draft selections."""
        intent = self.create_booking_intent(ticket_count=1)

        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Draft',
                        'last_name': 'Bank',
                        'date_of_birth': '1990-01-01',
                        'relationship_to_user': 'self',
                        'area_from': self.area.id,
                    }
                }
            ]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'pending_verification')
        self.assertIsNotNone(response.data.get('booking_id'))

        payment = Payment.objects.get(payment_reference=response.data['payment_reference'])
        self.assertIsNotNone(payment.target)
        self.assertIsInstance(payment.target, Booking)

        booking = payment.target
        attendees = Attendee.objects.filter(booking=booking)
        self.assertEqual(attendees.count(), 1)
        self.assertEqual(attendees.first().status, AttendeeStatus.PENDING_PAYMENT)

    @patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.create')
    def test_checkout_stripe_pending_creates_booking_and_attendee_from_draft(self, mock_create_intent):
        """Stripe checkout (client_secret flow) must create booking and attendee before payment confirmation."""
        intent = self.create_booking_intent(ticket_count=1)
        mock_create_intent.return_value = SimpleNamespace(
            id='pi_pending_123',
            client_secret='pi_pending_secret_123'
        )

        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.stripe_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Draft',
                        'last_name': 'Stripe',
                        'date_of_birth': '1992-01-01',
                        'relationship_to_user': 'self',
                        'area_from': self.area.id,
                    }
                }
            ]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'pending_payment')
        self.assertIsNotNone(response.data.get('booking_id'))
        self.assertIsNotNone(response.data.get('stripe_client_secret'))

        payment = Payment.objects.get(payment_reference=response.data['payment_reference'])
        self.assertEqual(payment.stripe_payment_intent, 'pi_pending_123')
        self.assertIsNotNone(payment.target)
        self.assertIsInstance(payment.target, Booking)

        booking = payment.target
        attendees = Attendee.objects.filter(booking=booking)
        self.assertEqual(attendees.count(), 1)
        self.assertEqual(attendees.first().status, AttendeeStatus.PENDING_PAYMENT)
    
    def test_verify_bank_transfer_creates_tickets(self):
        """Test that verifying bank transfer creates tickets."""
        # First, complete checkout with bank transfer
        intent = self.create_booking_intent(ticket_count=1)
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-VERIFY-001',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)
        
        checkout_response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.bank_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id
                }
            ]
        }, format='json')
        
        self.assertEqual(checkout_response.status_code, status.HTTP_201_CREATED)
        
        payment_reference = checkout_response.data['payment_reference']
        payment = Payment.objects.get(payment_reference=payment_reference)

        evidence = BankTransferEvidence.objects.create(
            transfer_id='BT-BOOKING-VERIFY-001',
            evidence_file=SimpleUploadedFile(
                'proof.pdf',
                b'%PDF-1.4 booking bank transfer evidence',
                content_type='application/pdf',
            ),
            payment=payment,
            payer_name='Booking Payer',
            payer_account_last4='1234',
            amount_on_evidence=payment.base_amount,
        )
        evidence.mark_verified(self.admin_user)
        
        # Now verify as admin
        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin_user)
        
        verify_response = admin_client.post(
            f'/api/payments/list/{payment.payment_id}/verify-bank-transfer/',
            {
                'verified': True,
                'notes': 'Received payment via bank reference'
            },
            format='json'
        )
        
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        self.assertEqual(verify_response.data['tickets_created'], 1)
        
        # Verify payment is now completed
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        
        # Verify tickets were created
        tickets = Ticket.objects.filter(payment=payment)
        self.assertEqual(tickets.count(), 1)
    
    def test_checkout_with_package_products(self):
        """Test checkout with products included in package."""
        # Create product and variant
        product = Product.objects.create(
            title='Conference T-Shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        variant = ProductVariant.objects.create(
            product=product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=10,
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        # Link product to package
        package_product = PackageProduct.objects.create(
            booking_package=self.package,
            product=product,
            quantity_per_attendee=1,
            percentage_modifier=Decimal('-10.00'),  # 10% discount
            added_by=self.user
        )
        
        intent = self.create_booking_intent(ticket_count=1)
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-PROD-001',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)
        
        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id,
                    'product_selections': [
                        {
                            'package_product_id': package_product.id,
                            'variant_id': str(variant.variant_id),
                            'quantity': 1
                        }
                    ]
                }
            ]
        }, format='json')

        logger.debug(response.data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertGreater(len(response.data['orders']), 0)
        
        # Verify order was created
        order_id = response.data['orders'][0]['order_id']
        from apps.products.models import Order
        order = Order.objects.get(order_id=order_id)
        self.assertEqual(order.order_items.count(), 1)
        order_item = order.order_items.first()
        self.assertIsNotNone(order_item)
        self.assertEqual(order_item.package_product_id, package_product.id)
        self.assertEqual(order_item.unit_price, Money('18.00', 'GBP'))
        self.assertEqual(order_item.total_price, Money('18.00', 'GBP'))
        
        # Verify stock was decremented
        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 9)

    def test_checkout_with_draft_attendee_full_payload(self):
        """Test atomic checkout with full draft attendee payload."""
        intent = self.create_booking_intent(ticket_count=1)

        consent = Consent.objects.create(
            event=self.event,
            code='CONSENT-1',
            title='Photo consent',
            description='Allow photos during event',
            required=True,
            defined_by=self.user
        )

        dietary = DietaryRequirement.objects.create(
            code='DIET-1',
            label='Vegan',
            description='Plant-based diet',
            added_by=self.user
        )

        medical = MedicalCondition.objects.create(
            code='MED-1',
            label='Asthma',
            description='Asthma condition',
            added_by=self.user
        )

        accessibility = AccessibilityRequirement.objects.create(
            code='ACC-1',
            label='Wheelchair access',
            description='Wheelchair access required',
            added_by=self.user
        )

        short_question, upload_question = self.create_required_questions()
        upload_resource = self.create_upload_resource()

        product = Product.objects.create(
            title='Conference T-Shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )

        variant = ProductVariant.objects.create(
            product=product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=10,
            added_by=self.user,
            verified=True,
            is_active=True
        )

        package_product = PackageProduct.objects.create(
            booking_package=self.package,
            product=product,
            quantity_per_attendee=1,
            added_by=self.user
        )

        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'product_selections': [
                        {
                            'package_product_id': package_product.id,
                            'variant_id': str(variant.variant_id),
                            'quantity': 1
                        }
                    ],
                    'attendee': {
                        'first_name': 'Draft',
                        'last_name': 'Attendee',
                        'email': 'draft@example.com',
                        'phone_number': '+447700900123',
                        'date_of_birth': '1990-01-01',
                        'gender': 'MALE',
                        'relationship_to_user': 'self',
                        'consents': [
                            {
                                'consent_id': consent.id,
                                'consent_given': True
                            }
                        ],
                        'personal_info': {
                            'dietary_requirements': [
                                {'id': dietary.id, 'details': 'No dairy'}
                            ],
                            'medical_conditions': [
                                {'id': medical.id, 'severity': 'mild'}
                            ],
                            'accessibility_requirements': [
                                {'id': accessibility.id}
                            ],
                            'emergency_contact': {
                                'first_name': 'Jane',
                                'last_name': 'Doe',
                                'relationship': 'parent',
                                'phone_number': '+447700900999'
                            }
                        },
                        'question_answers': [
                            {
                                'question_id': str(short_question.id),
                                'answer_text': 'Vegetarian'
                            },
                            {
                                'question_id': str(upload_question.id),
                                'upload_resource_id': upload_resource.id
                            }
                        ]
                    }
                }
            ]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'confirmed')

        attendee = Attendee.objects.get(email='draft@example.com')
        self.assertEqual(attendee.booking.booking_reference, response.data['booking_reference'])

        self.assertTrue(AttendeeConsent.objects.filter(attendee=attendee, consent=consent).exists())
        self.assertTrue(AttendeeDietaryRequirement.objects.filter(attendee=attendee, dietary_requirement=dietary).exists())
        self.assertTrue(AttendeeMedicalCondition.objects.filter(attendee=attendee, medical_condition=medical).exists())
        self.assertTrue(AttendeeAccessibilityRequirement.objects.filter(attendee=attendee, accessibility_requirement=accessibility).exists())
        self.assertTrue(EmergencyContact.objects.filter(attendee=attendee).exists())

        answers = EventQuestionAnswer.objects.filter(attendee=attendee)
        self.assertEqual(answers.count(), 2)
        upload_answer = answers.get(question=upload_question)
        self.assertEqual(upload_answer.answer_text, upload_resource.resource_url)

    def test_checkout_draft_attendee_missing_required_consent(self):
        """Draft checkout should fail when required consents are missing."""
        intent = self.create_booking_intent(ticket_count=1)

        Consent.objects.create(
            event=self.event,
            code='CONSENT-REQ',
            title='Required consent',
            description='Required consent',
            required=True,
            defined_by=self.user
        )

        short_question, upload_question = self.create_required_questions()
        upload_resource = self.create_upload_resource()

        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Draft',
                        'last_name': 'Attendee',
                        'date_of_birth': '1990-01-01',
                        'gender': 'MALE',
                        'relationship_to_user': 'self',
                        'question_answers': [
                            {
                                'question_id': str(short_question.id),
                                'answer_text': 'Yes'
                            },
                            {
                                'question_id': str(upload_question.id),
                                'upload_resource_id': upload_resource.id
                            }
                        ]
                    }
                }
            ]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Attendee.objects.count(), 0)

    def test_checkout_draft_attendee_missing_required_question(self):
        """Draft checkout should fail when required questions are missing."""
        intent = self.create_booking_intent(ticket_count=1)

        Consent.objects.create(
            event=self.event,
            code='CONSENT-REQ-2',
            title='Required consent',
            description='Required consent',
            required=True,
            defined_by=self.user
        )

        self.create_required_questions()

        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Draft',
                        'last_name': 'Attendee',
                        'date_of_birth': '1990-01-01',
                        'gender': 'MALE',
                        'relationship_to_user': 'self',
                        'consents': [
                            {
                                'consent_id': Consent.objects.first().id,
                                'consent_given': True
                            }
                        ]
                    }
                }
            ]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Attendee.objects.count(), 0)

    def test_checkout_expires_intent(self):
        """Checkout should return the existing session when Idempotency-Key matches."""
        intent = self.create_booking_intent(ticket_count=1)

        payload = {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Draft',
                        'last_name': 'Attendee',
                        'date_of_birth': '1990-01-01',
                        'gender': 'MALE',
                        'relationship_to_user': 'self',
                    }
                }
            ]
        }

        response_one = self.client.post(
            '/api/bookings/list/checkout/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='checkout-key-1'
        )
        self.assertEqual(response_one.status_code, status.HTTP_201_CREATED)

        response_two = self.client.post(
            '/api/bookings/list/checkout/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='checkout-key-1'
        )
        self.assertEqual(response_two.status_code, status.HTTP_200_OK)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_checkout_idempotency_handles_existing_payment_without_method(self):
        """Idempotent retries should safely return existing sessions even when stored payment method is null."""
        intent = self.create_booking_intent(ticket_count=1)
        intent.last_checkout_idempotency_key = 'checkout-null-method-key'
        intent.save(update_fields=['last_checkout_idempotency_key'])

        Payment.objects.create(
            user=self.user,
            event=self.event,
            method=None,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            metadata={
                'checkout_intent_id': str(intent.booking_intent_id),
                'checkout_idempotency_key': 'checkout-null-method-key',
                'checkout_attendees': [
                    {
                        'attendee_id': None,
                        'attendee_draft': {
                            'first_name': 'Null',
                            'last_name': 'Method',
                            'date_of_birth': '1990-01-01',
                            'relationship_to_user': 'self',
                        },
                        'package_id': self.package.id,
                        'product_selections': [],
                    }
                ],
                'payment_type': 'booking_checkout_pending_finalization',
            },
        )

        payload = {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Retry',
                        'last_name': 'User',
                        'date_of_birth': '1990-01-01',
                        'relationship_to_user': 'self',
                    },
                }
            ],
        }

        response = self.client.post(
            '/api/bookings/list/checkout/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='checkout-null-method-key',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'pending_payment')
        self.assertIn('payment_reference', response.data)

    def test_checkout_preview_accepts_pending_multipart_upload_marker(self):
        """Preview should accept upload_file_key placeholders for pending multipart question uploads."""
        intent = self.create_booking_intent(ticket_count=1)
        short_question, upload_question = self.create_required_questions()

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'attendees': [
                    {
                        'package_id': self.package.id,
                        'attendee': {
                            'first_name': 'Preview',
                            'last_name': 'Upload',
                            'date_of_birth': '1990-01-01',
                            'relationship_to_user': 'self',
                            'area_from': self.area.id,
                            'question_answers': [
                                {
                                    'question_id': str(short_question.id),
                                    'answer_text': 'Yes',
                                },
                                {
                                    'question_id': str(upload_question.id),
                                    'upload_file_key': '__multipart_pending__',
                                },
                            ],
                        },
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['currency'], 'GBP')

    def test_checkout_multipart_creates_question_upload_resource(self):
        """Multipart checkout should create a resource and persist its URL into the attendee answer."""
        intent = self.create_booking_intent(ticket_count=1)
        short_question, upload_question = self.create_required_questions()
        upload = SimpleUploadedFile('passport.pdf', b'%PDF-1.4 test passport', content_type='application/pdf')

        attendees_payload = [
            {
                'package_id': self.package.id,
                'attendee': {
                    'first_name': 'Multipart',
                    'last_name': 'Tester',
                    'date_of_birth': '1990-01-01',
                    'relationship_to_user': 'self',
                    'area_from': self.area.id,
                    'question_answers': [
                        {
                            'question_id': str(short_question.id),
                            'answer_text': 'Uploaded document attached',
                        },
                        {
                            'question_id': str(upload_question.id),
                            'upload_file_key': f'question_uploads[0][{upload_question.id}]',
                        },
                    ],
                },
            }
        ]

        response = self.client.post(
            '/api/bookings/list/checkout/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'payment_method_id': self.cash_method.id,
                'attendees': json.dumps(attendees_payload),
                f'question_uploads[0][{upload_question.id}]': upload,
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        attendee = Attendee.objects.get(first_name='Multipart', last_name='Tester')
        upload_answer = EventQuestionAnswer.objects.get(attendee=attendee, question=upload_question)
        resource = Resource.objects.get(id=Payment.objects.get(payment_reference=response.data['payment_reference']).metadata['checkout_attendees'][0]['attendee_draft']['question_answers'][1]['upload_resource_id'])

        self.assertEqual(resource.tag, 'QUESTION_UPLOAD')
        self.assertEqual(resource.added_by, self.user)
        self.assertEqual(str(resource.target_id), str(self.event.id))
        self.assertEqual(upload_answer.answer_text, resource.resource_url)

    @patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.retrieve')
    @patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.create')
    def test_checkout_idempotent_stripe_retry_returns_client_secret(self, mock_create_intent, mock_retrieve_intent):
        """Idempotent Stripe retries should return client_secret so frontend can continue confirmation."""
        intent = self.create_booking_intent(ticket_count=1)
        mock_create_intent.return_value = SimpleNamespace(
            id='pi_retry_123',
            client_secret='pi_retry_secret_123',
        )
        mock_retrieve_intent.return_value = SimpleNamespace(
            id='pi_retry_123',
            client_secret='pi_retry_secret_123',
        )

        payload = {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.stripe_method.id,
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Retry',
                        'last_name': 'Stripe',
                        'date_of_birth': '1990-01-01',
                        'relationship_to_user': 'self',
                        'area_from': self.area.id,
                    },
                }
            ],
        }

        first_response = self.client.post(
            '/api/bookings/list/checkout/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='stripe-retry-key',
        )
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_response.data['stripe_client_secret'], 'pi_retry_secret_123')

        second_response = self.client.post(
            '/api/bookings/list/checkout/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='stripe-retry-key',
        )
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.data['stripe_client_secret'], 'pi_retry_secret_123')
        self.assertEqual(Payment.objects.count(), 1)

    @patch('apps.payments.services.stripe.payment_intents.PaymentIntentService.retrieve')
    def test_checkout_stripe_confirmed_payment(self, mock_retrieve_intent):
        """Checkout should confirm Stripe payments when intent is succeeded."""
        intent = self.create_booking_intent(ticket_count=1)

        mock_retrieve_intent.return_value = SimpleNamespace(
            amount=5000,
            currency='gbp',
            status='succeeded',
            id='pi_confirmed'
        )

        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.stripe_method.id,
            'stripe_payment_intent_id': 'pi_confirmed',
            'attendees': [
                {
                    'package_id': self.package.id,
                    'attendee': {
                        'first_name': 'Draft',
                        'last_name': 'Attendee',
                        'date_of_birth': '1990-01-01',
                        'gender': 'MALE',
                        'relationship_to_user': 'self',
                    }
                }
            ]
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'confirmed')
        self.assertIn('tickets', response.data)

        payment = Payment.objects.get(payment_reference=response.data['payment_reference'])
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)

    def test_question_upload_endpoint_creates_resource(self):
        """Upload endpoint should create a resource for question answers."""
        upload = SimpleUploadedFile('answer.txt', b'answer file', content_type='text/plain')

        response = self.client.post(
            '/api/event/question-answers/upload/',
            {
                'event_id': str(self.event.event_id),
                'resource_type': 'DOCUMENT',
                'file': upload
            },
            format='multipart'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        resource = Resource.objects.get(id=response.data['id'])
        self.assertEqual(resource.tag, 'QUESTION_UPLOAD')
        self.assertEqual(str(resource.target_id), str(self.event.id))
    
    def test_checkout_validates_quantity_limits(self):
        """Test that checkout enforces package product quantity limits."""
        product = Product.objects.create(
            title='Conference T-Shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        variant = ProductVariant.objects.create(
            product=product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=10,
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        package_product = PackageProduct.objects.create(
            booking_package=self.package,
            product=product,
            quantity_per_attendee=1,  # Limit to 1
            added_by=self.user
        )
        
        intent = self.create_booking_intent(ticket_count=1)
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-LIMIT-001',
            made_by=self.user
        )
        attendee = self.create_attendee(booking)
        
        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.cash_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id,
                    'product_selections': [
                        {
                            'package_product_id': package_product.id,
                            'variant_id': str(variant.variant_id),
                            'quantity': 2  # Exceeds limit!
                        }
                    ]
                }
            ]
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('attendees', response.data or {})
        logger.debug(response.data)


class CheckoutEdgeCasesTest(TestCase):
    """Test edge cases and error handling in checkout."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='edgeuser',
            email='edge@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
        # Create minimal event setup
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
            title='Edge Case Event',
            display_code='EDGE2026',
            display_identifier='EDGE2026CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )

        AvailabilityWindow.objects.create(
            name='Registration Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=ContentType.objects.get_for_model(Event),
            target_id=self.event.id,
            available_from=timezone.now() - timedelta(days=1),
            available_to=timezone.now() + timedelta(days=60),
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='STANDARD',
            title='Standard',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.user
        )
        
        self.package = BookingPackage.objects.create(
            name='Standard Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(50, 'GBP'),
            created_by=self.user
        )
        
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.CASH,
            title='Cash',
            is_active=True,
            created_by=self.user
        )
    
    def test_checkout_with_insufficient_stock(self):
        """Test checkout fails gracefully when product stock is insufficient."""
        product = Product.objects.create(
            title='Limited Item',
            event=self.event,
            base_amount=Money(10, 'GBP'),
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        variant = ProductVariant.objects.create(
            product=product,
            size=ProductSizeChoices.ONE_SIZE,
            color='#000000',
            stock_quantity=0,  # No stock!
            added_by=self.user,
            verified=True,
            is_active=True
        )
        
        package_product = PackageProduct.objects.create(
            booking_package=self.package,
            product=product,
            quantity_per_attendee=1,
            added_by=self.user
        )
        
        intent = BookingIntent.objects.create(
            event=self.event,
            intended_ticket_count=1,
            made_by=self.user
        )
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-NOSTOCK-001',
            made_by=self.user
        )
        
        attendee = Attendee.objects.create(
            first_name='Test',
            last_name='User',
            email='test@example.com',
            date_of_birth=date(1990, 1, 1),
            event=self.event,
            user=self.user,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user
        )
        
        response = self.client.post('/api/bookings/list/checkout/', {
            'booking_intent_id': str(intent.booking_intent_id),
            'payment_method_id': self.payment_method.id,
            'attendees': [
                {
                    'attendee_id': str(attendee.attendee_id),
                    'package_id': self.package.id,
                    'product_selections': [
                        {
                            'package_product_id': package_product.id,
                            'variant_id': str(variant.variant_id),
                            'quantity': 1
                        }
                    ]
                }
            ]
        }, format='json')
        
        # Should fail with validation error
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Verify no booking or payment was created (transaction rolled back)
        self.assertFalse(
            Booking.objects.filter(booking_reference__startswith='BKG-').exclude(
                id=booking.id
            ).exists()
        )
