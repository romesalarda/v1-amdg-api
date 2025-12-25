from django.test import TestCase
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from apps.payments.models import Discount, DiscountRule, DiscountRuleTypeChoices, DiscountType
from apps.payments.evaluator import DiscountRuleEvaluator, DiscountContext, discount_applies
from apps.users.models import CommunityUser
from apps.events.models import Event, EventType


class DiscountRuleEvaluatorTestCase(TestCase):
    """
    Test suite for DiscountRuleEvaluator to verify all discount rule types
    are correctly evaluated.
    """

    def setUp(self):
        """Set up test data for discount rule evaluation tests."""
        # Create test user
        self.user = CommunityUser.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        # Create test event type and event
        self.event_type = EventType.objects.create(
            title='Test Conference',
            code='TESTC'
        )
        
        start_time = timezone.now() + timedelta(days=30)
        end_time = start_time + timedelta(days=2)
        
        self.event = Event.objects.create(
            title='Annual Test Conference',
            event_type=self.event_type,
            created_by=self.user,
            display_code='TC2026',
            display_identifier='TC2026-TEST',
            start_datetime=start_time,
            end_datetime=end_time
        )
        
        # Create a dummy discount target (we'll use Event as the target)
        content_type = ContentType.objects.get_for_model(Event)
        self.discount = Discount.objects.create(
            name='Test Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            target_type=content_type,
            target_id=self.event.id,
            active=True
        )
        
        self.evaluator = DiscountRuleEvaluator()

    def test_is_event_staff_true(self):
        """Test IS_EVENT_STAFF rule returns True when user is event staff."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Event Staff Discount',
            discount=self.discount
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"is_event_staff": True}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_is_event_staff_false(self):
        """Test IS_EVENT_STAFF rule returns False when user is not event staff."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Event Staff Discount',
            discount=self.discount
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"is_event_staff": False}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_is_event_staff_no_user(self):
        """Test IS_EVENT_STAFF rule returns False when no user is provided."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Event Staff Discount',
            discount=self.discount
        )
        
        context = DiscountContext(
            user=None,
            event=self.event,
            metadata={"is_event_staff": True}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_is_age_lt_true(self):
        """Test IS_AGE_LT rule returns True when age is less than threshold."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Youth Discount',
            discount=self.discount,
            value='18'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 15}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_is_age_lt_false(self):
        """Test IS_AGE_LT rule returns False when age is greater than or equal to threshold."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Youth Discount',
            discount=self.discount,
            value='18'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 20}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_is_age_lt_no_age(self):
        """Test IS_AGE_LT rule returns False when age is not provided."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Youth Discount',
            discount=self.discount,
            value='18'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_is_age_gt_true(self):
        """Test IS_AGE_GT rule returns True when age is greater than threshold."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Senior Discount',
            discount=self.discount,
            value='65'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 70}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_is_age_gt_false(self):
        """Test IS_AGE_GT rule returns False when age is less than or equal to threshold."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Senior Discount',
            discount=self.discount,
            value='65'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 60}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_value_matches_true(self):
        """Test VALUE_MATCHES rule returns True when value matches code."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.VALUE_MATCHES,
            name='Promo Code Discount',
            discount=self.discount,
            value='SUMMER2026'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"code": "SUMMER2026"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_value_matches_false(self):
        """Test VALUE_MATCHES rule returns False when value doesn't match code."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.VALUE_MATCHES,
            name='Promo Code Discount',
            discount=self.discount,
            value='SUMMER2026'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"code": "WINTER2026"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_organisation_matches_true(self):
        """Test ORGANISATION_MATCHES rule returns True when organisation is in list."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.ORGANISATION_MATCHES,
            name='Organisation Discount',
            discount=self.discount,
            value='ORG-123'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"organisations": ["ORG-123", "ORG-456"]}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_organisation_matches_false(self):
        """Test ORGANISATION_MATCHES rule returns False when organisation is not in list."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.ORGANISATION_MATCHES,
            name='Organisation Discount',
            discount=self.discount,
            value='ORG-999'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"organisations": ["ORG-123", "ORG-456"]}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_staff_role_matches_true(self):
        """Test EVENT_STAFF_ROLE_MATCHES rule returns True when role matches."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES,
            name='Volunteer Discount',
            discount=self.discount,
            value='Volunteer'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"staff_roles": ["Volunteer", "Coordinator"]}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_staff_role_matches_false(self):
        """Test EVENT_STAFF_ROLE_MATCHES rule returns False when role doesn't match."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES,
            name='Speaker Discount',
            discount=self.discount,
            value='Speaker'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"staff_roles": ["Volunteer", "Coordinator"]}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_staff_role_matches_no_roles(self):
        """Test EVENT_STAFF_ROLE_MATCHES rule returns False when no roles provided."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES,
            name='Volunteer Discount',
            discount=self.discount,
            value='Volunteer'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_name_matches_true_exact(self):
        """Test NAME_MATCHES rule returns True when name matches exactly."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.NAME_MATCHES,
            name='Named Discount',
            discount=self.discount,
            value='John Doe'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"full_name": "John Doe"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_name_matches_true_partial(self):
        """Test NAME_MATCHES rule returns True when name partially matches."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.NAME_MATCHES,
            name='Named Discount',
            discount=self.discount,
            value='John'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"full_name": "John Doe Smith"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_name_matches_case_insensitive(self):
        """Test NAME_MATCHES rule is case-insensitive."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.NAME_MATCHES,
            name='Named Discount',
            discount=self.discount,
            value='JOHN DOE'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"full_name": "john doe"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_name_matches_false(self):
        """Test NAME_MATCHES rule returns False when name doesn't match."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.NAME_MATCHES,
            name='Named Discount',
            discount=self.discount,
            value='Jane Smith'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"full_name": "John Doe"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)

    def test_location_matches_true(self):
        """Test LOCATION_MATCHES rule returns True when location matches."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.LOCATION_MATCHES,
            name='London Discount',
            discount=self.discount,
            value='London'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"location": "London"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_location_matches_case_insensitive(self):
        """Test LOCATION_MATCHES rule is case-insensitive."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.LOCATION_MATCHES,
            name='London Discount',
            discount=self.discount,
            value='LONDON'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"location": "london"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertTrue(result)

    def test_location_matches_false(self):
        """Test LOCATION_MATCHES rule returns False when location doesn't match."""
        rule = DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.LOCATION_MATCHES,
            name='London Discount',
            discount=self.discount,
            value='London'
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"location": "Manchester"}
        )
        
        result = self.evaluator.evaluate(rule, context)
        self.assertFalse(result)


