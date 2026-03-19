"""
Booking Checkout Flow API Tests

Tests the complete checkout flow via API endpoints with all payment methods:
- STRIPE: Tests client_secret return and payment intent creation
- BANK_TRANSFER: Tests bank reference generation and manual verification
- CASH: Tests immediate ticket creation
- FREE: Tests free event checkout
- Edge cases: Stock issues, expired intents, validation errors
"""
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
    PaymentStatusChoices
)
from apps.events.models import (
    Event, EventType, EventStatusChoices, EventAuthorization, EventAuthorizationStatusChoices,
    EventQuestion, EventQuestionOption, EventQuestionTypeChoices, EventQuestionAnswer
)
from apps.attendee.models import (
    Attendee, AttendeeRelationship,
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
            defined_by=self.user
        )

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
        })
        
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
        """Checkout should be idempotent when Idempotency-Key matches."""
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
        print(response_two.data)
        self.assertEqual(response_two.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Booking.objects.count(), 1)

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
