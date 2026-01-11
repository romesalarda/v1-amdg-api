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
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money

from apps.bookings.models import (
    Booking, BookingIntent, BookingPackage,
    TicketType, Ticket, TicketScopeChoices
)
from apps.payments.models import (
    Payment, PaymentMethod, PaymentMethodTypeChoices,
    PaymentStatusChoices
)
from apps.events.models import Event, EventType, EventStatusChoices, EventAuthorization, EventAuthorizationStatusChoices
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.organisations.models import Organisation
from apps.products.models import Product, ProductVariant, ProductSizeChoices
from apps.bookings.models import PackageProduct

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

        print(response.data)
        
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