class DiscountAppliesTestCase(TestCase):
    """
    Test suite for the discount_applies function to verify
    that discounts are correctly applied when all rules are satisfied.
    """

    def setUp(self):
        """Set up test data for discount application tests."""
        self.user = CommunityUser.objects.create_user(
            username='testuser2',
            email='testuser2@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Test Conference 2',
            code='TESTC'
        )
        
        start_time = timezone.now() + timedelta(days=60)
        end_time = start_time + timedelta(days=3)
        
        self.event = Event.objects.create(
            title='Annual Test Conference 2',
            event_type=self.event_type,
            created_by=self.user,
            display_code='TC2027',
            display_identifier='TC2027-TEST',
            start_datetime=start_time,
            end_datetime=end_time
        )
        
        content_type = ContentType.objects.get_for_model(Event)
        self.discount = Discount.objects.create(
            name='Multi-Rule Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            target_type=content_type,
            target_id=self.event.id,
            active=True
        )

    def test_discount_applies_no_rules(self):
        """Test discount applies when there are no rules."""
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={}
        )
        
        result = discount_applies(self.discount, context)
        self.assertTrue(result)

    def test_discount_applies_single_rule_passes(self):
        """Test discount applies when single rule passes."""
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Only',
            discount=self.discount,
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"is_event_staff": True}
        )
        
        result = discount_applies(self.discount, context)
        self.assertTrue(result)

    def test_discount_applies_single_rule_fails(self):
        """Test discount doesn't apply when single rule fails."""
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Only',
            discount=self.discount,
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"is_event_staff": False}
        )
        
        result = discount_applies(self.discount, context)
        self.assertFalse(result)

    def test_discount_applies_multiple_rules_all_pass(self):
        """Test discount applies when all multiple rules pass."""
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Only',
            discount=self.discount,
            active=True
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Age Greater Than 18',
            discount=self.discount,
            value='18',
            active=True
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.LOCATION_MATCHES,
            name='London Only',
            discount=self.discount,
            value='London',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "is_event_staff": True,
                "age": 25,
                "location": "London"
            }
        )
        
        result = discount_applies(self.discount, context)
        self.assertTrue(result)

    def test_discount_applies_multiple_rules_one_fails(self):
        """Test discount doesn't apply when one of multiple rules fails."""
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Only',
            discount=self.discount,
            active=True
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Age Greater Than 18',
            discount=self.discount,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "is_event_staff": True,
                "age": 15  # Fails age requirement
            }
        )
        
        result = discount_applies(self.discount, context)
        self.assertFalse(result)

    def test_discount_applies_ignores_inactive_rules(self):
        """Test discount evaluation ignores inactive rules."""
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Only',
            discount=self.discount,
            active=True
        )
        # Inactive rule that would fail
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Age Greater Than 100',
            discount=self.discount,
            value='100',
            active=False
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "is_event_staff": True,
                "age": 25
            }
        )
        
        result = discount_applies(self.discount, context)
        self.assertTrue(result)

    def test_discount_applies_complex_scenario(self):
        """Test discount application with a complex multi-rule scenario."""
        # Create multiple rules combining different conditions
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.ORGANISATION_MATCHES,
            name='Correct Organisation',
            discount=self.discount,
            value='ORG-123',
            active=True
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.VALUE_MATCHES,
            name='Promo Code',
            discount=self.discount,
            value='EARLYBIRD',
            active=True
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Youth Discount',
            discount=self.discount,
            value='30',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={
                "organisations": ["ORG-123", "ORG-456"],
                "code": "EARLYBIRD",
                "age": 22
            }
        )
        
        result = discount_applies(self.discount, context)
        self.assertTrue(result)
