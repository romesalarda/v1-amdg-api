"""
Attendee Refund Flow Integration Tests.

Tests the complete refund process for booking-related payments:
1. Partial refund for a specific attendee (removing one family member)
2. Full removal of an attendee with various refund policies
3. Refund verification workflow with payment history tracking
4. Validation of refund associations with tickets and products

Scenario 1:
A family has registered for an event. Dad can't make it anymore.
They want to refund ONLY dad's items:
- His single day ticket (£12)
- His conference t-shirt from the booking package (£15)
The refund should not affect other family members' bookings.

Scenario 2:
Remove an attendee from the event with different refund scenarios:
- Full refund (100% return of all payments)
- Partial refund (e.g., 50% return based on cancellation policy)
- No refund (attendee removed but no money returned)
Must check payment history to find all active/completed payments for that attendee.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money
from unittest.mock import patch, MagicMock
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.bookings.models import (
    Booking, BookingPackage, TicketType, Ticket, 
    TicketScopeChoices, TicketStatusChoices, PackageProduct
)
from apps.payments.models import (
    Payment, PaymentMethod, PaymentMethodTypeChoices,
    PaymentStatusChoices, Discount, DiscountType,
    DiscountRule, DiscountRuleTypeChoices,
    RefundRequest, RefundAssociation, PaymentHistoryAction
)
from apps.products.models import (
    Product, ProductVariant, ProductSizeChoices,
    Order, OrderStatusChoices, OrderItem
)
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import (
    Attendee, AttendeeRelationship, FamilyGroup, 
    FamilyAttendee, HumanRelationshipChoices
)
from apps.attendee.api.viewsets import AttendeeViewSet
from apps.organisations.models import Organisation

User = get_user_model()


class AttendeePartialRefundTest(TestCase):
    """
    Test partial refund for a specific attendee (dad) from a family booking.
    
    Scenario:
    - Family of 4 registers: Mum, Dad, Son, Daughter
    - Each has a ticket and merchandise
    - Dad can't attend, family requests refund for ONLY dad's items
    - Verify refund associations, payment history, and other attendees unaffected
    """
    
    def setUp(self):
        """Set up test data for partial attendee refund"""
        # Create user who made the booking
        self.booking_user = User.objects.create_user(
            username='mum',
            email='mum@family.com',
            password='testpass123'
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Family Conference',
            code='FAMCONF',
            created_by=self.booking_user
        )
        
        self.organisation = Organisation.objects.create(
            title='Family Events Org',
            created_by=self.booking_user
        )
        
        self.event = Event.objects.create(
            title='Annual Family Conference 2026',
            display_code='FC2026',
            display_identifier='FC2026FAMCONF001',
            created_by=self.booking_user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create ticket types
        self.single_day_ticket = TicketType.objects.create(
            event=self.event,
            code='DAY1',
            title='Single Day Pass',
            scope=TicketScopeChoices.SINGLE_DAY,
            valid_from=timezone.now(),
            valid_until=self.event.start_datetime + timedelta(days=1),
            created_by=self.booking_user
        )
        
        self.full_event_ticket = TicketType.objects.create(
            event=self.event,
            code='FULL',
            title='Full Event Pass',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.booking_user
        )
        
        # Create booking packages
        self.single_day_package = BookingPackage.objects.create(
            name='Single Day Package',
            event=self.event,
            ticket_type=self.single_day_ticket,
            base_amount=Money(12, 'GBP'),
            created_by=self.booking_user
        )
        
        self.full_event_package = BookingPackage.objects.create(
            name='Full Event Package',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(25, 'GBP'),
            created_by=self.booking_user
        )
        
        # Create product (Conference T-Shirt)
        self.tshirt = Product.objects.create(
            title='Conference T-Shirt',
            description='Official conference merchandise',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.booking_user,
            verified=True,
            is_active=True
        )
        
        # Create product variant
        self.tshirt_variant = ProductVariant.objects.create(
            product=self.tshirt,
            size=ProductSizeChoices.LARGE,
            color='#000000',
            stock_quantity=100,
            max_stock_quantity=200,
            max_purchase_quantity_per_order=10,
            added_by=self.booking_user,
            verified=True,
            is_active=True
        )
        
        # Link product to single day package
        self.package_product = PackageProduct.objects.create(
            booking_package=self.single_day_package,
            product=self.tshirt,
            quantity_per_attendee=1,
            percentage_modifier=Decimal('-25.00'),  # 25% discount when bundled
            added_by=self.booking_user
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit Card',
            is_active=True,
            created_by=self.booking_user
        )
        
        # Create booking
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-FAMILY-001',
            made_by=self.booking_user
        )
        
        # ===== STEP 1: PARTICIPANT REGISTERS FAMILY =====
        # Create family members as attendees
        
        # Mum (booking user, full event)
        self.mum_attendee = Attendee.objects.create(
            first_name='Sarah',
            last_name='Johnson',
            email='mum@family.com',
            user=self.booking_user,
            event=self.event,
            date_of_birth=date(1985, 3, 15),  # 40 years old
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.booking_user
        )
        
        # Dad (single day - the one we'll refund)
        self.dad_attendee = Attendee.objects.create(
            first_name='John',
            last_name='Johnson',
            email='dad@family.com',
            event=self.event,
            date_of_birth=date(1983, 7, 20),  # 42 years old
            relationship_to_user=AttendeeRelationship.SPOUSE,
            booking=self.booking,
            defined_by=self.booking_user
        )
        
        # Son (full event)
        self.son_attendee = Attendee.objects.create(
            first_name='James',
            last_name='Johnson',
            event=self.event,
            date_of_birth=date(2010, 5, 10),  # 15 years old
            relationship_to_user=AttendeeRelationship.CHILD,
            booking=self.booking,
            defined_by=self.booking_user
        )
        
        # Daughter (full event)
        self.daughter_attendee = Attendee.objects.create(
            first_name='Emma',
            last_name='Johnson',
            event=self.event,
            date_of_birth=date(2015, 11, 25),  # 10 years old
            relationship_to_user=AttendeeRelationship.CHILD,
            booking=self.booking,
            defined_by=self.booking_user
        )
        
        # Create family group
        self.family = FamilyGroup.objects.create(
            family_name='Johnson Family',
            created_by=self.booking_user
        )
        
        FamilyAttendee.objects.create(
            family_group=self.family,
            attendee=self.mum_attendee,
            relationship=HumanRelationshipChoices.PARENT,
            is_primary_guardian=True
        )
        
        FamilyAttendee.objects.create(
            family_group=self.family,
            attendee=self.dad_attendee,
            relationship=HumanRelationshipChoices.PARENT
        )
        
        FamilyAttendee.objects.create(
            family_group=self.family,
            attendee=self.son_attendee,
            relationship=HumanRelationshipChoices.CHILD
        )
        
        FamilyAttendee.objects.create(
            family_group=self.family,
            attendee=self.daughter_attendee,
            relationship=HumanRelationshipChoices.CHILD
        )
    
    @patch('stripe.Refund.create')
    def test_partial_refund_single_attendee_with_ticket_and_product(self, mock_stripe_refund):
        """
        Test: Family realizes dad can't attend. They request a refund for ONLY dad's items.
        
        Steps from participant perspective:
        1. Family completes initial booking and payment for all 4 members
        2. Dad realizes he can't attend
        3. Mum (booking user) requests refund for dad only
        4. Staff verifies and processes the refund
        5. Other family members' bookings remain active
        """
        
        # Mock Stripe refund to return success
        mock_refund = MagicMock()
        mock_refund.id = 're_mock123'
        mock_refund.status = 'succeeded'
        mock_refund.amount = 1200
        mock_stripe_refund.return_value = mock_refund
        
        # ===== STEP 1: PARTICIPANT COMPLETES INITIAL BOOKING =====
        # Calculate costs:
        # Mum: Full event £25
        # Dad: Single day £12
        # Son: Full event £25
        # Daughter: Full event £25
        # Total for tickets: £87
        
        # Create payment for tickets (booking packages)
        ticket_payment = Payment.objects.create(
            user=self.booking_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(87, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            target=self.booking,
            metadata={
                'booking_reference': self.booking.booking_reference,
                'payment_type': 'booking_tickets',
                'attendee_breakdown': {
                    'mum': {
                        'attendee_id': str(self.mum_attendee.attendee_id),
                        'attendee_name': self.mum_attendee.full_name,
                        'package': 'Full Event Package',
                        'amount': '25.00'
                    },
                    'dad': {
                        'attendee_id': str(self.dad_attendee.attendee_id),
                        'attendee_name': self.dad_attendee.full_name,
                        'package': 'Single Day Package',
                        'amount': '12.00'
                    },
                    'son': {
                        'attendee_id': str(self.son_attendee.attendee_id),
                        'attendee_name': self.son_attendee.full_name,
                        'package': 'Full Event Package',
                        'amount': '25.00'
                    },
                    'daughter': {
                        'attendee_id': str(self.daughter_attendee.attendee_id),
                        'attendee_name': self.daughter_attendee.full_name,
                        'package': 'Full Event Package',
                        'amount': '25.00'
                    }
                }
            }
        )
        
        # Complete payment
        ticket_payment.status = PaymentStatusChoices.COMPLETED
        ticket_payment.stripe_payment_intent = 'pi_test_tickets_123'
        ticket_payment.save()
        
        # Create tickets for all family members
        self.mum_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            attendee=self.mum_attendee,
            package=self.full_event_package,
            payment=ticket_payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        self.dad_ticket = Ticket.objects.create(
            ticket_type=self.single_day_ticket,
            attendee=self.dad_attendee,
            package=self.single_day_package,
            payment=ticket_payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        self.son_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            attendee=self.son_attendee,
            package=self.full_event_package,
            payment=ticket_payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        self.daughter_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            attendee=self.daughter_attendee,
            package=self.full_event_package,
            payment=ticket_payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        # ===== PARTICIPANT ALSO PURCHASES T-SHIRTS =====
        # Dad gets a t-shirt with 25% package discount
        # Product base: £20 * 0.75 (25% discount) = £15
        
        product_order = Order.objects.create(
            customer=self.booking_user,
            attendee=self.dad_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.booking_user
        )
        
        # Add dad's t-shirt to order
        dad_tshirt_item = product_order.add_order_item(self.tshirt_variant, 1)
        
        # Manually set the discounted price (as if from package)
        dad_tshirt_item.unit_price = Money(15, 'GBP')
        dad_tshirt_item.total_price = Money(15, 'GBP')
        dad_tshirt_item.save()
        
        product_order.total_amount = Money(15, 'GBP')
        product_order.transition_to(OrderStatusChoices.PENDING)
        product_order.save()
        
        # Create payment for products
        product_payment = Payment.objects.create(
            user=self.booking_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(15, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            target=product_order,
            metadata={
                'payment_type': 'product_purchase',
                'order_reference': product_order.order_reference_id,
                'attendee_id': str(self.dad_attendee.attendee_id),
                'attendee_name': self.dad_attendee.full_name,
                'items': [
                    {
                        'product': 'Conference T-Shirt',
                        'variant_size': 'LARGE',
                        'quantity': 1,
                        'unit_price': '15.00',
                        'total': '15.00'
                    }
                ]
            }
        )
        
        # Link payment to order
        product_order.payment = product_payment
        product_order.save()
        
        # Complete payment
        product_payment.status = PaymentStatusChoices.COMPLETED
        product_payment.stripe_payment_intent = 'pi_test_products_123'
        product_payment.save()
        
        # Complete order
        product_order.transition_to(OrderStatusChoices.PROCESSING)
        product_order.transition_to(OrderStatusChoices.COMPLETED)
        
        # Verify initial state
        self.assertEqual(ticket_payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(product_payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(Ticket.objects.filter(payment=ticket_payment).count(), 4)
        
        # ===== STEP 2: DAD REALIZES HE CAN'T ATTEND =====
        # A few days later, dad realizes he has a work conflict
        # Mum decides to request a refund for ONLY dad's items
        
        # ===== STEP 3: MUM REQUESTS REFUND FOR DAD ONLY =====
        # Total refund amount: Dad's ticket (£12) + Dad's t-shirt (£15) = £27
        
        # First, refund dad's ticket from the ticket payment
        dad_ticket_refund_amount = Money(12, 'GBP')
        
        ticket_refund_request = RefundRequest.objects.create(
            payment=ticket_payment,
            amount=dad_ticket_refund_amount,
            reason='Family member (dad) can no longer attend due to work commitment',
            requested_by=self.booking_user,
            metadata={
                'refund_scope': 'partial',
                'affected_attendee_id': str(self.dad_attendee.attendee_id),
                'affected_attendee_name': self.dad_attendee.full_name,
                'reason_category': 'personal_conflict',
                'request_date': timezone.now().isoformat()
            }
        )
        
        # Verify refund request created correctly
        self.assertIsNotNone(ticket_refund_request.tracking_reference)
        self.assertEqual(ticket_refund_request.verification_status, VerificationStatus.PENDING)
        self.assertEqual(ticket_refund_request.amount, dad_ticket_refund_amount)
        self.assertTrue(ticket_refund_request.is_partial)
        
        # Associate refund with dad's ticket
        # Get frozen amount from payment metadata
        dad_metadata = ticket_payment.metadata['attendee_breakdown']['dad']
        dad_frozen_amount = Money(dad_metadata['amount'], 'GBP')
        
        ticket_refund_association = ticket_refund_request.associate_with(
            self.dad_ticket,
            amount=dad_frozen_amount,
            metadata={
                'attendee_id': dad_metadata['attendee_id'],
                'attendee_name': dad_metadata['attendee_name'],
                'package': dad_metadata['package']
            }
        )
        self.assertIsNotNone(ticket_refund_association)
        self.assertEqual(ticket_refund_association.target_object, self.dad_ticket)
        
        # Second, refund dad's product from the product payment
        dad_product_refund_amount = Money(15, 'GBP')
        
        product_refund_request = RefundRequest.objects.create(
            payment=product_payment,
            amount=dad_product_refund_amount,
            reason='Refunding product for attendee who can no longer attend',
            requested_by=self.booking_user,
            metadata={
                'refund_scope': 'full',  # Full refund of this order (only dad's items)
                'affected_attendee_id': str(self.dad_attendee.attendee_id),
                'affected_attendee_name': self.dad_attendee.full_name,
                'linked_ticket_refund': str(ticket_refund_request.refund_id)
            }
        )
        
        # Verify product refund request
        self.assertEqual(product_refund_request.amount, dad_product_refund_amount)
        self.assertTrue(product_refund_request.is_full)  # Full order refund
        
        # Associate refund with dad's order item
        # Get frozen amount from payment metadata
        dad_product_metadata = product_payment.metadata['items'][0]
        dad_product_frozen_amount = Money(dad_product_metadata['total'], 'GBP')
        
        product_refund_association = product_refund_request.associate_with(
            dad_tshirt_item,
            amount=dad_product_frozen_amount,
            metadata={
                'product': dad_product_metadata['product'],
                'variant_size': dad_product_metadata['variant_size'],
                'quantity': dad_product_metadata['quantity']
            }
        )
        self.assertIsNotNone(product_refund_association)
        self.assertEqual(product_refund_association.target_object, dad_tshirt_item)
        
        # ===== STEP 4: STAFF REVIEWS AND VERIFIES REFUND =====
        admin_user = User.objects.create_user(
            username='admin',
            email='admin@conference.com',
            password='admin123'
        )
        
        # Admin verifies ticket refund
        ticket_refund_request.mark_verified(admin_user)
        ticket_refund_request.refresh_from_db()
        self.assertEqual(ticket_refund_request.verification_status, VerificationStatus.VERIFIED)
        
        # Admin verifies product refund
        product_refund_request.mark_verified(admin_user)
        product_refund_request.refresh_from_db()
        self.assertEqual(product_refund_request.verification_status, VerificationStatus.VERIFIED)
        
        # ===== STEP 5: CREATE PAYMENT HISTORY FOR AUDIT TRAIL =====
        
        # History action for ticket refund
        ticket_history_action = PaymentHistoryAction.objects.create(
            payment=ticket_payment,
            description=f'Partial refund processed for attendee {self.dad_attendee.full_name}',
            action='REFUND_INITIATED',
            performed_by=admin_user,
            metadata={
                'refund_request_id': str(ticket_refund_request.refund_id),
                'refund_tracking_reference': ticket_refund_request.tracking_reference,
                'refund_type': 'partial',
                'refund_scope': 'single_attendee',
                'original_payment_amount': str(ticket_payment.base_amount.amount),
                'original_payment_currency': ticket_payment.base_amount.currency.code,
                'refund_amount': str(ticket_refund_request.amount.amount),
                'refund_currency': ticket_refund_request.amount.currency.code,
                'affected_attendee': {
                    'attendee_id': str(self.dad_attendee.attendee_id),
                    'attendee_name': self.dad_attendee.full_name,
                    'relationship': self.dad_attendee.relationship_to_user
                },
                'refunded_items': [
                    {
                        'type': 'ticket',
                        'ticket_id': str(self.dad_ticket.ticket_id),
                        'ticket_type': self.dad_ticket.ticket_type.title,
                        'package': self.dad_ticket.package.name if self.dad_ticket.package else None,
                        'amount': '12.00'
                    }
                ],
                'unaffected_attendees': [
                    self.mum_attendee.full_name,
                    self.son_attendee.full_name,
                    self.daughter_attendee.full_name
                ]
            },
            notes='Dad unable to attend due to work conflict. Other family members continuing with booking.'
        )
        
        # History action for product refund
        product_history_action = PaymentHistoryAction.objects.create(
            payment=product_payment,
            description=f'Full order refund for attendee {self.dad_attendee.full_name}',
            action='REFUND_INITIATED',
            performed_by=admin_user,
            metadata={
                'refund_request_id': str(product_refund_request.refund_id),
                'refund_tracking_reference': product_refund_request.tracking_reference,
                'refund_type': 'full',
                'refund_scope': 'complete_order',
                'original_payment_amount': str(product_payment.base_amount.amount),
                'refund_amount': str(product_refund_request.amount.amount),
                'affected_attendee': {
                    'attendee_id': str(self.dad_attendee.attendee_id),
                    'attendee_name': self.dad_attendee.full_name
                },
                'refunded_items': [
                    {
                        'type': 'product',
                        'order_item_id': dad_tshirt_item.id,
                        'product': 'Conference T-Shirt',
                        'variant_size': 'LARGE',
                        'quantity': 1,
                        'unit_price': '15.00',
                        'total': '15.00'
                    }
                ],
                'linked_ticket_refund': str(ticket_refund_request.refund_id)
            },
            notes='Product purchased with package discount being refunded alongside ticket.'
        )
        
        # Verify history actions created
        self.assertEqual(ticket_history_action.action, 'REFUND_INITIATED')
        self.assertEqual(product_history_action.action, 'REFUND_INITIATED')
        self.assertEqual(ticket_history_action.metadata['refund_scope'], 'single_attendee')
        self.assertEqual(len(ticket_history_action.metadata['unaffected_attendees']), 3)
        
        # ===== STEP 6: STAFF PROCESSES EXTERNAL REFUNDS =====
        # Admin processes refunds via Stripe
        
        ticket_refund_request.mark_processed(admin_user)
        ticket_refund_request.refresh_from_db()
        self.assertEqual(ticket_refund_request.verification_status, VerificationStatus.PROCESSED)
        
        product_refund_request.mark_processed(admin_user)
        product_refund_request.refresh_from_db()
        self.assertEqual(product_refund_request.verification_status, VerificationStatus.PROCESSED)
        
        # Note: Payments remain COMPLETED since these are partial refunds
        # Only if ALL items were refunded would we change to REFUNDED
        self.assertEqual(ticket_payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(product_payment.status, PaymentStatusChoices.COMPLETED)
        
        # Cancel dad's ticket
        self.dad_ticket.status = TicketStatusChoices.CANCELLED
        self.dad_ticket.save()
        
        # ===== STEP 7: VERIFY OTHER FAMILY MEMBERS UNAFFECTED =====
        # Mum, son, and daughter's tickets should still be active
        self.mum_ticket.refresh_from_db()
        self.son_ticket.refresh_from_db()
        self.daughter_ticket.refresh_from_db()
        
        self.assertEqual(self.mum_ticket.status, TicketStatusChoices.ACTIVE)
        self.assertEqual(self.son_ticket.status, TicketStatusChoices.ACTIVE)
        self.assertEqual(self.daughter_ticket.status, TicketStatusChoices.ACTIVE)
        
        # Verify dad's ticket is cancelled
        self.dad_ticket.refresh_from_db()
        self.assertEqual(self.dad_ticket.status, TicketStatusChoices.CANCELLED)
        
        # Verify booking still exists and has 4 attendees
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.attendees.count(), 4)
        
        # ===== STEP 8: VERIFY TOTAL REFUNDS =====
        # Total refunded: £12 (ticket) + £15 (product) = £27
        total_ticket_refunds = sum(
            req.amount.amount 
            for req in ticket_payment.refund_requests.all()
        )
        total_product_refunds = sum(
            req.amount.amount 
            for req in product_payment.refund_requests.all()
        )
        
        self.assertEqual(total_ticket_refunds, Decimal('12.00'))
        self.assertEqual(total_product_refunds, Decimal('15.00'))
        
        # Verify refund associations
        self.assertEqual(ticket_refund_request.associations.count(), 1)
        self.assertEqual(product_refund_request.associations.count(), 1)
        
        # Verify payment history records
        self.assertEqual(ticket_payment.history_actions.count(), 1)
        self.assertEqual(product_payment.history_actions.count(), 1)


class AttendeeRemovalWithRefundPolicyTest(TestCase):
    """
    Test removing an attendee from an event with different refund policies.
    
    Scenarios:
    1. Full refund (100% return) - early cancellation
    2. Partial refund (50% return) - cancellation with penalty
    3. No refund - last minute cancellation or policy violation
    
    Must check payment history to find all COMPLETED/PROCESSED payments for attendee.
    """
    
    def setUp(self):
        """Set up test data for attendee removal with refund policies"""
        # Create organizer user
        self.organizer = User.objects.create_user(
            username='organizer',
            email='organizer@events.com',
            password='testpass123'
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Workshop Event',
            code='WORKSHOP',
            created_by=self.organizer
        )
        
        self.organisation = Organisation.objects.create(
            title='Workshop Organization',
            created_by=self.organizer
        )
        
        self.event = Event.objects.create(
            title='Professional Workshop 2026',
            display_code='PW2026',
            display_identifier='PW2026WORKSHOP001',
            created_by=self.organizer,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=60),  # 60 days away
            end_datetime=timezone.now() + timedelta(days=62),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create ticket type
        self.workshop_ticket = TicketType.objects.create(
            event=self.event,
            code='WS',
            title='Workshop Ticket',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.organizer
        )
        
        # Create booking package
        self.workshop_package = BookingPackage.objects.create(
            name='Workshop Package',
            event=self.event,
            ticket_type=self.workshop_ticket,
            base_amount=Money(150, 'GBP'),
            created_by=self.organizer
        )
        
        # Create product
        self.workbook = Product.objects.create(
            title='Workshop Materials',
            description='Comprehensive workshop workbook',
            event=self.event,
            base_amount=Money(30, 'GBP'),
            added_by=self.organizer,
            verified=True,
            is_active=True
        )
        
        self.workbook_variant = ProductVariant.objects.create(
            product=self.workbook,
            size=ProductSizeChoices.ONE_SIZE,
            color='#FFFFFF',
            stock_quantity=100,
            max_stock_quantity=200,
            max_purchase_quantity_per_order=5,
            added_by=self.organizer,
            verified=True,
            is_active=True
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit Card',
            is_active=True,
            created_by=self.organizer
        )
        
    def _create_attendee_with_full_booking(self, username, email, first_name, last_name, dob):
        """
        Helper: Create an attendee with completed ticket and product purchase.
        
        Returns: (user, attendee, ticket_payment, product_payment, ticket, order)
        """
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password='testpass123'
        )
        
        # Create booking
        booking = Booking.objects.create(
            event=self.event,
            booking_reference=f'BKG-{username.upper()}-001',
            made_by=user
        )
        
        # Create attendee
        attendee = Attendee.objects.create(
            first_name=first_name,
            last_name=last_name,
            email=email,
            user=user,
            event=self.event,
            date_of_birth=dob,
            relationship_to_user=AttendeeRelationship.SELF,
            booking=booking,
            defined_by=user
        )
        
        # Create ticket payment
        ticket_payment = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(150, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target=booking,
            stripe_payment_intent=f'pi_{username}_ticket',
            metadata={
                'payment_type': 'booking_ticket',
                'attendee_id': str(attendee.attendee_id),
                'attendee_name': attendee.full_name,
                'package': self.workshop_package.name
            }
        )
        
        # Create ticket
        ticket = Ticket.objects.create(
            ticket_type=self.workshop_ticket,
            attendee=attendee,
            package=self.workshop_package,
            payment=ticket_payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        # Create product order
        order = Order.objects.create(
            customer=user,
            attendee=attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=user
        )
        
        order_item = order.add_order_item(self.workbook_variant, 1)
        order.total_amount = Money(30, 'GBP')
        order.transition_to(OrderStatusChoices.PENDING)
        order.save()
        
        # Create product payment
        product_payment = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(30, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target=order,
            stripe_payment_intent=f'pi_{username}_product',
            metadata={
                'payment_type': 'product_purchase',
                'attendee_id': str(attendee.attendee_id),
                'order_reference': order.order_reference_id
            }
        )
        
        order.payment = product_payment
        order.transition_to(OrderStatusChoices.PROCESSING)
        order.transition_to(OrderStatusChoices.COMPLETED)
        order.save()
        
        return user, attendee, ticket_payment, product_payment, ticket, order
    
    def _get_active_payments_for_attendee(self, attendee):
        """
        Helper: Get all active/completed payments for a specific attendee.
        
        Returns only payments that are COMPLETED and haven't been refunded.
        This mirrors what would happen in production when removing an attendee.
        """
        # Find all completed payments related to this attendee
        active_payments = []
        
        # Check ticket payments (via tickets)
        ticket_payments = Payment.objects.filter(
            tickets__attendee=attendee,
            status=PaymentStatusChoices.COMPLETED
        ).distinct()
        
        for payment in ticket_payments:
            # Check if already refunded
            total_refunded = sum(
                req.amount.amount 
                for req in payment.refund_requests.filter(
                    verification_status=VerificationStatus.PROCESSED
                )
            )
            
            # Only include if not fully refunded
            if total_refunded < payment.base_amount.amount:
                active_payments.append(payment)
        
        # Check product payments (via orders)
        product_payments = Payment.objects.filter(
            target_type=ContentType.objects.get_for_model(Order),
            status=PaymentStatusChoices.COMPLETED
        ).distinct()
        
        for payment in product_payments:
            if payment.target and hasattr(payment.target, 'attendee'):
                if payment.target.attendee == attendee:
                    # Check if already refunded
                    total_refunded = sum(
                        req.amount.amount 
                        for req in payment.refund_requests.filter(
                            verification_status=VerificationStatus.PROCESSED
                        )
                    )
                    
                    if total_refunded < payment.base_amount.amount:
                        active_payments.append(payment)
        
        return active_payments
    
    @patch('stripe.Refund.create')
    def test_full_refund_early_cancellation(self, mock_stripe_refund):
        """
        Test: Attendee cancels well in advance (100% refund policy).
        
        Staff perspective:
        1. Attendee requests cancellation 60 days before event
        2. Staff checks refund policy - full refund eligible
        3. Staff processes 100% refund of all payments
        4. Staff removes attendee from event
        """
        
        # Mock Stripe refund to return success
        mock_refund = MagicMock()
        mock_refund.id = 're_mock456'
        mock_refund.status = 'succeeded'
        mock_stripe_refund.return_value = mock_refund
        
        # ===== STEP 1: CREATE ATTENDEE WITH BOOKING =====
        user, attendee, ticket_payment, product_payment, ticket, order = \
            self._create_attendee_with_full_booking(
                'alice', 'alice@example.com', 'Alice', 'Smith',
                date(1992, 4, 10)
            )
        
        # Verify initial state
        self.assertEqual(ticket_payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(product_payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(ticket.status, TicketStatusChoices.ACTIVE)
        
        # ===== STEP 2: ATTENDEE REQUESTS CANCELLATION =====
        # Alice realizes she can't attend and requests cancellation early
        
        # ===== STEP 3: STAFF CHECKS ACTIVE PAYMENTS =====
        active_payments = self._get_active_payments_for_attendee(attendee)
        
        # Should find 2 payments: ticket and product
        self.assertEqual(len(active_payments), 2)
        
        total_refundable = sum(p.base_amount.amount for p in active_payments)
        self.assertEqual(total_refundable, Decimal('180.00'))  # £150 + £30
        
        # ===== STEP 4: STAFF APPLIES 100% REFUND POLICY =====
        # Early cancellation = full refund
        refund_percentage = Decimal('100.00')
        
        admin = User.objects.create_user(
            username='admin',
            email='admin@workshop.com',
            password='admin123'
        )
        
        # Process refunds for each payment
        refund_requests = []
        
        for payment in active_payments:
            refund_amount = payment.base_amount
            
            refund_request = RefundRequest.objects.create(
                payment=payment,
                amount=refund_amount,
                reason=f'Early cancellation by attendee - {refund_percentage}% refund policy applied',
                requested_by=user,
                metadata={
                    'refund_policy': 'full_refund',
                    'refund_percentage': str(refund_percentage),
                    'cancellation_timing': 'early',
                    'days_before_event': 60,
                    'attendee_id': str(attendee.attendee_id),
                    'attendee_name': attendee.full_name,
                    'removal_reason': 'attendee_request'
                }
            )
            
            # Verify and process
            refund_request.mark_verified(admin)
            refund_request.mark_processed(admin)
            refund_requests.append(refund_request)
            
            # Create payment history
            PaymentHistoryAction.objects.create(
                payment=payment,
                description=f'Full refund processed for attendee removal - {attendee.full_name}',
                action='REFUND_COMPLETED',
                performed_by=admin,
                metadata={
                    'refund_request_id': str(refund_request.refund_id),
                    'refund_policy': 'full_refund',
                    'refund_percentage': '100.00',
                    'original_amount': str(payment.base_amount.amount),
                    'refund_amount': str(refund_amount.amount),
                    'attendee_id': str(attendee.attendee_id),
                    'attendee_name': attendee.full_name,
                    'reason': 'Early cancellation by attendee'
                }
            )
            
            # Update payment status
            payment.status = PaymentStatusChoices.REFUNDED
            payment.save()
        
        # ===== STEP 5: VERIFY REFUNDS COMPLETED =====
        self.assertEqual(len(refund_requests), 2)
        
        for refund_request in refund_requests:
            self.assertEqual(refund_request.verification_status, VerificationStatus.PROCESSED)
            self.assertTrue(refund_request.is_full)
        
        # Verify payments refunded
        ticket_payment.refresh_from_db()
        product_payment.refresh_from_db()
        self.assertEqual(ticket_payment.status, PaymentStatusChoices.REFUNDED)
        self.assertEqual(product_payment.status, PaymentStatusChoices.REFUNDED)
        
        # ===== STEP 6: STAFF REMOVES ATTENDEE =====
        # Cancel ticket
        ticket.status = TicketStatusChoices.CANCELLED
        ticket.save()
        
        # Soft delete attendee
        attendee.soft_delete()
        
        # Verify attendee marked as deleted
        attendee.refresh_from_db()
        self.assertIsNotNone(attendee.deleted_at)
    
    @patch('stripe.Refund.create')
    def test_partial_refund_with_cancellation_penalty(self, mock_stripe_refund):
        """
        Test: Attendee cancels with moderate notice (50% refund policy).
        
        Staff perspective:
        1. Attendee requests cancellation 20 days before event
        2. Staff checks refund policy - 50% refund with penalty
        3. Staff processes 50% refund of all payments
        4. Staff documents cancellation penalty
        """
        
        # Mock Stripe refund to return success
        mock_refund = MagicMock()
        mock_refund.id = 're_mock789'
        mock_refund.status = 'succeeded'
        mock_stripe_refund.return_value = mock_refund
        
        # ===== STEP 1: CREATE ATTENDEE WITH BOOKING =====
        user, attendee, ticket_payment, product_payment, ticket, order = \
            self._create_attendee_with_full_booking(
                'bob', 'bob@example.com', 'Bob', 'Jones',
                date(1988, 8, 15)
            )
        
        # ===== STEP 2: STAFF CHECKS ACTIVE PAYMENTS =====
        active_payments = self._get_active_payments_for_attendee(attendee)
        self.assertEqual(len(active_payments), 2)
        
        # ===== STEP 3: STAFF APPLIES 50% REFUND POLICY =====
        refund_percentage = Decimal('50.00')
        
        admin = User.objects.create_user(
            username='admin2',
            email='admin2@workshop.com',
            password='admin123'
        )
        
        for payment in active_payments:
            # Calculate 50% refund
            refund_amount = Money(
                payment.base_amount.amount * (refund_percentage / 100),
                payment.base_amount.currency
            )
            
            refund_request = RefundRequest.objects.create(
                payment=payment,
                amount=refund_amount,
                reason=f'Moderate notice cancellation - {refund_percentage}% refund policy applied',
                requested_by=user,
                metadata={
                    'refund_policy': 'partial_refund_with_penalty',
                    'refund_percentage': str(refund_percentage),
                    'penalty_percentage': '50.00',
                    'cancellation_timing': 'moderate',
                    'days_before_event': 20,
                    'attendee_id': str(attendee.attendee_id),
                    'original_amount': str(payment.base_amount.amount),
                    'penalty_amount': str(payment.base_amount.amount * Decimal('0.5'))
                }
            )
            
            refund_request.mark_verified(admin)
            refund_request.mark_processed(admin)
            
            # Create payment history
            PaymentHistoryAction.objects.create(
                payment=payment,
                description=f'Partial refund (50%) processed for attendee removal - {attendee.full_name}',
                action='REFUND_COMPLETED',
                performed_by=admin,
                metadata={
                    'refund_request_id': str(refund_request.refund_id),
                    'refund_policy': 'partial_refund_with_penalty',
                    'refund_percentage': '50.00',
                    'penalty_percentage': '50.00',
                    'original_amount': str(payment.base_amount.amount),
                    'refund_amount': str(refund_amount.amount),
                    'penalty_amount': str(payment.base_amount.amount * Decimal('0.5')),
                    'attendee_id': str(attendee.attendee_id),
                    'reason': 'Cancellation with moderate notice'
                }
            )
            
            # Payment status remains COMPLETED (partial refund)
            # Could add custom status if needed
        
        # ===== STEP 4: VERIFY PARTIAL REFUNDS =====
        ticket_refund = ticket_payment.refund_requests.first()
        product_refund = product_payment.refund_requests.first()
        
        self.assertEqual(ticket_refund.amount, Money(75, 'GBP'))  # 50% of £150
        self.assertEqual(product_refund.amount, Money(15, 'GBP'))  # 50% of £30
        
        self.assertTrue(ticket_refund.is_partial)
        self.assertTrue(product_refund.is_partial)
        
        # ===== STEP 5: STAFF REMOVES ATTENDEE =====
        ticket.status = TicketStatusChoices.CANCELLED
        ticket.save()
        
        attendee.soft_delete()
        attendee.refresh_from_db()
        self.assertIsNotNone(attendee.deleted_at)
        
    def test_no_refund_last_minute_cancellation(self):
        """
        Test: Attendee cancels last minute (0% refund policy).
        
        Staff perspective:
        1. Attendee requests cancellation 2 days before event
        2. Staff checks refund policy - no refund due to late cancellation
        3. Staff documents no-refund decision
        4. Staff still removes attendee but no payment refund
        """
        
        # ===== STEP 1: CREATE ATTENDEE WITH BOOKING =====
        user, attendee, ticket_payment, product_payment, ticket, order = \
            self._create_attendee_with_full_booking(
                'charlie', 'charlie@example.com', 'Charlie', 'Brown',
                date(1995, 12, 5)
            )
        
        # ===== STEP 2: STAFF CHECKS ACTIVE PAYMENTS =====
        active_payments = self._get_active_payments_for_attendee(attendee)
        self.assertEqual(len(active_payments), 2)
        
        total_non_refundable = sum(p.base_amount.amount for p in active_payments)
        self.assertEqual(total_non_refundable, Decimal('180.00'))
        
        # ===== STEP 3: STAFF APPLIES NO REFUND POLICY =====
        admin = User.objects.create_user(
            username='admin3',
            email='admin3@workshop.com',
            password='admin123'
        )
        
        # Document no-refund decision in payment history
        for payment in active_payments:
            PaymentHistoryAction.objects.create(
                payment=payment,
                description=f'No refund - late cancellation policy applied for {attendee.full_name}',
                action='NO_REFUND_POLICY_APPLIED',
                performed_by=admin,
                metadata={
                    'refund_policy': 'no_refund',
                    'refund_percentage': '0.00',
                    'cancellation_timing': 'last_minute',
                    'days_before_event': 2,
                    'attendee_id': str(attendee.attendee_id),
                    'attendee_name': attendee.full_name,
                    'payment_amount': str(payment.base_amount.amount),
                    'reason': 'Last minute cancellation - outside refund window',
                    'policy_reference': 'Late cancellation policy - no refunds within 7 days of event'
                }
            )
        
        # ===== STEP 4: VERIFY NO REFUNDS CREATED =====
        self.assertEqual(ticket_payment.refund_requests.count(), 0)
        self.assertEqual(product_payment.refund_requests.count(), 0)
        
        # Payments remain completed
        self.assertEqual(ticket_payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(product_payment.status, PaymentStatusChoices.COMPLETED)
        
        # ===== STEP 5: STAFF STILL REMOVES ATTENDEE =====
        # Even without refund, attendee is removed
        ticket.status = TicketStatusChoices.CANCELLED
        ticket.save()
        
        attendee.soft_delete()
        attendee.refresh_from_db()
        self.assertIsNotNone(attendee.deleted_at)
        
        # Verify history actions recorded
        self.assertEqual(ticket_payment.history_actions.count(), 1)
        self.assertEqual(product_payment.history_actions.count(), 1)
        
        no_refund_action = ticket_payment.history_actions.first()
        self.assertEqual(no_refund_action.action, 'NO_REFUND_POLICY_APPLIED')
        self.assertEqual(no_refund_action.metadata['refund_percentage'], '0.00')


class AttendeeRefundComplexScenariosTest(TestCase):
    """
    Test complex refund scenarios with multiple payments and edge cases.
    """
    
    def setUp(self):
        """Set up test data for complex scenarios"""
        self.organizer = User.objects.create_user(
            username='organizer',
            email='organizer@events.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Complex Event',
            code='COMPLEX',
            created_by=self.organizer
        )
        
        self.organisation = Organisation.objects.create(
            title='Complex Events Org',
            created_by=self.organizer
        )
        
        self.event = Event.objects.create(
            title='Complex Conference 2026',
            display_code='CC2026',
            display_identifier='CC2026COMPLEX001',
            created_by=self.organizer,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=45),
            end_datetime=timezone.now() + timedelta(days=47),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='STD',
            title='Standard Ticket',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.organizer
        )
        
        self.package = BookingPackage.objects.create(
            name='Standard Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            created_by=self.organizer
        )
        
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit Card',
            is_active=True,
            created_by=self.organizer
        )

    def _create_attendee_with_full_booking(self, username, email, first_name, last_name, dob):
        """Create an attendee with completed ticket and product purchase."""
        user = User.objects.create_user(
            username=username,
            email=email,
            password='testpass123'
        )

        booking = Booking.objects.create(
            event=self.event,
            booking_reference=f'BKG-{username.upper()}-001',
            made_by=user
        )

        attendee = Attendee.objects.create(
            first_name=first_name,
            last_name=last_name,
            email=email,
            user=user,
            event=self.event,
            date_of_birth=dob,
            relationship_to_user=AttendeeRelationship.SELF,
            booking=booking,
            defined_by=user
        )

        ticket_payment = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target=booking,
            stripe_payment_intent=f'pi_{username}_ticket',
            metadata={
                'payment_type': 'booking_ticket',
                'attendee_id': str(attendee.attendee_id),
                'attendee_name': attendee.full_name,
            }
        )

        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=attendee,
            package=self.package,
            payment=ticket_payment,
            status=TicketStatusChoices.ACTIVE
        )

        order = Order.objects.create(
            customer=user,
            attendee=attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=user
        )

        order.transition_to(OrderStatusChoices.PENDING)
        order.save()

        product_payment = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(25, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target=order,
            stripe_payment_intent=f'pi_{username}_product',
            metadata={
                'payment_type': 'product_purchase',
                'attendee_id': str(attendee.attendee_id),
                'order_reference': order.order_reference_id,
            }
        )

        order.payment = product_payment
        order.transition_to(OrderStatusChoices.PROCESSING)
        order.transition_to(OrderStatusChoices.COMPLETED)
        order.save()

        return user, attendee, ticket_payment, product_payment, ticket, order
    
    @patch('stripe.Refund.create')
    def test_refund_attendee_with_multiple_payments(self, mock_stripe_refund):
        """
        Test: Attendee has multiple separate payments (ticket, upgrade, merchandise).
        All must be identified and refunded when removing attendee.
        """
        
        # Mock Stripe refund to return success
        mock_refund = MagicMock()
        mock_refund.id = 're_mock_multi'
        mock_refund.status = 'succeeded'
        mock_stripe_refund.return_value = mock_refund
        
        # Create user and booking
        user = User.objects.create_user(
            username='david',
            email='david@example.com',
            password='testpass123'
        )
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-DAVID-001',
            made_by=user
        )
        
        attendee = Attendee.objects.create(
            first_name='David',
            last_name='Wilson',
            email='david@example.com',
            user=user,
            event=self.event,
            date_of_birth=date(1990, 5, 20),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=booking,
            defined_by=user
        )
        
        # ===== PAYMENT 1: Initial ticket =====
        payment1 = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target=booking,
            stripe_payment_intent='pi_ticket_001',
            metadata={'payment_type': 'initial_ticket', 'attendee_id': str(attendee.attendee_id)}
        )
        
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=attendee,
            package=self.package,
            payment=payment1,
            status=TicketStatusChoices.ACTIVE
        )
        
        # ===== PAYMENT 2: Later upgrade =====
        payment2 = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            stripe_payment_intent='pi_upgrade_001',
            metadata={'payment_type': 'ticket_upgrade', 'attendee_id': str(attendee.attendee_id)}
        )
        
        # ===== PAYMENT 3: Merchandise =====
        payment3 = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(25, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            stripe_payment_intent='pi_merch_001',
            metadata={'payment_type': 'merchandise', 'attendee_id': str(attendee.attendee_id)}
        )
        
        # ===== STAFF IDENTIFIES ALL PAYMENTS =====
        # In production, would query by attendee_id in metadata
        all_payments = Payment.objects.filter(
            event=self.event,
            user=user,
            status=PaymentStatusChoices.COMPLETED
        ).exclude(
            refund_requests__verification_status=VerificationStatus.PROCESSED
        )
        
        self.assertEqual(all_payments.count(), 3)
        
        total_to_refund = sum(p.base_amount.amount for p in all_payments)
        self.assertEqual(total_to_refund, Decimal('175.00'))  # £100 + £50 + £25
        
        # ===== STAFF PROCESSES FULL REFUND FOR ALL =====
        admin = User.objects.create_user(
            username='admin',
            email='admin@complex.com',
            password='admin123'
        )
        
        for payment in all_payments:
            refund_request = RefundRequest.objects.create(
                payment=payment,
                amount=payment.base_amount,
                reason=f'Attendee removal - full refund of all payments',
                requested_by=user,
                metadata={
                    'refund_type': 'attendee_removal',
                    'attendee_id': str(attendee.attendee_id),
                    'payment_category': payment.metadata.get('payment_type', 'unknown')
                }
            )
            
            refund_request.mark_verified(admin)
            refund_request.mark_processed(admin)
            
            payment.status = PaymentStatusChoices.REFUNDED
            payment.save()
        
        # Verify all refunded
        refunded_count = Payment.objects.filter(
            event=self.event,
            user=user,
            status=PaymentStatusChoices.REFUNDED
        ).count()
        
        self.assertEqual(refunded_count, 3)
    
    @patch('stripe.Refund.create')
    def test_refund_with_already_partially_refunded_payment(self, mock_stripe_refund):
        """
        Test: Attendee has a payment that was already partially refunded.
        When removing attendee, only refund the remaining amount.
        """
        
        # Mock Stripe refund to return success
        mock_refund = MagicMock()
        mock_refund.id = 're_mock_partial'
        mock_refund.status = 'succeeded'
        mock_stripe_refund.return_value = mock_refund
        
        user = User.objects.create_user(
            username='emily',
            email='emily@example.com',
            password='testpass123'
        )
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-EMILY-001',
            made_by=user
        )
        
        attendee = Attendee.objects.create(
            first_name='Emily',
            last_name='Davis',
            email='emily@example.com',
            user=user,
            event=self.event,
            date_of_birth=date(1993, 9, 12),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=booking,
            defined_by=user
        )
        
        # Create payment
        payment = Payment.objects.create(
            user=user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target=booking,
            stripe_payment_intent='pi_emily_001',
            metadata={'attendee_id': str(attendee.attendee_id)}
        )
        
        # ===== EARLIER: Partial refund was already processed =====
        earlier_refund = RefundRequest.objects.create(
            payment=payment,
            amount=Money(30, 'GBP'),
            reason='Item cancellation',
            requested_by=user
        )
        
        admin = User.objects.create_user(
            username='admin',
            email='admin@complex.com',
            password='admin123'
        )
        
        earlier_refund.mark_verified(admin)
        earlier_refund.mark_processed(admin)
        
        # ===== NOW: Remove attendee, refund remaining amount =====
        # Calculate remaining refundable amount
        total_refunded = sum(
            req.amount.amount 
            for req in payment.refund_requests.filter(
                verification_status=VerificationStatus.PROCESSED
            )
        )
        
        remaining_amount = payment.base_amount.amount - total_refunded
        self.assertEqual(remaining_amount, Decimal('70.00'))  # £100 - £30
        
        # Create final refund request
        final_refund = RefundRequest.objects.create(
            payment=payment,
            amount=Money(remaining_amount, 'GBP'),
            reason='Attendee removal - refunding remaining balance',
            requested_by=user,
            metadata={
                'refund_type': 'attendee_removal_remaining',
                'original_amount': '100.00',
                'previously_refunded': '30.00',
                'remaining_refund': str(remaining_amount),
                'attendee_id': str(attendee.attendee_id)
            }
        )
        
        final_refund.mark_verified(admin)
        final_refund.mark_processed(admin)
        
        # Verify total refunds
        total_all_refunds = sum(
            req.amount.amount 
            for req in payment.refund_requests.filter(
                verification_status=VerificationStatus.PROCESSED
            )
        )
        
        self.assertEqual(total_all_refunds, Decimal('100.00'))  # £30 + £70
        
        # Now payment can be marked as fully refunded
        payment.status = PaymentStatusChoices.REFUNDED
        payment.save()
        
        self.assertEqual(payment.status, PaymentStatusChoices.REFUNDED)

    def test_pre_removal_summary_includes_verbose_blocker_context_and_pagination(self):
        user, attendee, ticket_payment, product_payment, ticket, order = self._create_attendee_with_full_booking(
            'sarah', 'sarah@example.com', 'Sarah', 'Jones', date(1991, 6, 14)
        )

        admin = User.objects.create_superuser(
            username='summary-admin',
            email='summary-admin@example.com',
            password='admin123'
        )

        RefundRequest.objects.create(
            payment=ticket_payment,
            amount=ticket_payment.base_amount,
            reason='Active refund request for summary coverage',
            requested_by=admin,
        )

        factory = APIRequestFactory()
        request = factory.get('/api/attendees/summary/?page_size=1')
        force_authenticate(request, user=admin)

        view = AttendeeViewSet()
        view.request = request

        summary = view._build_pre_removal_summary(attendee)
        blockers_by_code = {blocker['code']: blocker for blocker in summary['blockers']}

        self.assertIn('linked_payments', blockers_by_code)
        linked_blocker = blockers_by_code['linked_payments']
        self.assertEqual(linked_blocker['count'], 2)
        self.assertEqual(linked_blocker['pagination']['page_size'], 1)
        self.assertTrue(linked_blocker['pagination']['has_next'])
        self.assertEqual(len(linked_blocker['items']), 1)

        linked_item = linked_blocker['items'][0]
        self.assertIn('payment_type', linked_item)
        self.assertIn('payment_descriptor', linked_item)
        self.assertIn('payment_status_bucket', linked_item)
        self.assertIn('can_request_refund', linked_item)
        self.assertIn('_links', linked_item)
        self.assertIn(linked_item['payment_type'], {'booking', 'order'})

        self.assertIn('outstanding_payments', blockers_by_code)
        outstanding_blocker = blockers_by_code['outstanding_payments']
        self.assertEqual(outstanding_blocker['pagination']['page_size'], 1)
        self.assertEqual(len(outstanding_blocker['items']), 1)
        self.assertIn('refund_block_reason', outstanding_blocker['items'][0])

        self.assertIn('active_tickets', blockers_by_code)
        active_ticket_item = blockers_by_code['active_tickets']['items'][0]
        self.assertEqual(active_ticket_item['ticket_code'], ticket.ticket_code)
        self.assertIn('payment_id', active_ticket_item)
        self.assertIn('payment_descriptor', active_ticket_item)

        self.assertIn('unresolved_orders', blockers_by_code)
        order_item = blockers_by_code['unresolved_orders']['items'][0]
        self.assertEqual(order_item['order_reference'], order.order_reference_id)
        self.assertIn('order_amount', order_item)
        self.assertIn('payment_type', order_item)

        self.assertIn('active_refunds', blockers_by_code)
        active_refunds_blocker = blockers_by_code['active_refunds']
        self.assertEqual(active_refunds_blocker['count'], 1)
        self.assertEqual(active_refunds_blocker['items'][0]['active_refund_count'], 1)
        self.assertEqual(active_refunds_blocker['items'][0]['active_refunds'][0]['requested_by_name'], admin.username)
        self.assertIn('tracking_reference', active_refunds_blocker['items'][0]['active_refunds'][0])

    def test_pre_removal_summary_marks_refund_eligibility_with_reason(self):
        _, attendee, ticket_payment, _, _, _ = self._create_attendee_with_full_booking(
            'tom', 'tom@example.com', 'Tom', 'White', date(1994, 3, 2)
        )

        factory = APIRequestFactory()
        request = factory.get('/api/attendees/summary/')
        force_authenticate(request, user=self.organizer)

        view = AttendeeViewSet()
        view.request = request

        summary = view._build_pre_removal_summary(attendee)
        linked_blocker = next(blocker for blocker in summary['blockers'] if blocker['code'] == 'linked_payments')
        payment_item = next(item for item in linked_blocker['items'] if item['payment_id'] == str(ticket_payment.payment_id))

        self.assertIn('can_request_refund', payment_item)
        self.assertIn('refund_block_reason', payment_item)
        self.assertFalse(payment_item['can_request_refund'])
