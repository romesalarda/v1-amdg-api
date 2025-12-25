"""
Full booking flow integration test.

Tests the complete registration and payment flow:
1. Create attendees (Sam + 4 family members)
2. Create family group
3. Add personal info (medical, dietary, accessibility)
4. Create booking object
5. Choose ticket type per attendee
6. Choose package per attendee
7. Calculate prices with discounts
8. Create payment object
9. Create tickets linked to payment

Scenario:
Sam (19) is registering for a youth event with his family:
- Sam (19, event staff) - FULL_EVENT, gets 10% staff discount
- Mum (45) - SINGLE_DAY, standard price
- Dad (48) - SINGLE_DAY, standard price
- Brother (14) - FULL_EVENT, gets 15% child discount
- Sister (2) - FULL_EVENT, gets 15% child discount

Packages:
- Early bird: £10
- Standard: £15
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money

from apps.bookings.models import (
    Booking, BookingPackage, BookingPackageRule,
    TicketType, Ticket, TicketScopeChoices, TicketStatusChoices,
    PackageRuleTypeChoices
)
from apps.payments.models import (
    Payment, PaymentMethod, PaymentMethodTypeChoices,
    PaymentStatusChoices, Discount, DiscountType,
    DiscountRule, DiscountRuleTypeChoices
)
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import (
    Attendee, AttendeeRelationship, FamilyGroup, FamilyAttendee,
    HumanRelationshipChoices
)
from apps.attendee.models.personal import (
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    AccessibilityRequirement, AttendeeAccessibilityRequirement
)
from apps.organisations.models import Organisation

User = get_user_model()


class FullBookingFlowIntegrationTest(TestCase):
    """
    Test the complete booking flow from attendee creation to ticket issuance.
    """
    
    def setUp(self):
        """Set up test data for the full booking flow"""
        # Create Sam's user account
        self.sam = User.objects.create_user(
            username='sam',
            email='sam@example.com',
            password='testpass123'
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Youth Conference',
            code='YOUTH',
            created_by=self.sam
        )
        
        self.event = Event.objects.create(
            title='Annual Youth Conference 2025',
            display_code='YC2025',
            display_identifier='YC2025YOUTH001',
            created_by=self.sam,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN
        )
        
        # Create ticket types
        self.full_event_ticket = TicketType.objects.create(
            event=self.event,
            code='FULL',
            title='Full Event Pass',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.sam
        )
        
        self.single_day_ticket = TicketType.objects.create(
            event=self.event,
            code='DAY1',
            title='Single Day Pass',
            scope=TicketScopeChoices.SINGLE_DAY,
            valid_from=timezone.now(),
            valid_until=self.event.start_datetime + timedelta(days=1),
            created_by=self.sam
        )
        
        # Create booking packages
        self.early_bird_package = BookingPackage.objects.create(
            name='Early Bird',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(10, 'GBP'),
            created_by=self.sam
        )
        
        self.standard_package = BookingPackage.objects.create(
            name='Standard',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(15, 'GBP'),
            created_by=self.sam
        )
        
        self.single_day_package = BookingPackage.objects.create(
            name='Day Pass Package',
            event=self.event,
            ticket_type=self.single_day_ticket,
            base_amount=Money(12, 'GBP'),
            created_by=self.sam
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
            is_active=True,
            created_by=self.sam
        )
        
        # Create personal info options
        self.vegetarian = DietaryRequirement.objects.create(
            code='VEG',
            label='Vegetarian',
            description='No meat or fish'
        )
        
        self.gluten_free = DietaryRequirement.objects.create(
            code='GF',
            label='Gluten Free',
            description='No gluten'
        )
        
        self.asthma = MedicalCondition.objects.create(
            code='ASTHMA',
            label='Asthma',
            description='Respiratory condition'
        )
        
        self.wheelchair = AccessibilityRequirement.objects.create(
            code='WHEEL',
            label='Wheelchair Access',
            description='Requires wheelchair accessible facilities'
        )
        
    def test_full_booking_flow_with_family(self):
        """
        Test the complete booking flow:
        1. Create attendees
        2. Create family group
        3. Add personal info
        4. Create booking
        5. Apply packages with discounts
        6. Create payment
        7. Create tickets
        """
        
        # ===== STEP 1: Create Attendees =====
        # Create booking first (required for attendees)
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-FAM-001',
            made_by=self.sam
        )
        
        # Sam (19, event staff, registering himself)
        sam_attendee = Attendee.objects.create(
            first_name='Sam',
            last_name='Johnson',
            email='sam@example.com',
            date_of_birth=date(2006, 3, 15),  # 19 years old
            event=self.event,
            user=self.sam,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.sam
        )
        
        # Mum (45, single day only)
        mum_attendee = Attendee.objects.create(
            first_name='Jane',
            last_name='Johnson',
            email='jane@example.com',
            date_of_birth=date(1980, 5, 20),  # 45 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.OTHER,
            defined_by=self.sam
        )
        
        # Dad (48, single day only)
        dad_attendee = Attendee.objects.create(
            first_name='John',
            last_name='Johnson',
            email='john@example.com',
            date_of_birth=date(1977, 8, 10),  # 48 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.OTHER,
            defined_by=self.sam
        )
        
        # Brother (14, full event)
        brother_attendee = Attendee.objects.create(
            first_name='Tom',
            last_name='Johnson',
            date_of_birth=date(2011, 11, 5),  # 14 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.sam
        )
        
        # Sister (2, full event)
        sister_attendee = Attendee.objects.create(
            first_name='Emma',
            last_name='Johnson',
            date_of_birth=date(2023, 6, 25),  # 2 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.sam
        )
        
        self.assertEqual(booking.attendees.count(), 5)
        
        # ===== STEP 2: Create Family Group =====
        family = FamilyGroup.objects.create(
            family_name='Johnson Family',
            created_by=self.sam
        )
        
        # Link attendees to family
        FamilyAttendee.objects.create(
            family_group=family,
            attendee=sam_attendee,
            relationship=HumanRelationshipChoices.CHILD
        )
        
        FamilyAttendee.objects.create(
            family_group=family,
            attendee=mum_attendee,
            relationship=HumanRelationshipChoices.PARENT,
            is_primary_guardian=True
        )
        
        FamilyAttendee.objects.create(
            family_group=family,
            attendee=dad_attendee,
            relationship=HumanRelationshipChoices.PARENT
        )
        
        FamilyAttendee.objects.create(
            family_group=family,
            attendee=brother_attendee,
            relationship=HumanRelationshipChoices.SIBLING
        )
        
        FamilyAttendee.objects.create(
            family_group=family,
            attendee=sister_attendee,
            relationship=HumanRelationshipChoices.SIBLING
        )
        
        self.assertEqual(family.family_attendees.count(), 5)
        
        # ===== STEP 3: Add Personal Info =====
        # Brother has asthma
        AttendeeMedicalCondition.objects.create(
            attendee=brother_attendee,
            medical_condition=self.asthma,
            notes='Carries inhaler'
        )
        
        # Mum is vegetarian
        AttendeeDietaryRequirement.objects.create(
            attendee=mum_attendee,
            dietary_requirement=self.vegetarian
        )
        
        # Sister has gluten allergy
        AttendeeDietaryRequirement.objects.create(
            attendee=sister_attendee,
            dietary_requirement=self.gluten_free,
            notes='Severe allergy'
        )
        
        # Dad needs wheelchair access
        AttendeeAccessibilityRequirement.objects.create(
            attendee=dad_attendee,
            accessibility_requirement=self.wheelchair
        )
        
        # ===== STEP 4: Calculate Prices with Discounts =====
        # Create discounts linked to packages
        # 10% staff discount for early bird package
        staff_discount = Discount.objects.create(
            name='Event Staff Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.early_bird_package.id
        )
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Is Event Staff',
            discount=staff_discount,
            active=True
        )
        
        # 15% child discount for standard package
        child_discount = Discount.objects.create(
            name='Child Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.standard_package.id
        )
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 18',
            discount=child_discount,
            value='18',
            active=True
        )
        
        # Sam: Early bird £10, 10% staff discount = £9
        sam_context = sam_attendee.pricing_context()
        # Manually set event staff metadata for Sam
        sam_context.metadata['is_event_staff'] = True
        
        sam_price = self.early_bird_package.total_amount_for_context(sam_context)
        expected_sam_price = Money('9.00', 'GBP')  # £10 - 10% = £9
        self.assertEqual(sam_price, expected_sam_price)
        
        # Parents: Single day £12 each, no discount = £24 total
        mum_price = self.single_day_package.base_amount
        dad_price = self.single_day_package.base_amount
        self.assertEqual(mum_price, Money(12, 'GBP'))
        self.assertEqual(dad_price, Money(12, 'GBP'))
        
        # Brother: Standard £15, 15% child discount = £12.75
        brother_context = brother_attendee.pricing_context()
        brother_price = self.standard_package.total_amount_for_context(brother_context)
        expected_brother_price = Money('12.75', 'GBP')  # £15 - 15% = £12.75
        self.assertEqual(brother_price, expected_brother_price)
        
        # Sister: Standard £15, 15% child discount = £12.75
        sister_context = sister_attendee.pricing_context()
        sister_price = self.standard_package.total_amount_for_context(sister_context)
        expected_sister_price = Money('12.75', 'GBP')  # £15 - 15% = £12.75
        self.assertEqual(sister_price, expected_sister_price)
        
        # Total: £9 + £12 + £12 + £12.75 + £12.75 = £58.50
        total_amount = sam_price + mum_price + dad_price + brother_price + sister_price
        expected_total = Money('58.50', 'GBP')
        self.assertEqual(total_amount, expected_total)
        
        # ===== STEP 5: Create Payment =====
        payment = Payment.objects.create(
            user=self.sam,
            event=self.event,
            method=self.payment_method,
            base_amount=total_amount,
            percentage_modifier=Decimal('0.00'),
            description='Johnson Family - Youth Conference 2025',
            status=PaymentStatusChoices.PENDING,
            metadata={
                'booking_reference': booking.booking_reference,
                'attendee_count': 5,
                'breakdown': {
                    'sam': str(sam_price),
                    'mum': str(mum_price),
                    'dad': str(dad_price),
                    'brother': str(brother_price),
                    'sister': str(sister_price)
                }
            }
        )
        
        # Link payment to booking
        payment.target = booking
        payment.save()
        
        self.assertEqual(payment.base_amount, expected_total)
        self.assertEqual(payment.status, PaymentStatusChoices.PENDING)
        
        # ===== STEP 6: Simulate Successful Payment =====
        payment.status = PaymentStatusChoices.COMPLETED
        payment.stripe_payment_intent = 'pi_test_123456'
        payment.stripe_charge_id = 'ch_test_123456'
        payment.save()
        
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        
        # ===== STEP 7: Create Tickets =====
        # Sam gets full event ticket with early bird package
        sam_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            attendee=sam_attendee,
            package=self.early_bird_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
            uses=1
        )
        
        # Mum gets single day ticket
        mum_ticket = Ticket.objects.create(
            ticket_type=self.single_day_ticket,
            attendee=mum_attendee,
            package=self.single_day_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
            uses=1
        )
        
        # Dad gets single day ticket
        dad_ticket = Ticket.objects.create(
            ticket_type=self.single_day_ticket,
            attendee=dad_attendee,
            package=self.single_day_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
            uses=1
        )
        
        # Brother gets full event ticket with standard package
        brother_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            attendee=brother_attendee,
            package=self.standard_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
            uses=1
        )
        
        # Sister gets full event ticket with standard package
        sister_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            attendee=sister_attendee,
            package=self.standard_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
            uses=1
        )
        
        # ===== STEP 8: Verify Final State =====
        # Check all tickets created
        self.assertEqual(payment.tickets.count(), 5)
        self.assertEqual(Ticket.objects.filter(payment=payment).count(), 5)
        
        # Check ticket scopes
        self.assertEqual(sam_ticket.ticket_type.scope, TicketScopeChoices.FULL_EVENT)
        self.assertEqual(mum_ticket.ticket_type.scope, TicketScopeChoices.SINGLE_DAY)
        self.assertEqual(dad_ticket.ticket_type.scope, TicketScopeChoices.SINGLE_DAY)
        self.assertEqual(brother_ticket.ticket_type.scope, TicketScopeChoices.FULL_EVENT)
        self.assertEqual(sister_ticket.ticket_type.scope, TicketScopeChoices.FULL_EVENT)
        
        # Check all tickets are active
        for ticket in [sam_ticket, mum_ticket, dad_ticket, brother_ticket, sister_ticket]:
            self.assertEqual(ticket.status, TicketStatusChoices.ACTIVE)
            self.assertIsNotNone(ticket.ticket_code)
            self.assertEqual(ticket.payment, payment)
        
        # Check packages are correctly linked to tickets
        self.assertEqual(sam_ticket.package, self.early_bird_package)
        self.assertEqual(mum_ticket.package, self.single_day_package)
        self.assertEqual(dad_ticket.package, self.single_day_package)
        self.assertEqual(brother_ticket.package, self.standard_package)
        self.assertEqual(sister_ticket.package, self.standard_package)
        
        # Check booking relationship
        for ticket in payment.tickets.all():
            self.assertEqual(ticket.booking, booking)
        
        # Check personal info was saved
        self.assertEqual(brother_attendee.medical_conditions.count(), 1)
        self.assertEqual(mum_attendee.dietary_requirements.count(), 1)
        self.assertEqual(sister_attendee.dietary_requirements.count(), 1)
        self.assertEqual(dad_attendee.accessibility_requirements.count(), 1)
        
        # ===== Summary Assertions =====
        self.assertEqual(booking.attendees.count(), 5)
        self.assertEqual(family.family_attendees.count(), 5)
        self.assertEqual(payment.base_amount, Money('58.50', 'GBP'))
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(payment.tickets.count(), 5)
        
    def test_payment_status_transitions(self):
        """Test that payment status transitions are validated"""
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-STATUS-001',
            made_by=self.sam
        )
        
        payment = Payment.objects.create(
            user=self.sam,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.DRAFTING
        )
        
        # DRAFTING -> PENDING is allowed
        payment.status = PaymentStatusChoices.PENDING
        payment.save()  # Should not raise
        
        # PENDING -> COMPLETED is allowed
        payment.status = PaymentStatusChoices.COMPLETED
        payment.save()  # Should not raise
        
        # COMPLETED -> PENDING_REFUND is allowed
        payment.status = PaymentStatusChoices.PENDING_REFUND
        payment.save()  # Should not raise
        
        # PENDING_REFUND -> REFUNDED is allowed
        payment.status = PaymentStatusChoices.REFUNDED
        payment.save()  # Should not raise
        
    def test_payment_linked_to_booking(self):
        """Test that payment can be linked to a booking via GenericForeignKey"""
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-LINK-001',
            made_by=self.sam
        )
        
        payment = Payment.objects.create(
            user=self.sam,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(50, 'GBP'),
            status=PaymentStatusChoices.PENDING
        )
        
        # Link payment to booking
        payment.target = booking
        payment.save()
        
        # Verify link
        self.assertEqual(payment.target, booking)
        self.assertEqual(payment.target_type, ContentType.objects.get_for_model(Booking))
        self.assertEqual(payment.target_id, booking.id)
        
    def test_tickets_use_correct_pricing(self):
        """Test that each ticket reflects the correct pricing from packages"""
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-PRICE-001',
            made_by=self.sam
        )
        
        # Adult paying full price
        adult = Attendee.objects.create(
            first_name='Adult',
            last_name='User',
            date_of_birth=date(1990, 1, 1),
            event=self.event,
            user=self.sam,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.sam
        )
        
        # Child with discount
        child = Attendee.objects.create(
            first_name='Child',
            last_name='User',
            date_of_birth=date(2015, 1, 1),  # 10 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.sam
        )
        
        # Create child discount linked to standard package
        child_discount = Discount.objects.create(
            name='Child Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.standard_package.id
        )
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 18',
            discount=child_discount,
            value='18',
            active=True
        )
        
        # Calculate prices
        adult_context = adult.pricing_context()
        adult_price = self.standard_package.total_amount_for_context(adult_context)
        
        child_context = child.pricing_context()
        child_price = self.standard_package.total_amount_for_context(child_context)
        
        # Adult pays full £15
        self.assertEqual(adult_price, Money(15, 'GBP'))
        
        # Child pays £15 - 15% = £12.75
        self.assertEqual(child_price, Money('12.75', 'GBP'))
        
        # Total payment
        total = adult_price + child_price
        self.assertEqual(total, Money('27.75', 'GBP'))
