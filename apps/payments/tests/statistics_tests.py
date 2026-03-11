"""
Payment Statistics Tests

Comprehensive test suite for payment statistics functionality testing:
- Core statistics calculation functions
- API endpoints with raw and ECharts formats
- Event filtering capabilities
- Superuser permissions for global statistics
- Soft-delete handling (only affects Order model, not Payment)
- Revenue calculations with COMPLETED-only logic
- Edge cases and data accuracy
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status as http_status
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money

from apps.payments.models.payments import Payment, PaymentStatusChoices
from apps.payments.models.methods import PaymentMethod, PaymentMethodTypeChoices
from apps.payments.models.discounts import Discount, DiscountType, DiscountRule, DiscountRuleTypeChoices
from apps.payments.models.refunds import RefundRequest
from apps.payments.models.donations import Donation
from apps.payments import statistics
from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.products.models.orders import Order, OrderStatusChoices

User = get_user_model()


class PaymentStatisticsBaseTestCase(TestCase):
    """Base test case with comprehensive setup for payment statistics tests."""
    
    def setUp(self):
        """Set up comprehensive test data for statistics testing."""
        self.client = APIClient()
        
        # ==================== STEP 1: Create Users ====================
        self.regular_user = User.objects.create_user(
            username='regularuser',
            email='regular@example.com',
            password='testpass123',
            first_name='Regular',
            last_name='User'
        )
        
        self.admin_user = User.objects.create_user(
            username='adminuser',
            email='admin@example.com',
            password='testpass123',
            first_name='Admin',
            last_name='User',
            is_superuser=True,
            is_staff=True
        )
        
        self.donor_user = User.objects.create_user(
            username='donor',
            email='donor@example.com',
            password='testpass123',
            first_name='Generous',
            last_name='Donor'
        )
        
        # ==================== STEP 2: Create Organizations ====================
        self.org1 = Organisation.objects.create(
            title='Test Organization 1',
            created_by=self.admin_user
        )
        
        self.org2 = Organisation.objects.create(
            title='Test Organization 2',
            created_by=self.admin_user
        )
        
        # ==================== STEP 3: Create Event Type ====================
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF'
        )
        
        # ==================== STEP 4: Create Events ====================
        start_time1 = timezone.now() + timedelta(days=30)
        self.event1 = Event.objects.create(
            title='Test Event 1',
            event_type=self.event_type,
            created_by=self.admin_user,
            display_code='TE1-2026',
            display_identifier='TE1-2026-TEST',
            start_datetime=start_time1,
            end_datetime=start_time1 + timedelta(days=2),
            organisation=self.org1,
            status=EventStatusChoices.PUBLISHED
        )
        
        start_time2 = timezone.now() + timedelta(days=60)
        self.event2 = Event.objects.create(
            title='Test Event 2',
            event_type=self.event_type,
            created_by=self.admin_user,
            display_code='TE2-2026',
            display_identifier='TE2-2026-TEST',
            start_datetime=start_time2,
            end_datetime=start_time2 + timedelta(days=3),
            organisation=self.org2,
            status=EventStatusChoices.PUBLISHED
        )
        
        start_time3 = timezone.now() + timedelta(days=90)
        self.event3 = Event.objects.create(
            title='Test Event 3',
            event_type=self.event_type,
            created_by=self.admin_user,
            display_code='TE3-2026',
            display_identifier='TE3-2026-TEST',
            start_datetime=start_time3,
            end_datetime=start_time3 + timedelta(days=1),
            organisation=self.org1,
            status=EventStatusChoices.DRAFTING
        )
        
        # ==================== STEP 5: Create Payment Methods ====================
        self.method_stripe_event1 = PaymentMethod.objects.create(
            code='PYM-STRIPE-E1',
            title='Stripe Payment (Event 1)',
            event=self.event1,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True,
            created_by=self.admin_user
        )
        
        self.method_bank_event1 = PaymentMethod.objects.create(
            code='PYM-BANK-E1',
            title='Bank Transfer (Event 1)',
            event=self.event1,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            is_active=True,
            created_by=self.admin_user
        )
        
        self.method_stripe_event2 = PaymentMethod.objects.create(
            code='PYM-STRIPE-E2',
            title='Stripe Payment (Event 2)',
            event=self.event2,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True,
            created_by=self.admin_user
        )
        
        # ==================== STEP 6: Create Attendees ====================
        self.attendee1 = Attendee.objects.create(
            event=self.event1,
            user=self.regular_user,
            first_name='Test',
            last_name='Attendee 1',
            email='attendee1@example.com',
            relationship_to_user=AttendeeRelationship.SELF,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.attendee2 = Attendee.objects.create(
            event=self.event1,
            user=self.regular_user,
            first_name='Test',
            last_name='Attendee 2',
            email='attendee2@example.com',
            relationship_to_user=AttendeeRelationship.CHILD,
            date_of_birth=date(2010, 1, 1)
        )
        
        self.attendee3 = Attendee.objects.create(
            event=self.event2,
            user=self.regular_user,
            first_name='Test',
            last_name='Attendee 3',
            email='attendee3@example.com',
            relationship_to_user=AttendeeRelationship.SELF,
            date_of_birth=date(1985, 1, 1)
        )
        
        # ==================== STEP 7: Create Discounts ====================
        event1_ct = ContentType.objects.get_for_model(Event)
        
        self.discount1 = Discount.objects.create(
            name='Early Bird Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('15.00'),
            target_type=event1_ct,
            target_id=self.event1.id,
            active=True,
            created_by=self.admin_user
        )
        
        self.discount2 = Discount.objects.create(
            name='Fixed Amount Discount',
            discount_type=DiscountType.FIXED,
            amount=Money(10, 'GBP'),
            target_type=event1_ct,
            target_id=self.event1.id,
            active=True,
            created_by=self.admin_user
        )
        
        self.discount3 = Discount.objects.create(
            name='Event 2 Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            target_type=event1_ct,
            target_id=self.event2.id,
            active=True,
            created_by=self.admin_user
        )
        
        # ==================== STEP 8: Create Discount Rules ====================
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Rule',
            discount=self.discount1,
            active=True
        )
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            name='Code Rule',
            discount=self.discount1,
            value='EARLYBIRD',
            active=True
        )
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Youth Rule',
            discount=self.discount2,
            value='18',
            active=True
        )
        
        # ==================== STEP 9: Create Payments with Various Statuses ====================
        # Event 1 - Completed payments
        for i in range(5):
            self._create_payment(
                user=self.regular_user,
                event=self.event1,
                status=PaymentStatusChoices.COMPLETED,
                amount=100.00 + (i * 10),
                method=self.method_stripe_event1,
                created_days_ago=10 + i
            )
        
        # Event 1 - Bank transfer completed payments
        for i in range(3):
            self._create_payment(
                user=self.regular_user,
                event=self.event1,
                status=PaymentStatusChoices.COMPLETED,
                amount=150.00,
                method=self.method_bank_event1,
                created_days_ago=5 + i
            )
        
        # Event 1 - Pending payments (should NOT count toward revenue)
        for i in range(2):
            self._create_payment(
                user=self.regular_user,
                event=self.event1,
                status=PaymentStatusChoices.PENDING,
                amount=200.00,
                method=self.method_stripe_event1,
                created_days_ago=3 + i
            )
        
        # Event 1 - Failed payments (should NOT count toward revenue)
        self._create_payment(
            user=self.regular_user,
            event=self.event1,
            status=PaymentStatusChoices.FAILED,
            amount=50.00,
            method=self.method_stripe_event1,
            created_days_ago=1
        )
        
        # Event 1 - Refunded payments
        self._create_payment(
            user=self.regular_user,
            event=self.event1,
            status=PaymentStatusChoices.REFUNDED,
            amount=100.00,
            method=self.method_stripe_event1,
            created_days_ago=2
        )
        
        # Event 2 - Completed payments
        for i in range(4):
            self._create_payment(
                user=self.regular_user,
                event=self.event2,
                status=PaymentStatusChoices.COMPLETED,
                amount=80.00 + (i * 5),
                method=self.method_stripe_event2,
                created_days_ago=7 + i
            )
        
        # Event 2 - Cancelled payment (should NOT count toward revenue)
        self._create_payment(
            user=self.regular_user,
            event=self.event2,
            status=PaymentStatusChoices.CANCELLED,
            amount=75.00,
            method=self.method_stripe_event2,
            created_days_ago=4
        )
        
        # ==================== STEP 10: Create Refund Requests ====================
        refunded_payment = Payment.objects.filter(
            status=PaymentStatusChoices.REFUNDED,
            event=self.event1
        ).first()
        
        if refunded_payment:
            self.refund_request1 = RefundRequest.objects.create(
                tracking_reference='REF-001',
                payment=refunded_payment,
                amount=Money(100, 'GBP'),
                reason='Customer requested refund',
                requested_by=self.regular_user,
                processed_at=timezone.now() - timedelta(days=1),
            )
        
        # Create pending refund request
        completed_payment = Payment.objects.filter(
            status=PaymentStatusChoices.COMPLETED,
            event=self.event1
        ).first()
        
        if completed_payment:
            self.refund_request2 = RefundRequest.objects.create(
                tracking_reference='REF-002',
                payment=completed_payment,
                amount=Money(50, 'GBP'),
                reason='Partial refund requested',
                requested_by=self.regular_user,
            )
        
        # ==================== STEP 11: Create Donations ====================
        # Link donations to payments
        donation_payment1 = self._create_payment(
            user=self.donor_user,
            event=self.event1,
            status=PaymentStatusChoices.COMPLETED,
            amount=250.00,
            method=self.method_stripe_event1,
            created_days_ago=15
        )
        
        self.donation1 = Donation.objects.create(
            tracking_reference='DON-001',
            amount=Money(250, 'GBP'),
            donated_by=self.donor_user,
            payment=donation_payment1,
        )
        
        donation_payment2 = self._create_payment(
            user=self.donor_user,
            event=self.event1,
            status=PaymentStatusChoices.COMPLETED,
            amount=100.00,
            method=self.method_stripe_event1,
            created_days_ago=10
        )
        
        self.donation2 = Donation.objects.create(
            tracking_reference='DON-002',
            amount=Money(100, 'GBP'),
            donated_by=self.donor_user,
            payment=donation_payment2,
        )
        
        donation_payment3 = self._create_payment(
            user=self.donor_user,
            event=self.event2,
            status=PaymentStatusChoices.COMPLETED,
            amount=500.00,
            method=self.method_stripe_event2,
            created_days_ago=5
        )
        
        self.donation3 = Donation.objects.create(
            tracking_reference='DON-003',
            amount=Money(500, 'GBP'),
            donated_by=self.donor_user,
            payment=donation_payment3,
        )
        
        # ==================== STEP 12: Create Orders (for soft-delete testing) ====================
        self.order1 = Order.objects.create(
            customer=self.regular_user,
            attendee=self.attendee1,
            status=OrderStatusChoices.COMPLETED,
            total_amount=Money(150, 'GBP'),
            created_by=self.regular_user
        )
        
        self.order2 = Order.objects.create(
            customer=self.regular_user,
            attendee=self.attendee2,
            status=OrderStatusChoices.COMPLETED,
            total_amount=Money(200, 'GBP'),
            created_by=self.regular_user,
        )
    
    def _create_payment(self, user, event, status, amount, method=None, created_days_ago=0):
        """
        Helper method to create a payment with specified parameters.
        
        Args:
            user: User who made the payment
            event: Event the payment is for
            status: Payment status
            amount: Payment amount (float)
            method: PaymentMethod (optional)
            created_days_ago: How many days ago the payment was created
        
        Returns:
            Created Payment object
        """
        payment = Payment.objects.create(
            payment_reference=f'PAY-{Payment.objects.count() + 1:06d}',
            user=user,
            event=event,
            status=status,
            base_amount=Money(amount, 'GBP'),
            method=method,
            description=f'Payment for {event.title}'
        )
        
        if created_days_ago > 0:
            # Backdate the payment
            payment.created_at = timezone.now() - timedelta(days=created_days_ago)
            payment.save(update_fields=['created_at'])
        
        return payment


# ============================================================================
# PAYMENT STATISTICS TESTS
# ============================================================================

class PaymentStatusDistributionTests(PaymentStatisticsBaseTestCase):
    """Tests for payment status distribution statistics."""
    
    def test_basic_status_distribution(self):
        """Test basic status distribution calculation."""
        result = statistics.calculate_payment_status_distribution()
        
        self.assertIn('total', result)
        self.assertIn('distribution', result)
        self.assertGreater(result['total'], 0)
        self.assertGreater(len(result['distribution']), 0)
    
    def test_status_distribution_with_event_filter(self):
        """Test status distribution filtered by event."""
        result = statistics.calculate_payment_status_distribution(event_id=str(self.event1.id))
        
        # Count event1 payments
        event1_payment_count = Payment.objects.filter(event=self.event1).count()
        self.assertEqual(result['total'], event1_payment_count)
    
    def test_status_distribution_percentages(self):
        """Test that percentages sum to approximately 100."""
        result = statistics.calculate_payment_status_distribution(event_id=str(self.event1.id))
        
        total_percentage = sum(item['percentage'] for item in result['distribution'])
        self.assertAlmostEqual(total_percentage, 100.0, places=1)
    
    def test_status_distribution_has_all_statuses(self):
        """Test that distribution includes all present statuses."""
        result = statistics.calculate_payment_status_distribution(event_id=str(self.event1.id))
        
        statuses_in_result = {item['status_code'] for item in result['distribution']}
        statuses_in_db = set(
            Payment.objects.filter(event=self.event1).values_list('status', flat=True).distinct()
        )
        
        self.assertEqual(statuses_in_result, statuses_in_db)


class PaymentMethodDistributionTests(PaymentStatisticsBaseTestCase):
    """Tests for payment method distribution statistics."""
    
    def test_basic_method_distribution(self):
        """Test basic method distribution calculation."""
        result = statistics.calculate_payment_method_distribution()
        
        self.assertIn('total', result)
        self.assertIn('distribution', result)
        self.assertGreater(result['total'], 0)
    
    def test_method_distribution_with_event_filter(self):
        """Test method distribution filtered by event."""
        result = statistics.calculate_payment_method_distribution(event_id=str(self.event1.id))
        
        event1_payment_count = Payment.objects.filter(event=self.event1).count()
        self.assertEqual(result['total'], event1_payment_count)
    
    def test_method_distribution_counts_without_method(self):
        """Test that payments without method are counted."""
        result = statistics.calculate_payment_method_distribution()
        
        self.assertIn('total_without_method', result)


class PaymentTrendsTests(PaymentStatisticsBaseTestCase):
    """Tests for payment trends statistics."""
    
    def test_basic_trends(self):
        """Test basic payment trends."""
        result = statistics.calculate_payment_trends()
        
        self.assertIn('trends', result)
        self.assertIn('total', result)
        self.assertGreater(len(result['trends']), 0)
    
    def test_trends_grouping_day(self):
        """Test trends with day grouping."""
        result = statistics.calculate_payment_trends(group_by='day')
        
        self.assertIn('trends', result)
        # Should have multiple days
        self.assertGreater(len(result['trends']), 0)
    
    def test_trends_grouping_week(self):
        """Test trends with week grouping."""
        result = statistics.calculate_payment_trends(group_by='week')
        
        self.assertIn('trends', result)
    
    def test_trends_grouping_month(self):
        """Test trends with month grouping."""
        result = statistics.calculate_payment_trends(group_by='month')
        
        self.assertIn('trends', result)
    
    def test_trends_with_event_filter(self):
        """Test trends filtered by event."""
        result = statistics.calculate_payment_trends(event_id=str(self.event1.id))
        
        total_count = sum(item['count'] for item in result['trends'])
        event1_payments = Payment.objects.filter(event=self.event1).count()
        self.assertEqual(total_count, event1_payments)
    
    def test_trends_with_date_filter(self):
        """Test trends with date range filtering."""
        date_from = date.today() - timedelta(days=7)
        date_to = date.today()
        
        result = statistics.calculate_payment_trends(
            date_from=date_from,
            date_to=date_to
        )
        
        self.assertIn('trends', result)


class PaymentOverviewTests(PaymentStatisticsBaseTestCase):
    """Tests for payment overview statistics."""
    
    def test_basic_overview(self):
        """Test basic payment overview."""
        result = statistics.calculate_payment_overview()
        
        self.assertIn('total_payments', result)
        self.assertIn('total_amount', result)
        self.assertIn('average_amount', result)
        self.assertIn('status_breakdown', result)
    
    def test_overview_with_event_filter(self):
        """Test overview filtered by event."""
        result = statistics.calculate_payment_overview(event_id=str(self.event1.id))
        
        event1_payments = Payment.objects.filter(event=self.event1).count()
        self.assertEqual(result['total_payments'], event1_payments)
    
    def test_overview_status_breakdown(self):
        """Test that status breakdown contains all statuses."""
        result = statistics.calculate_payment_overview()
        
        self.assertIn('status_breakdown', result)
        self.assertIsInstance(result['status_breakdown'], dict)


# ============================================================================
# DISCOUNT STATISTICS TESTS
# ============================================================================

class DiscountUsageTests(PaymentStatisticsBaseTestCase):
    """Tests for discount usage statistics."""
    
    def test_basic_discount_usage(self):
        """Test basic discount usage calculation."""
        result = statistics.calculate_discount_usage()
        
        self.assertIn('total_discounts', result)
        self.assertIn('type_distribution', result)
    
    def test_discount_usage_with_event_filter(self):
        """Test discount usage filtered by event."""
        result = statistics.calculate_discount_usage(event_id=str(self.event1.id))
        
        event1_ct = ContentType.objects.get_for_model(Event)
        event1_discounts = Discount.objects.filter(
            target_type=event1_ct,
            target_id=self.event1.id,
            active=True
        ).count()
        
        self.assertEqual(result['total_discounts'], event1_discounts)
    
    def test_discount_type_distribution(self):
        """Test discount type distribution."""
        result = statistics.calculate_discount_usage()
        
        distribution = result['type_distribution']
        self.assertGreater(len(distribution), 0)
        
        # Check that each type has required fields
        for item in distribution:
            self.assertIn('label', item)
            self.assertIn('value', item)
            self.assertIn('percentage', item)


class DiscountRuleEffectivenessTests(PaymentStatisticsBaseTestCase):
    """Tests for discount rule effectiveness statistics."""
    
    def test_basic_rule_effectiveness(self):
        """Test basic rule effectiveness calculation."""
        result = statistics.calculate_discount_rule_effectiveness()
        
        self.assertIn('total_rules', result)
        self.assertIn('rules', result)
    
    def test_rule_effectiveness_with_event_filter(self):
        """Test rule effectiveness filtered by event."""
        result = statistics.calculate_discount_rule_effectiveness(event_id=str(self.event1.id))
        
        # Count rules for event1 discounts
        event1_ct = ContentType.objects.get_for_model(Event)
        event1_rules = DiscountRule.objects.filter(
            discount__target_type=event1_ct,
            discount__target_id=self.event1.id,
            discount__active=True,
            active=True
        ).count()
        
        self.assertEqual(result['total_rules'], event1_rules)


class TopDiscountsTests(PaymentStatisticsBaseTestCase):
    """Tests for top discounts statistics."""
    
    def test_basic_top_discounts(self):
        """Test basic top discounts calculation."""
        result = statistics.calculate_top_discounts(limit=5)
        
        self.assertIn('discounts', result)
        self.assertIn('limit', result)
        self.assertEqual(result['limit'], 5)
    
    def test_top_discounts_respects_limit(self):
        """Test that top discounts respects limit parameter."""
        result = statistics.calculate_top_discounts(limit=2)
        
        self.assertLessEqual(len(result['discounts']), 2)


# ============================================================================
# REFUND STATISTICS TESTS
# ============================================================================

class RefundRequestStatsTests(PaymentStatisticsBaseTestCase):
    """Tests for refund request statistics."""
    
    def test_basic_refund_stats(self):
        """Test basic refund request statistics."""
        result = statistics.calculate_refund_request_stats()
        
        self.assertIn('total_requests', result)
        self.assertIn('total_amount', result)
        self.assertIn('status_distribution', result)
    
    def test_refund_stats_with_event_filter(self):
        """Test refund stats filtered by event."""
        result = statistics.calculate_refund_request_stats(event_id=str(self.event1.id))
        
        event1_refunds = RefundRequest.objects.filter(
            payment__event=self.event1
        ).count()
        
        self.assertEqual(result['total_requests'], event1_refunds)


class RefundTrendsTests(PaymentStatisticsBaseTestCase):
    """Tests for refund trends statistics."""
    
    def test_basic_refund_trends(self):
        """Test basic refund trends."""
        result = statistics.calculate_refund_trends()
        
        self.assertIn('trends', result)
        self.assertIn('total_count', result)
        self.assertIn('total_amount', result)
    
    def test_refund_trends_grouping(self):
        """Test refund trends with different groupings."""
        for group_by in ['day', 'week', 'month']:
            result = statistics.calculate_refund_trends(group_by=group_by)
            self.assertIn('trends', result)


class RefundProcessingTimesTests(PaymentStatisticsBaseTestCase):
    """Tests for refund processing time statistics."""
    
    def test_basic_processing_times(self):
        """Test basic processing time calculation."""
        result = statistics.calculate_refund_processing_times()
        
        self.assertIn('total_processed', result)
        self.assertIn('average_days', result)
    
    def test_processing_times_with_no_processed_refunds(self):
        """Test processing times when no refunds are processed."""
        # Delete all processed refunds
        RefundRequest.objects.filter(processed_at__isnull=False).delete()
        
        result = statistics.calculate_refund_processing_times()
        
        self.assertEqual(result['total_processed'], 0)
        self.assertIsNone(result['average_days'])


# ============================================================================
# DONATION STATISTICS TESTS
# ============================================================================

class DonationStatsTests(PaymentStatisticsBaseTestCase):
    """Tests for donation statistics."""
    
    def test_basic_donation_stats(self):
        """Test basic donation statistics."""
        result = statistics.calculate_donation_stats()
        
        self.assertIn('total_donations', result)
        self.assertIn('total_amount', result)
        self.assertIn('average_amount', result)
        self.assertIn('status_distribution', result)
    
    def test_donation_stats_with_event_filter(self):
        """Test donation stats filtered by event."""
        result = statistics.calculate_donation_stats(event_id=str(self.event1.id))
        
        event1_donations = Donation.objects.filter(
            payment__event=self.event1
        ).count()
        
        self.assertEqual(result['total_donations'], event1_donations)


class DonationTrendsTests(PaymentStatisticsBaseTestCase):
    """Tests for donation trends statistics."""
    
    def test_basic_donation_trends(self):
        """Test basic donation trends."""
        result = statistics.calculate_donation_trends()
        
        self.assertIn('trends', result)
        self.assertIn('total_count', result)
        self.assertIn('total_amount', result)


class TopDonorsTests(PaymentStatisticsBaseTestCase):
    """Tests for top donors statistics."""
    
    def test_basic_top_donors(self):
        """Test basic top donors calculation."""
        result = statistics.calculate_top_donors(limit=5)
        
        self.assertIn('donors', result)
        self.assertIn('limit', result)
    
    def test_top_donors_respects_limit(self):
        """Test that top donors respects limit parameter."""
        result = statistics.calculate_top_donors(limit=1)
        
        self.assertLessEqual(len(result['donors']), 1)
    
    def test_top_donors_contains_user_info(self):
        """Test that top donors contains user information."""
        result = statistics.calculate_top_donors()
        
        if len(result['donors']) > 0:
            donor = result['donors'][0]
            self.assertIn('user_id', donor)
            self.assertIn('email', donor)
            self.assertIn('name', donor)
            self.assertIn('total_donated', donor)
            self.assertIn('donation_count', donor)


# ============================================================================
# REVENUE STATISTICS TESTS (CRITICAL)
# ============================================================================

class RevenueOverviewTests(PaymentStatisticsBaseTestCase):
    """Tests for revenue overview statistics - CRITICAL revenue calculation tests."""
    
    def test_only_completed_payments_counted(self):
        """Test that ONLY COMPLETED payments count toward revenue."""
        result = statistics.calculate_revenue_overview(event_id=str(self.event1.id))
        
        # Count only COMPLETED payments for event1
        completed_count = Payment.objects.filter(
            event=self.event1,
            status=PaymentStatusChoices.COMPLETED
        ).count()
        
        self.assertEqual(result['total_completed_payments'], completed_count)
        
        # Verify PENDING, FAILED, CANCELLED are NOT counted
        total_revenue = result['total_revenue']
        
        # Sum only completed payments
        completed_sum = float(
            Payment.objects.filter(
                event=self.event1,
                status=PaymentStatusChoices.COMPLETED
            ).aggregate(
                total=Sum('base_amount')
            )['total']
        )
        
        self.assertAlmostEqual(total_revenue, completed_sum, places=2)
    
    def test_revenue_excludes_pending_payments(self):
        """Test that PENDING payments are excluded from revenue."""
        result = statistics.calculate_revenue_overview()
        
        # Create a pending payment
        pending_payment = self._create_payment(
            user=self.regular_user,
            event=self.event1,
            status=PaymentStatusChoices.PENDING,
            amount=1000.00,
            method=self.method_stripe_event1
        )
        
        result_after = statistics.calculate_revenue_overview()
        
        # Revenue should be the same (pending payment not counted)
        self.assertEqual(result['total_revenue'], result_after['total_revenue'])
        
        # Clean up
        pending_payment.delete()
    
    def test_revenue_excludes_failed_payments(self):
        """Test that FAILED payments are excluded from revenue."""
        result = statistics.calculate_revenue_overview(event_id=str(self.event1.id))
        
        # Verify failed payments exist but aren't counted
        failed_count = Payment.objects.filter(
            event=self.event1,
            status=PaymentStatusChoices.FAILED
        ).count()
        
        self.assertGreater(failed_count, 0, "Test data should include failed payments")
        
        # Verify they're not in revenue
        total_payments = Payment.objects.filter(event=self.event1).count()
        self.assertGreater(total_payments, result['total_completed_payments'])
    
    def test_revenue_overview_basic(self):
        """Test basic revenue overview calculation."""
        result = statistics.calculate_revenue_overview()
        
        self.assertIn('total_revenue', result)
        self.assertIn('total_completed_payments', result)
        self.assertIn('average_payment', result)
        self.assertIn('total_refunded', result)
        self.assertIn('net_revenue', result)
    
    def test_revenue_net_calculation(self):
        """Test net revenue calculation (gross - refunded)."""
        result = statistics.calculate_revenue_overview()
        
        calculated_net = (result['total_revenue'] or 0) - (result['total_refunded'] or 0)
        self.assertAlmostEqual(result['net_revenue'], calculated_net, places=2)
    
    def test_revenue_with_event_filter(self):
        """Test revenue filtered by event."""
        result = statistics.calculate_revenue_overview(event_id=str(self.event1.id))
        
        # Should only include event1 completed payments
        event1_completed = Payment.objects.filter(
            event=self.event1,
            status=PaymentStatusChoices.COMPLETED
        ).count()
        
        self.assertEqual(result['total_completed_payments'], event1_completed)


class RevenueTrendsTests(PaymentStatisticsBaseTestCase):
    """Tests for revenue trends statistics."""
    
    def test_only_completed_payments_counted(self):
        """Test that only COMPLETED payments are counted in revenue trends."""
        result = statistics.calculate_revenue_trends(event_id=str(self.event1.id))
        
        # Count total payments in trends
        total_in_trends = sum(item['count'] for item in result['trends'])
        
        # Should equal completed payment count
        completed_count = Payment.objects.filter(
            event=self.event1,
            status=PaymentStatusChoices.COMPLETED
        ).count()
        
        self.assertEqual(total_in_trends, completed_count)
    
    def test_basic_revenue_trends(self):
        """Test basic revenue trends calculation."""
        result = statistics.calculate_revenue_trends()
        
        self.assertIn('trends', result)
        self.assertIn('total_revenue', result)
        self.assertIn('total_payments', result)
    
    def test_revenue_trends_grouping(self):
        """Test revenue trends with different groupings."""
        for group_by in ['day', 'week', 'month']:
            result = statistics.calculate_revenue_trends(group_by=group_by)
            self.assertIn('trends', result)


class RevenueByMethodTests(PaymentStatisticsBaseTestCase):
    """Tests for revenue by payment method statistics."""
    
    def test_only_completed_payments_counted(self):
        """Test that only COMPLETED payments are counted in revenue by method."""
        result = statistics.calculate_revenue_by_method(event_id=str(self.event1.id))
        
        # Calculate expected revenue from completed Stripe payments
        stripe_completed_revenue = float(
            Payment.objects.filter(
                event=self.event1,
                status=PaymentStatusChoices.COMPLETED,
                method=self.method_stripe_event1
            ).aggregate(
                total=Sum('base_amount')
            )['total']
        )
        
        # Find Stripe in results
        stripe_method = next(
            (m for m in result['methods'] if m['method'] == self.method_stripe_event1.title),
            None
        )
        
        if stripe_method:
            self.assertAlmostEqual(stripe_method['revenue'], stripe_completed_revenue, places=2)
    
    def test_basic_revenue_by_method(self):
        """Test basic revenue by method calculation."""
        result = statistics.calculate_revenue_by_method()
        
        self.assertIn('total_revenue', result)
        self.assertIn('methods', result)
    
    def test_revenue_by_method_percentages(self):
        """Test that revenue by method includes percentages."""
        result = statistics.calculate_revenue_by_method(event_id=str(self.event1.id))
        
        if len(result['methods']) > 0:
            for method in result['methods']:
                self.assertIn('percentage', method)
                self.assertGreaterEqual(method['percentage'], 0)
                self.assertLessEqual(method['percentage'], 100)


class RevenueBreakdownTests(PaymentStatisticsBaseTestCase):
    """Tests for revenue breakdown statistics."""
    
    def test_only_completed_payments_in_gross_revenue(self):
        """Test that only COMPLETED payments are included in gross revenue."""
        result = statistics.calculate_revenue_breakdown(event_id=str(self.event1.id))
        
        # Calculate expected gross revenue
        expected_gross = float(
            Payment.objects.filter(
                event=self.event1,
                status=PaymentStatusChoices.COMPLETED
            ).aggregate(
                total=Sum('base_amount')
            )['total']
        )
        
        self.assertAlmostEqual(result['gross_revenue'], expected_gross, places=2)
    
    def test_basic_revenue_breakdown(self):
        """Test basic revenue breakdown calculation."""
        result = statistics.calculate_revenue_breakdown()
        
        self.assertIn('gross_revenue', result)
        self.assertIn('refunded_amount', result)
        self.assertIn('net_revenue', result)
        self.assertIn('pending_refund_amount', result)
    
    def test_net_revenue_calculation(self):
        """Test that net revenue = gross - refunded."""
        result = statistics.calculate_revenue_breakdown()
        
        calculated_net = result['gross_revenue'] - result['refunded_amount']
        self.assertAlmostEqual(result['net_revenue'], calculated_net, places=2)


# ============================================================================
# OVERVIEW STATISTICS TESTS
# ============================================================================

class OverviewStatsTests(PaymentStatisticsBaseTestCase):
    """Tests for combined overview statistics."""
    
    def test_basic_overview(self):
        """Test basic overview statistics."""
        result = statistics.calculate_overview_stats()
        
        self.assertIn('payments', result)
        self.assertIn('revenue', result)
        self.assertIn('discounts', result)
        self.assertIn('refunds', result)
        self.assertIn('donations', result)
    
    def test_overview_structure(self):
        """Test that overview has correct structure."""
        result = statistics.calculate_overview_stats()
        
        # Check payments section
        self.assertIn('total', result['payments'])
        self.assertIn('total_amount', result['payments'])
        
        # Check revenue section
        self.assertIn('gross', result['revenue'])
        self.assertIn('net', result['revenue'])
        
        # Check discounts section
        self.assertIn('total_active', result['discounts'])
        
        # Check refunds section
        self.assertIn('total_requests', result['refunds'])
        
        # Check donations section
        self.assertIn('total', result['donations'])
    
    def test_overview_with_event_filter(self):
        """Test overview with event filter."""
        result = statistics.calculate_overview_stats(event_id=str(self.event1.id))
        
        # Verify it's filtered to event1
        event1_payments = Payment.objects.filter(event=self.event1).count()
        self.assertEqual(result['payments']['total'], event1_payments)


# ============================================================================
# API ENDPOINT TESTS
# ============================================================================

class PaymentStatisticsAPITests(PaymentStatisticsBaseTestCase):
    """Tests for payment statistics API endpoints."""
    
    def test_authentication_required(self):
        """Test that authentication is required for all endpoints."""
        response = self.client.get('/api/payments/statistics/overview/')
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)
    
    def test_global_stats_require_superuser(self):
        """Test that global statistics (no event_id) require superuser."""
        # Regular user should be denied
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/payments/statistics/overview/')
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)
        
        # Admin user should be allowed
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/payments/statistics/overview/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
    
    def test_event_specific_stats_allowed_for_authenticated(self):
        """Test that event-specific statistics are allowed for authenticated users."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/payments/statistics/overview/?event_id={self.event1.event_id}'
        )
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
    
    def test_overview_endpoint_raw_format(self):
        """Test overview endpoint with raw format."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/payments/statistics/overview/?format=raw')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('payments', response.data)
        self.assertIn('revenue', response.data)
    
    def test_overview_endpoint_echarts_format(self):
        """Test overview endpoint with echarts format."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/payments/statistics/overview/?format=echarts')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        # Overview doesn't add chart, but should still return data
        self.assertIn('payments', response.data)
    
    def test_payment_status_endpoint(self):
        """Test payment status distribution endpoint."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/payments/statistics/payment-status/')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('total', response.data)
        self.assertIn('distribution', response.data)
    
    def test_revenue_overview_endpoint(self):
        """Test revenue overview endpoint."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/payments/statistics/revenue-overview/')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('total_revenue', response.data)
        self.assertIn('net_revenue', response.data)
    
    def test_filter_metadata_in_response(self):
        """Test that filter metadata is included in responses."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/payments/statistics/overview/?event_id={self.event1.event_id}&include_deleted=true'
        )
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('filters_applied', response.data)
        self.assertIn('generated_at', response.data)
        
        filters = response.data['filters_applied']
        self.assertEqual(filters['event_id'], str(self.event1.id))
    
    def test_invalid_uuid_returns_error(self):
        """Test that invalid UUID format returns validation error."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/payments/statistics/overview/?event_id=invalid-uuid')
        
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
    
    def test_list_endpoints(self):
        """Test that list endpoint returns available endpoints."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/payments/statistics/')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('endpoints', response.data)
        self.assertIn('supported_parameters', response.data)
    
    def test_all_major_endpoints_accessible(self):
        """Test that all major endpoints are accessible."""
        self.client.force_authenticate(user=self.admin_user)
        
        endpoints = [
            'overview',
            'payment-status',
            'payment-methods',
            'payment-overview',
            'discount-usage',
            'refund-requests',
            'donations',
            'revenue-overview',
            'revenue-breakdown',
        ]
        
        for endpoint in endpoints:
            response = self.client.get(f'/api/payments/statistics/{endpoint}/')
            self.assertEqual(
                response.status_code,
                http_status.HTTP_200_OK,
                f"Endpoint {endpoint} returned {response.status_code}"
            )


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class PaymentStatisticsEdgeCaseTests(PaymentStatisticsBaseTestCase):
    """Tests for edge cases in payment statistics."""
    
    def test_empty_event_statistics(self):
        """Test statistics for an event with no payments."""
        result = statistics.calculate_payment_overview(event_id=str(self.event3.id))
        
        self.assertEqual(result['total_payments'], 0)
        self.assertIsNone(result['total_amount'])
        self.assertIsNone(result['average_amount'])
    
    def test_revenue_with_no_completed_payments(self):
        """Test revenue calculation when there are no completed payments."""
        # Use event3 which has no payments
        result = statistics.calculate_revenue_overview(event_id=str(self.event3.id))
        
        self.assertEqual(result['total_completed_payments'], 0)
        self.assertIsNone(result['total_revenue'])
    
    def test_include_deleted_only_affects_orders(self):
        """Test that include_deleted parameter only affects orders, not payments."""
        # Payment model doesn't support soft-delete
        result_without = statistics.calculate_payment_overview(
            event_id=str(self.event1.id),
            include_deleted=False
        )
        
        result_with = statistics.calculate_payment_overview(
            event_id=str(self.event1.id),
            include_deleted=True
        )
        
        # Results should be identical for payment statistics
        self.assertEqual(result_without['total_payments'], result_with['total_payments'])
    
    def test_money_field_serialization(self):
        """Test that Money fields are correctly serialized to float."""
        result = statistics.calculate_revenue_overview()
        
        # Should be float, not Money object
        self.assertIsInstance(result['total_revenue'] or 0, (int, float))
        self.assertIsInstance(result['average_payment'] or 0, (int, float))
    
    def test_date_range_with_no_data(self):
        """Test date range filtering with no data in range."""
        future_date = date.today() + timedelta(days=365)
        result = statistics.calculate_payment_trends(
            date_from=future_date,
            date_to=future_date + timedelta(days=7)
        )
        
        self.assertEqual(len(result['trends']), 0)
        self.assertEqual(result['total'], 0)
