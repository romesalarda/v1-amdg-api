"""
Tests for booking package discounts in isolation.
Tests the PayableModel.calculate_total_discounts method and discount evaluation logic.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money

from apps.bookings.models import BookingPackage, BookingPackageRule, PackageRuleTypeChoices, TicketType, TicketScopeChoices
from apps.payments.models import Discount, DiscountType, DiscountRule, DiscountRuleTypeChoices
from apps.payments.services.evaluator import DiscountContext
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.organisations.models import Organisation

User = get_user_model()


class PayableModelDiscountCalculationTest(TestCase):
    """
    Test the calculate_total_discounts method on PayableModel (via BookingPackage).
    This tests the core discount calculation logic that was previously untested.
    """
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='discountuser',
            email='discount@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Test Event Type',
            code='TEST',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.user    
        )
        
        self.event = Event.objects.create(
            title='Discount Test Event',
            display_code='DTE001',
            display_identifier='DTE001TEST001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='STD',
            title='Standard',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
        
        # Create a booking package (which inherits from PayableModel)
        self.package = BookingPackage.objects.create(
            name='Test Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            percentage_modifier=Decimal('0.00'),
            created_by=self.user
        )
        
    def test_calculate_total_discounts_no_discounts(self):
        """Test that calculate_total_discounts returns zero when no discounts exist"""
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        discount = self.package.calculate_total_discounts(
            discount_base=self.package.base_amount,
            context=context
        )
        
        self.assertEqual(discount, Money(0, 'GBP'))
        
    def test_calculate_total_discounts_percentage_discount(self):
        """Test percentage discount calculation"""
        # Create 10% discount
        discount_obj = Discount.objects.create(
            name='10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(discount_obj)
        
        # Add a rule that always passes
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount_obj,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        discount = self.package.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        self.assertEqual(discount, Money(10, 'GBP'))
        
    def test_calculate_total_discounts_fixed_amount_discount(self):
        """Test fixed amount discount calculation"""
        # Create £15 off discount
        discount_obj = Discount.objects.create(
            name='£15 Off',
            discount_type=DiscountType.FIXED,
            amount=Money(15, 'GBP'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(discount_obj)
        
        # Add a rule that always passes
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount_obj,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        discount = self.package.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        self.assertEqual(discount, Money(15, 'GBP'))
        
    def test_calculate_total_discounts_multiple_percentage_discounts(self):
        """Test that multiple percentage discounts are added together"""
        # Create 10% discount for event staff
        staff_discount = Discount.objects.create(
            name='Staff 10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(staff_discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Is Staff',
            discount=staff_discount,
            active=True
        )
        
        # Create 15% discount for youth
        youth_discount = Discount.objects.create(
            name='Youth 15% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(youth_discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 18',
            discount=youth_discount,
            value='18',
            active=True
        )
        
        # Context: 16-year-old event staff member
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "age": 16,
                "is_event_staff": True
            }
        )
        
        discount = self.package.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        # Should be 10% + 15% = 25% of £100 = £25
        self.assertEqual(discount, Money(25, 'GBP'))
        
    def test_calculate_total_discounts_mixed_percentage_and_fixed(self):
        """Test combining percentage and fixed discounts"""
        # Create 10% discount
        percentage_discount = Discount.objects.create(
            name='10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(percentage_discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=percentage_discount,
            value='18',
            active=True
        )
        
        # Create £5 fixed discount
        fixed_discount = Discount.objects.create(
            name='£5 Off',
            discount_type=DiscountType.FIXED,
            amount=Money(5, 'GBP'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(fixed_discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Is Staff',
            discount=fixed_discount,
            active=True
        )
        
        # Context: 25-year-old event staff
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "age": 25,
                "is_event_staff": True
            }
        )
        
        discount = self.package.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        # Should be 10% of £100 (£10) + £5 = £15
        self.assertEqual(discount, Money(15, 'GBP'))
        
    def test_calculate_total_discounts_capped_at_base_amount(self):
        """Test that total discount cannot exceed the base amount"""
        # Create 80% discount
        large_percentage = Discount.objects.create(
            name='80% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('80.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(large_percentage)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=large_percentage,
            value='18',
            active=True
        )
        
        # Create £30 fixed discount
        large_fixed = Discount.objects.create(
            name='£30 Off',
            discount_type=DiscountType.FIXED,
            amount=Money(30, 'GBP'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(large_fixed)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Is Staff',
            discount=large_fixed,
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "age": 25,
                "is_event_staff": True
            }
        )
        
        # Base amount is £100, discounts would be £80 + £30 = £110
        # But should be capped at £100
        discount = self.package.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        self.assertEqual(discount, Money(100, 'GBP'))
        
    def test_calculate_total_discounts_inactive_discount_ignored(self):
        """Test that inactive discounts are not applied"""
        # Create active discount
        active_discount = Discount.objects.create(
            name='Active 10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(active_discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=active_discount,
            value='18',
            active=True
        )
        
        # Create inactive discount
        inactive_discount = Discount.objects.create(
            name='Inactive 15% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            active=False,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(inactive_discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Is Staff',
            discount=inactive_discount,
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "age": 25,
                "is_event_staff": True
            }
        )
        
        discount = self.package.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        # Only active discount should be applied (10%)
        self.assertEqual(discount, Money(10, 'GBP'))
        
    def test_calculate_total_discounts_rule_does_not_apply(self):
        """Test that discounts are not applied when rules don't match"""
        # Create discount with rule that won't match
        discount_obj = Discount.objects.create(
            name='Youth 15% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(discount_obj)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 18',
            discount=discount_obj,
            value='18',
            active=True
        )
        
        # Context: 25-year-old (does not meet age < 18 rule)
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        discount = self.package.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        self.assertEqual(discount, Money(0, 'GBP'))
        
    def test_total_amount_for_context_with_discounts(self):
        """Test total_amount_for_context method which uses calculate_total_discounts"""
        # Create 20% discount
        discount_obj = Discount.objects.create(
            name='20% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('20.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id
        )
        self.package.add_discount(discount_obj)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount_obj,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        # Base amount is £100, 20% discount = £20, so total should be £80
        total = self.package.total_amount_for_context(context)
        
        self.assertEqual(total, Money(80, 'GBP'))
        
    def test_total_amount_for_context_with_percentage_modifier(self):
        """Test total_amount_for_context with both percentage modifier and discounts"""
        # Package with 10% markup
        package_with_markup = BookingPackage.objects.create(
            name='Premium Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            percentage_modifier=Decimal('10.00'),  # +10% markup
            created_by=self.user
        )
        
        # Create 15% discount
        discount_obj = Discount.objects.create(
            name='15% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=package_with_markup.id
        )
        package_with_markup.add_discount(discount_obj)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount_obj,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        # Base £100 + 10% markup = £110
        # 15% discount on £110 = £16.50
        # Total = £110 - £16.50 = £93.50
        total = package_with_markup.total_amount_for_context(context)
        
        self.assertEqual(total, Money('93.50', 'GBP'))
