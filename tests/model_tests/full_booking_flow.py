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

        self.organisation = Organisation.objects.create(
            title='Youth Events Org',
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
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
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
            relationship_to_user=AttendeeRelationship.PARENT,
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
            relationship_to_user=AttendeeRelationship.PARENT,
            defined_by=self.sam
        )
        
        # Brother (14, full event)
        brother_attendee = Attendee.objects.create(
            first_name='Tom',
            last_name='Johnson',
            date_of_birth=date(2011, 11, 5),  # 14 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SIBLING,
            defined_by=self.sam
        )
        
        # Sister (2, full event)
        sister_attendee = Attendee.objects.create(
            first_name='Emma',
            last_name='Johnson',
            date_of_birth=date(2023, 6, 25),  # 2 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SIBLING,
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
        sam_context.metadata['is_event_staff'] = True # TODO: use staff object
        
        sam_price = self.early_bird_package.total_amount_for_context(sam_context)
        
        ###########################
        # TODO: Here is where we would add orders if there is merchandise etc.
        


        ###########################

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
        
        # ===== STEP 5: Create Payment with Proper Metadata =====
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
                'booking_id': str(booking.id),
                'payment_type': 'booking_tickets',
                'attendee_count': 5,
                'attendee_breakdown': {
                    'sam': {
                        'attendee_id': str(sam_attendee.attendee_id),
                        'attendee_name': sam_attendee.full_name,
                        'package': self.early_bird_package.name,
                        'amount': str(sam_price.amount),
                        'currency': sam_price.currency.code
                    },
                    'mum': {
                        'attendee_id': str(mum_attendee.attendee_id),
                        'attendee_name': mum_attendee.full_name,
                        'package': self.single_day_package.name,
                        'amount': str(mum_price.amount),
                        'currency': mum_price.currency.code
                    },
                    'dad': {
                        'attendee_id': str(dad_attendee.attendee_id),
                        'attendee_name': dad_attendee.full_name,
                        'package': self.single_day_package.name,
                        'amount': str(dad_price.amount),
                        'currency': dad_price.currency.code
                    },
                    'brother': {
                        'attendee_id': str(brother_attendee.attendee_id),
                        'attendee_name': brother_attendee.full_name,
                        'package': self.standard_package.name,
                        'amount': str(brother_price.amount),
                        'currency': brother_price.currency.code
                    },
                    'sister': {
                        'attendee_id': str(sister_attendee.attendee_id),
                        'attendee_name': sister_attendee.full_name,
                        'package': self.standard_package.name,
                        'amount': str(sister_price.amount),
                        'currency': sister_price.currency.code
                    }
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
        
    def test_full_booking_flow_with_package_products(self):
        """
        Test the complete booking flow with products bundled in packages, including variant selection.
        
        Scenario: Sarah (25, student) is registering for a conference with her younger brother Mark (16).
        - The Standard Package includes registration + Conference T-Shirt (users select size/color)
        - Registration base: £30
        - T-Shirt base: £20
        - Package base: £45 (£5 bundled discount on combined registration + product)
        - Sarah chooses: Medium Blue t-shirt (0% modifier) -> gets 10% student discount on package
        - Mark chooses: Small Red t-shirt (+10% premium) -> gets 15% youth discount on package
        
        Calculation breakdown:
        Sarah: 
          - Package base: £45
          - T-shirt variant modifier: 0% -> £20 * 1.0 = £20
          - Package total with product: £45 + £0 = £45
          - 10% student discount: £45 * 0.9 = £40.50
        
        Mark:
          - Package base: £45
          - T-shirt variant modifier: +10% -> £20 * 1.1 = £22
          - Package total with product: £45 + £2 = £47
          - 15% youth discount: £47 * 0.85 = £39.95
        
        Total: £80.45
        """
        from apps.bookings.models import PackageProduct
        from apps.products.models import Product, ProductVariant, ProductSizeChoices
        from apps.bookings.models import PackageProduct
        from apps.products.models import Product, ProductVariant, ProductSizeChoices
        
        # ===== STEP 1: Create Products with Variants =====
        # Conference T-Shirt product
        tshirt_product = Product.objects.create(
            title='Conference T-Shirt 2025',
            description='Official conference merchandise',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Create variants for the t-shirt (different sizes and colors with modifiers)
        # Blue Medium - standard price (0% modifier)
        variant_blue_medium = ProductVariant.objects.create(
            product=tshirt_product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',  # Blue
            percentage_modifier=Decimal('0.00'),  # No price change
            stock_quantity=50,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Red Small - premium color (+10% modifier)
        variant_red_small = ProductVariant.objects.create(
            product=tshirt_product,
            size=ProductSizeChoices.SMALL,
            color='#FF0000',  # Red
            percentage_modifier=Decimal('10.00'),  # +10% premium
            stock_quantity=30,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Green Large - bulk discount (-5% modifier)
        variant_green_large = ProductVariant.objects.create(
            product=tshirt_product,
            size=ProductSizeChoices.LARGE,
            color='#00FF00',  # Green
            percentage_modifier=Decimal('-5.00'),  # -5% discount
            stock_quantity=40,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # ===== STEP 2: Create Package with Bundled Product =====
        # Standard package: base amount £30 for registration
        # Product will be added separately so user can choose variant
        standard_package_with_product = BookingPackage.objects.create(
            name='Standard Package with T-Shirt',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(30, 'GBP'),  # Registration base price
            created_by=self.sam
        )
        
        # Link the product to the package (not variant - user chooses variant at booking time)
        package_product = PackageProduct.objects.create(
            booking_package=standard_package_with_product,
            product=tshirt_product,
            quantity_per_attendee=1,
            percentage_modifier=Decimal('-25.00'),  # -25% discount when bought with package
            added_by=self.sam
        )
        
        # Verify PackageProduct base_amount is set correctly (product price * quantity)
        self.assertEqual(package_product.base_amount, Money(20, 'GBP'))
        # Verify PackageProduct base_amount is set correctly (product price * quantity)
        self.assertEqual(package_product.base_amount, Money(20, 'GBP'))
        
        # ===== STEP 3: Create Student Discount (applies to package) =====
        student_discount = Discount.objects.create(
            name='Student Discount 10%',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=standard_package_with_product.id
        )
        
        # Student discount: 18-25 years old (need both age rules)
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 26',
            discount=student_discount,
            value='26',
            active=True
        )
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 17',
            discount=student_discount,
            value='17',
            active=True
        )
        
        # ===== STEP 4: Create Youth Discount (applies to package) =====
        youth_discount = Discount.objects.create(
            name='Youth Discount 15%',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=standard_package_with_product.id
        )
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 18',
            discount=youth_discount,
            value='18',
            active=True
        )
        
        # ===== STEP 5: Create Booking and Attendees =====
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-PKG-VAR-001',
            made_by=self.sam
        )

        # Keep this test deterministic across calendar years by forcing Sarah to be 25.
        today = timezone.now().date()
        sarah_dob = date(today.year - 25, today.month, max(1, today.day - 1))
        
        # Sarah (25, student) - will choose blue medium variant, gets 10% discount
        sarah = Attendee.objects.create(
            first_name='Sarah',
            last_name='Williams',
            email='sarah@example.com',
            date_of_birth=sarah_dob,
            event=self.event,
            user=self.sam,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.sam
        )
        
        # Mark (16) - will choose red small variant (premium), gets 15% youth discount
        mark = Attendee.objects.create(
            first_name='Mark',
            last_name='Williams',
            date_of_birth=date(2009, 7, 15),  # 16 years old (born July 2009, it's Jan 2026)
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SIBLING,
            defined_by=self.sam
        )
        
        self.assertEqual(booking.attendees.count(), 2)
        
        # ===== STEP 6: Calculate Package Base Price =====
        # Package base (registration): £30
        self.assertEqual(standard_package_with_product.base_amount, Money(30, 'GBP'))
        
        # ===== STEP 7: Calculate Total with Variants for Each Attendee =====
        sarah_context = sarah.pricing_context()
        mark_context = mark.pricing_context()
        
        # Sarah chooses blue medium (0% modifier)
        sarah_variant_cost = package_product.total_amount_with_variant(
            variant=variant_blue_medium,
            context=sarah_context
        )
        # Base: £20 * 1.0 (0% modifier) * 0.75 (-25% package discount) = £15
        self.assertEqual(sarah_variant_cost, Money('15.00', 'GBP'))
        
        # Sarah's total: Package base £30 + Variant cost £15 = £45
        # Apply 10% student discount: £45 * 0.9 = £40.50
        sarah_package_price = standard_package_with_product.total_amount_for_context(sarah_context)
        sarah_total = sarah_package_price + sarah_variant_cost #! out of method important calculation
        # Package base: £30
        # Package discount (10%): £30 * 0.9 = £27.00
        sarah_package_price = standard_package_with_product.total_amount_for_context(sarah_context)
        self.assertEqual(sarah_package_price, Money('27.00', 'GBP'))
        
        # Product with variant and package discount:
        # £20 (base) * 1.0 (variant 0%) * 0.75 (package -25%) = £15
        sarah_total = sarah_package_price + sarah_variant_cost
        self.assertEqual(sarah_total, Money('42.00', 'GBP'))
        
        # Mark chooses red small (+10% premium)
        mark_variant_cost = package_product.total_amount_with_variant(
            variant=variant_red_small,
            context=mark_context
        )
        # Base: £20 * 1.1 (10% modifier) * 0.75 (-25% package discount) = £16.50
        self.assertEqual(mark_variant_cost, Money('16.50', 'GBP'))
        
        # Mark's total: Package base £30 with 15% discount = £25.50 TODO: was adding multiple discounts together
        mark_package_price = standard_package_with_product.total_amount_for_context(mark_context)
        self.assertEqual(mark_package_price, Money('25.50', 'GBP'))
        
        # Mark total: £25.50 + £16.50 = £42.00
        mark_total = mark_package_price + mark_variant_cost
        self.assertEqual(mark_total, Money('42.00', 'GBP'))
        # Mark total: £25.50 + £16.50 = £42.00
        mark_total = mark_package_price + mark_variant_cost
        self.assertEqual(mark_total, Money('42.00', 'GBP'))
        
        # ===== STEP 8: Verify Package Product Association =====
        associated_products = standard_package_with_product.associated_products
        self.assertEqual(associated_products.count(), 1)
        self.assertEqual(associated_products.first().product, tshirt_product)
        self.assertEqual(associated_products.first().quantity_per_attendee, 1)
        
        # ===== STEP 9: Verify Variants Are Available =====
        available_variants = tshirt_product.variants.filter(is_active=True)
        self.assertEqual(available_variants.count(), 3)
        self.assertIn(variant_blue_medium, available_variants)
        self.assertIn(variant_red_small, available_variants)
        self.assertIn(variant_green_large, available_variants)
        
        # ===== STEP 10: Create Payment with Frozen Metadata =====
        total_amount = sarah_total + mark_total
        self.assertEqual(total_amount, Money('84.00', 'GBP'))
        
        payment = Payment.objects.create(
            user=self.sam,
            event=self.event,
            method=self.payment_method,
            base_amount=total_amount,
            status=PaymentStatusChoices.PENDING,
            target_id=booking.id,
            target_type=ContentType.objects.get_for_model(Booking),
            metadata={
                'booking_reference': booking.booking_reference,
                'booking_id': str(booking.id),
                'payment_type': 'booking_tickets',
                'attendee_count': 2,
                'attendee_breakdown': {
                    'sarah': {
                        'attendee_id': str(sarah.attendee_id),
                        'attendee_name': sarah.full_name,
                        'package': standard_package_with_product.name,
                        'amount': str(sarah_total.amount),
                        'currency': sarah_total.currency.code,
                        'package_amount': str(sarah_package_price.amount),
                        'product_variant_amount': str(sarah_variant_cost.amount),
                        'variant': 'Medium Blue'
                    },
                    'mark': {
                        'attendee_id': str(mark.attendee_id),
                        'attendee_name': mark.full_name,
                        'package': standard_package_with_product.name,
                        'amount': str(mark_total.amount),
                        'currency': mark_total.currency.code,
                        'package_amount': str(mark_package_price.amount),
                        'product_variant_amount': str(mark_variant_cost.amount),
                        'variant': 'Small Red'
                    }
                }
            }
        )
        
        # Link payment to booking
        # booking.payments.add(payment)
        
        # ===== STEP 11: Create Tickets with Package and Variant Information =====
        sarah_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            ticket_code=f'TICKET-{sarah.attendee_display_id}',
            attendee=sarah,
            package=standard_package_with_product,
            payment=payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        mark_ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            ticket_code=f'TICKET-{mark.attendee_display_id}',
            attendee=mark,
            package=standard_package_with_product,
            payment=payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        # ===== STEP 12: Verify Complete Flow =====
        # Verify tickets are linked to payment
        self.assertEqual(payment.tickets.count(), 2)
        self.assertIn(sarah_ticket, payment.tickets.all())
        self.assertIn(mark_ticket, payment.tickets.all())
        
        # Verify each ticket has the correct package
        self.assertEqual(sarah_ticket.package, standard_package_with_product)
        self.assertEqual(mark_ticket.package, standard_package_with_product)
        
        # Verify payment amount matches calculated totals
        self.assertEqual(payment.base_amount, total_amount)
        
        # Verify booking has correct attendees and payment
        self.assertEqual(booking.attendees.count(), 2)
        self.assertEqual(booking.payments.first(), payment)
        
        # ===== STEP 13: Verify Variant Stock Not Affected Yet =====
        # Stock shouldn't be decremented until order is processed
        variant_blue_medium.refresh_from_db()
        variant_red_small.refresh_from_db()
        self.assertEqual(variant_blue_medium.stock_quantity, 50)
        self.assertEqual(variant_red_small.stock_quantity, 30)
        
        # ===== STEP 14: Verify Savings Calculation =====
        # Without package discount:
        # Sarah: Registration £30 + T-shirt £20 = £50, with 10% discount = £45
        # Mark: Registration £30 + T-shirt £22 (premium) = £52, with 15% discount = £44.20
        # Total without package: £89.20
        # With package: £84.00
        # Savings: £5.20
        without_package_sarah = Money(50, 'GBP') * Decimal('0.9')  # £45.00
        without_package_mark = Money(52, 'GBP') * Decimal('0.85')  # £44.20
        without_package_total = without_package_sarah + without_package_mark
        savings = without_package_total - total_amount
        self.assertEqual(savings, Money('5.20', 'GBP'))
        
    def test_full_booking_flow_with_package_products_no_discounts(self):
        """
        Test booking flow with package products and variants but NO attendee-based discounts.
        
        Scenario: An organization bulk-books for 3 employees (all adults, no student/youth status)
        - Professional Package includes registration + Conference Bag (users select size)
        - Registration base: £50
        - Bag base: £15
        - Package includes bag at 10% discount when bundled
        - Employee 1 chooses One Size bag (0% modifier)
        - Employee 2 chooses Large bag (+5% premium)
        - Employee 3 chooses One Size bag (0% modifier)
        - No attendee-specific discounts apply (all are adult employees)
        """
        from apps.bookings.models import PackageProduct
        from apps.products.models import Product, ProductVariant, ProductSizeChoices
        
        # ===== STEP 1: Create Product with Variants =====
        conference_bag = Product.objects.create(
            title='Conference Bag',
            description='Professional conference bag',
            event=self.event,
            base_amount=Money(15, 'GBP'),
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # One Size variant - standard
        variant_onesize = ProductVariant.objects.create(
            product=conference_bag,
            size=ProductSizeChoices.ONE_SIZE,
            color='#000000',  # Black
            percentage_modifier=Decimal('0.00'),
            stock_quantity=100,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Large variant - premium (+5%)
        variant_large = ProductVariant.objects.create(
            product=conference_bag,
            size=ProductSizeChoices.LARGE,
            color='#000000',  # Black
            percentage_modifier=Decimal('5.00'),  # +5% premium for large size
            stock_quantity=50,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # ===== STEP 2: Create Package with Bundled Product (No Discounts) =====
        employee_package = BookingPackage.objects.create(
            name='Professional Package',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(50, 'GBP'),  # Registration only
            created_by=self.sam
        )
        
        # Link product to package with 10% bundle discount
        package_product = PackageProduct.objects.create(
            booking_package=employee_package,
            product=conference_bag,
            quantity_per_attendee=1,
            percentage_modifier=Decimal('-10.00'),  # -10% when bundled
            added_by=self.sam
        )
        
        self.assertEqual(package_product.base_amount, Money(15, 'GBP'))
        
        # ===== STEP 3: Create Booking and Adult Attendees =====
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-EMP-VAR-001',
            made_by=self.sam
        )
        
        # Employee 1 - chooses One Size
        employee1 = Attendee.objects.create(
            first_name='Alice',
            last_name='Johnson',
            email='alice@company.com',
            date_of_birth=date(1985, 5, 10),  # 39 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.OTHER,
            defined_by=self.sam
        )
        
        # Employee 2 - chooses Large (premium)
        employee2 = Attendee.objects.create(
            first_name='Bob',
            last_name='Smith',
            email='bob@company.com',
            date_of_birth=date(1990, 8, 22),  # 34 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.OTHER,
            defined_by=self.sam
        )
        
        # Employee 3 - chooses One Size
        employee3 = Attendee.objects.create(
            first_name='Carol',
            last_name='Davis',
            email='carol@company.com',
            date_of_birth=date(1978, 12, 5),  # 46 years old
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.OTHER,
            defined_by=self.sam
        )
        
        self.assertEqual(booking.attendees.count(), 3)
        
        # ===== STEP 4: Calculate Package Prices with Variants (No Attendee Discounts) =====
        emp1_context = employee1.pricing_context()
        emp2_context = employee2.pricing_context()
        emp3_context = employee3.pricing_context()
        
        # Package base price (registration) - no discounts
        emp1_package_price = employee_package.total_amount_for_context(emp1_context)
        emp2_package_price = employee_package.total_amount_for_context(emp2_context)
        emp3_package_price = employee_package.total_amount_for_context(emp3_context)
        
        # All pay £50 for registration (no attendee discounts)
        self.assertEqual(emp1_package_price, Money(50, 'GBP'))
        self.assertEqual(emp2_package_price, Money(50, 'GBP'))
        self.assertEqual(emp3_package_price, Money(50, 'GBP'))
        
        # Calculate variant costs with package discount
        # Employee 1: One Size (0% modifier)
        # £15 * 1.0 * 0.9 (10% package discount) = £13.50
        emp1_variant_cost = package_product.total_amount_with_variant(
            variant=variant_onesize,
            context=emp1_context
        )
        self.assertEqual(emp1_variant_cost, Money('13.50', 'GBP'))
        
        # Employee 2: Large (+5% modifier)
        # £15 * 1.05 * 0.9 (10% package discount) = £14.175 -> rounds to £14.18
        emp2_variant_cost = package_product.total_amount_with_variant(
            variant=variant_large,
            context=emp2_context
        )
        self.assertEqual(emp2_variant_cost, Money('14.18', 'GBP'))
        
        # Employee 3: One Size (0% modifier)
        emp3_variant_cost = package_product.total_amount_with_variant(
            variant=variant_onesize,
            context=emp3_context
        )
        self.assertEqual(emp3_variant_cost, Money('13.50', 'GBP'))
        
        # Calculate totals
        emp1_total = emp1_package_price + emp1_variant_cost  # £50 + £13.50 = £63.50
        emp2_total = emp2_package_price + emp2_variant_cost  # £50 + £14.18 = £64.18
        emp3_total = emp3_package_price + emp3_variant_cost  # £50 + £13.50 = £63.50
        
        self.assertEqual(emp1_total, Money('63.50', 'GBP'))
        self.assertEqual(emp2_total, Money('64.18', 'GBP'))
        self.assertEqual(emp3_total, Money('63.50', 'GBP'))
        
        # ===== STEP 5: Verify Package Product Details =====
        self.assertEqual(package_product.quantity_per_attendee, 1)
        self.assertEqual(package_product.percentage_modifier, Decimal('-10.00'))
        
        # ===== STEP 6: Create Payment with Frozen Metadata =====
        total_amount = emp1_total + emp2_total + emp3_total
        self.assertEqual(total_amount, Money('191.18', 'GBP'))
        
        payment = Payment.objects.create(
            user=self.sam,
            event=self.event,
            method=self.payment_method,
            base_amount=total_amount,
            status=PaymentStatusChoices.PENDING,
            metadata={
                'booking_reference': booking.booking_reference,
                'booking_id': str(booking.id),
                'payment_type': 'booking_tickets',
                'attendee_count': 3,
                'attendee_breakdown': {
                    'employee1': {
                        'attendee_id': str(employee1.attendee_id),
                        'attendee_name': employee1.full_name,
                        'package': employee_package.name,
                        'amount': str(emp1_total.amount),
                        'currency': emp1_total.currency.code
                    },
                    'employee2': {
                        'attendee_id': str(employee2.attendee_id),
                        'attendee_name': employee2.full_name,
                        'package': employee_package.name,
                        'amount': str(emp2_total.amount),
                        'currency': emp2_total.currency.code
                    },
                    'employee3': {
                        'attendee_id': str(employee3.attendee_id),
                        'attendee_name': employee3.full_name,
                        'package': employee_package.name,
                        'amount': str(emp3_total.amount),
                        'currency': emp3_total.currency.code
                    }
                }
            }
        )
        
        booking.add_payment(payment)
        
        # ===== STEP 7: Create Tickets =====
        ticket1 = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            ticket_code=f'TICKET-{employee1.attendee_display_id}',
            attendee=employee1,
            package=employee_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        ticket2 = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            ticket_code=f'TICKET-{employee2.attendee_display_id}',
            attendee=employee2,
            package=employee_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        ticket3 = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            ticket_code=f'TICKET-{employee3.attendee_display_id}',
            attendee=employee3,
            package=employee_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        # ===== STEP 8: Verify Complete Flow =====
        # Verify all tickets created
        self.assertEqual(payment.tickets.count(), 3)
        
        # Verify payment is linked to booking
        self.assertEqual(booking.payments.first(), payment)
        
        # Verify payment amount is correct
        self.assertEqual(payment.base_amount, Money('191.18', 'GBP'))
        
        # Verify each attendee has exactly one ticket
        self.assertEqual(employee1.tickets.count(), 1)
        self.assertEqual(employee2.tickets.count(), 1)
        self.assertEqual(employee3.tickets.count(), 1)
        
        # ===== STEP 9: Verify Variant Stock Not Affected =====
        variant_onesize.refresh_from_db()
        variant_large.refresh_from_db()
        self.assertEqual(variant_onesize.stock_quantity, 100)
        self.assertEqual(variant_large.stock_quantity, 50)
        
        # ===== STEP 10: Verify Bundle Savings =====
        # Without bundle discount on bags:
        # Employee 1: £50 + £15 = £65
        # Employee 2: £50 + £15.75 (large premium) = £65.75
        # Employee 3: £50 + £15 = £65
        # Total without bundle: £195.75
        # With bundle: £191.18
        # Savings: £4.57
        without_bundle = Money(65, 'GBP') + Money('65.75', 'GBP') + Money(65, 'GBP')
        self.assertEqual(without_bundle, Money('195.75', 'GBP'))
        savings = without_bundle - total_amount
        self.assertEqual(savings, Money('4.57', 'GBP'))
        
    def test_package_products_with_multiple_products(self):
        """
        Test a package that includes multiple different products with variants.
        
        Scenario: VIP Package includes Registration + T-Shirt + Mug + Bag (all with variant choices)
        - Tests that multiple PackageProducts can be associated with one package
        - Verifies each product's pricing with different variants and quantities
        - T-Shirt: user selects size/color (1 per attendee)
        - Mug: standard color, quantity 2 per attendee
        - Bag: user selects size (1 per attendee)
        """
        from apps.bookings.models import PackageProduct
        from apps.products.models import Product, ProductVariant, ProductSizeChoices
        
        # ===== STEP 1: Create Multiple Products with Variants =====
        # Product 1: T-Shirt
        tshirt = Product.objects.create(
            title='VIP T-Shirt',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        tshirt_medium_blue = ProductVariant.objects.create(
            product=tshirt,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            percentage_modifier=Decimal('0.00'),
            stock_quantity=100,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        tshirt_large_red = ProductVariant.objects.create(
            product=tshirt,
            size=ProductSizeChoices.LARGE,
            color='#FF0000',
            percentage_modifier=Decimal('8.00'),  # Premium color +8%
            stock_quantity=50,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Product 2: Mug
        mug = Product.objects.create(
            title='VIP Mug',
            event=self.event,
            base_amount=Money(10, 'GBP'),
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        mug_onesize = ProductVariant.objects.create(
            product=mug,
            size=ProductSizeChoices.ONE_SIZE,
            color='#FFFFFF',
            percentage_modifier=Decimal('0.00'),
            stock_quantity=200,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Product 3: Bag
        bag = Product.objects.create(
            title='VIP Bag',
            event=self.event,
            base_amount=Money(30, 'GBP'),
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        bag_standard = ProductVariant.objects.create(
            product=bag,
            size=ProductSizeChoices.MEDIUM,
            color='#000000',
            percentage_modifier=Decimal('0.00'),
            stock_quantity=80,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        bag_large = ProductVariant.objects.create(
            product=bag,
            size=ProductSizeChoices.LARGE,
            color='#000000',
            percentage_modifier=Decimal('10.00'),  # Large size +10%
            stock_quantity=40,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # ===== STEP 2: Create VIP Package =====
        # Registration £50 + Products (with bundle savings)
        vip_package = BookingPackage.objects.create(
            name='VIP All-Inclusive Package',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(50, 'GBP'),  # Registration base
            created_by=self.sam
        )
        
        # ===== STEP 3: Link Multiple Products to Package =====
        pp_tshirt = PackageProduct.objects.create(
            booking_package=vip_package,
            product=tshirt,
            quantity_per_attendee=1,
            percentage_modifier=Decimal('-20.00'),  # -20% bundle discount
            added_by=self.sam
        )
        
        pp_mug = PackageProduct.objects.create(
            booking_package=vip_package,
            product=mug,
            quantity_per_attendee=2,  # 2 mugs per attendee
            percentage_modifier=Decimal('-15.00'),  # -15% bundle discount
            added_by=self.sam
        )
        
        pp_bag = PackageProduct.objects.create(
            booking_package=vip_package,
            product=bag,
            quantity_per_attendee=1,
            percentage_modifier=Decimal('-10.00'),  # -10% bundle discount
            added_by=self.sam
        )
        
        # ===== STEP 4: Verify Package Products Base Amounts =====
        associated_products = vip_package.associated_products
        self.assertEqual(associated_products.count(), 3)
        
        # Verify base amounts are calculated correctly (product base price, not multiplied by quantity)
        self.assertEqual(pp_tshirt.base_amount, Money(25, 'GBP'))  # £25
        self.assertEqual(pp_mug.base_amount, Money(10, 'GBP'))     # £10 per mug (quantity handled separately)
        self.assertEqual(pp_bag.base_amount, Money(30, 'GBP'))     # £30
        
        # ===== STEP 5: Create Booking with VIP Attendee =====
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-VIP-MULTI-001',
            made_by=self.sam
        )
        
        vip_attendee = Attendee.objects.create(
            first_name='Victoria',
            last_name='VIP',
            email='vip@example.com',
            date_of_birth=date(1985, 4, 12),
            event=self.event,
            user=self.sam,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.sam
        )
        
        # ===== STEP 6: Calculate Package and Product Costs with Variants =====
        vip_context = vip_attendee.pricing_context()
        
        # Package base price (registration)
        vip_package_price = vip_package.total_amount_for_context(vip_context)
        self.assertEqual(vip_package_price, Money(50, 'GBP'))
        
        # VIP chooses: Medium Blue T-shirt (0% modifier)
        # £25 * 1.0 * 0.8 (-20% package discount) = £20.00
        tshirt_cost = pp_tshirt.total_amount_with_variant(
            variant=tshirt_medium_blue,
            context=vip_context
        )
        self.assertEqual(tshirt_cost, Money('20.00', 'GBP'))
        
        # Mugs: One Size (0% modifier), quantity 2
        # £10 * 1.0 * 0.85 (-15% package discount) = £8.50 per mug
        # £8.50 * 2 mugs = £17.00
        mug_cost_per_unit = pp_mug.total_amount_with_variant(
            variant=mug_onesize,
            context=vip_context
        )
        self.assertEqual(mug_cost_per_unit, Money('8.50', 'GBP'))
        # Use Money constructor to ensure proper 2 decimal place rounding
        mug_cost = Money(mug_cost_per_unit.amount * pp_mug.quantity_per_attendee, 'GBP')
        self.assertEqual(mug_cost, Money('17.00', 'GBP'))
        
        # VIP chooses: Large Bag (+10% premium)
        # £30 * 1.1 * 0.9 (-10% package discount) = £29.70
        bag_cost = pp_bag.total_amount_with_variant(
            variant=bag_large,
            context=vip_context
        )
        self.assertEqual(bag_cost, Money('29.70', 'GBP'))
        
        # Total: £50 + £20 + £17 + £29.70 = £116.70
        vip_total = vip_package_price + tshirt_cost + mug_cost + bag_cost
        vip_total = Money(vip_total.amount, 'GBP')  # Ensure proper Money type
        self.assertEqual(vip_total, Money('116.70', 'GBP'))
        
        # ===== STEP 7: Create Payment with Frozen Metadata =====
        payment = Payment.objects.create(
            user=self.sam,
            event=self.event,
            method=self.payment_method,
            base_amount=vip_total,
            status=PaymentStatusChoices.COMPLETED,
            metadata={
                'booking_reference': booking.booking_reference,
                'booking_id': str(booking.id),
                'payment_type': 'booking_tickets',
                'attendee_count': 1,
                'attendee_breakdown': {
                    'vip': {
                        'attendee_id': str(vip_attendee.attendee_id),
                        'attendee_name': vip_attendee.full_name,
                        'package': vip_package.name,
                        'amount': str(vip_total.amount),
                        'currency': vip_total.currency.code,
                        'breakdown': {
                            'package_base': str(vip_package_price.amount),
                            'tshirt': str(tshirt_cost.amount),
                            'mugs': str(mug_cost.amount),
                            'bag': str(bag_cost.amount)
                        }
                    }
                }
            }
        )
        
        booking.add_payment(payment)
        
        ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            ticket_code=f'TICKET-{vip_attendee.attendee_display_id}',
            attendee=vip_attendee,
            package=vip_package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE
        )
        
        # ===== STEP 8: Verify Complete Flow =====
        self.assertEqual(payment.tickets.count(), 1)
        self.assertEqual(ticket.package, vip_package)
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        self.assertEqual(payment.base_amount, Money('116.70', 'GBP'))
        
        # ===== STEP 9: Verify Savings =====
        # Without package discounts:
        # Registration: £50
        # T-shirt (medium blue): £25 * 1.0 = £25
        # Mugs (2): £10 * 2 = £20
        # Bag (large): £30 * 1.1 = £33
        # Total without discounts: £128
        # With package discounts: £116.70
        # Savings: £11.30
        without_discounts = Money(50, 'GBP') + Money(25, 'GBP') + Money(20, 'GBP') + Money(33, 'GBP')
        self.assertEqual(without_discounts, Money(128, 'GBP'))
        savings = without_discounts - vip_total
        self.assertEqual(savings, Money('11.30', 'GBP'))
        
        # ===== STEP 10: Verify Stock Not Affected =====
        tshirt_medium_blue.refresh_from_db()
        mug_onesize.refresh_from_db()
        bag_large.refresh_from_db()
        self.assertEqual(tshirt_medium_blue.stock_quantity, 100)
        self.assertEqual(mug_onesize.stock_quantity, 200)
        self.assertEqual(bag_large.stock_quantity, 40)
