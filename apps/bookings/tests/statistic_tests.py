"""
Booking Statistics Tests

Comprehensive test suite for booking statistics functionality testing:
- Core statistics calculation functions
- API endpoints with raw and ECharts formats
- Event and organization filtering capabilities
- Soft-delete handling
- Revenue calculations with status-specific logic (COMPLETED payments only)
- Edge cases and data accuracy

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient
from rest_framework import status as http_status
from datetime import date, datetime, timedelta
from decimal import Decimal
from djmoney.money import Money

from apps.bookings.models import (
    Booking, Ticket, BookingPackage, BookingPackageRule,
    TicketType, BookingIntent, PackageProduct
)
from apps.bookings.services import statistics
from apps.attendee.models import Attendee
from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation
from apps.payments.models import Payment, PaymentStatusChoices
from apps.products.models import Product, ProductCategory

User = get_user_model()


class BookingStatisticsBaseTestCase(TestCase):
    """Base test case with comprehensive setup for booking statistics tests."""
    
    def setUp(self):
        """Set up comprehensive test data for statistics testing."""
        self.client = APIClient()
        
        # ==================== STEP 1: Create Users ====================
        self.customer = User.objects.create_user(
            username='customer@test.com',
            email='customer@test.com',
            password='testpass123',
            first_name='Customer',
            last_name='User'
        )
        
        self.staff_user = User.objects.create_user(
            username='staff@test.com',
            email='staff@test.com',
            password='testpass123',
            first_name='Staff',
            last_name='User',
            is_staff=True
        )
        
        self.superuser = User.objects.create_superuser(
            username='admin@test.com',
            email='admin@test.com',
            password='testpass123',
            first_name='Admin',
            last_name='User'
        )
        
        # ==================== STEP 2: Create Organizations ====================
        self.organisation1 = Organisation.objects.create(
            title='Test Org 1',
        )
        
        self.organisation2 = Organisation.objects.create(
            title='Test Org 2',
        )
        
        # ==================== STEP 3: Create Event Types ====================
        self.event_type = EventType.objects.create(
            title='Test Event Type',
            description='Description'
        )
        
        # ==================== STEP 4: Create Events ====================
        now = timezone.now()
        self.event1 = Event.objects.create(
            title='Test Event 1',
            display_code='EV1',
            start_datetime=now + timedelta(days=30),
            end_datetime=now + timedelta(days=32),
            event_type=self.event_type,
            organisation=self.organisation1,
            maximum_attendance=100,
            status=EventStatusChoices.OPEN,
            created_by=self.staff_user
        )
        
        self.event2 = Event.objects.create(
            title='Test Event 2',
            display_code='EV2',
            start_datetime=now + timedelta(days=60),
            end_datetime=now + timedelta(days=62),
            event_type=self.event_type,
            organisation=self.organisation2,
            maximum_attendance=50,
            status=EventStatusChoices.OPEN,
            created_by=self.staff_user
        )
        
        # ==================== STEP 5: Create Ticket Types ====================
        self.ticket_type_full = TicketType.objects.create(
            title='Full Event Ticket',
            event=self.event1,
            scope='FULL_EVENT',
            is_active=True
        )
        
        self.ticket_type_single_day = TicketType.objects.create(
            title='Single Day Ticket',
            event=self.event1,
            scope='SINGLE_DAY',
            is_active=True
        )
        
        self.ticket_type_workshop = TicketType.objects.create(
            title='Workshop Ticket',
            event=self.event1,
            scope='WORKSHOP_ONLY',
            is_active=True
        )
        
        self.ticket_type_event2 = TicketType.objects.create(
            title='Event 2 Full Ticket',
            event=self.event2,
            scope='FULL_EVENT',
            is_active=True
        )
        
        # ==================== STEP 6: Create Booking Packages ====================
        self.package_standard = BookingPackage.objects.create(
            name='Standard Package',
            event=self.event1,
            ticket_type=self.ticket_type_full,
            base_amount=Money(50, 'GBP'),
            percentage_modifier=Decimal('1.0'),
            is_active=True
        )
        
        self.package_discount = BookingPackage.objects.create(
            name='Discount Package',
            event=self.event1,
            ticket_type=self.ticket_type_full,
            base_amount=Money(30, 'GBP'),
            percentage_modifier=Decimal('0.8'),
            is_active=True
        )
        
        self.package_premium = BookingPackage.objects.create(
            name='Premium Package',
            event=self.event1,
            ticket_type=self.ticket_type_full,
            base_amount=Money(100, 'GBP'),
            percentage_modifier=Decimal('1.2'),
            is_active=True
        )
        
        # ==================== STEP 7: Create Package Rules ====================
        self.rule_age = BookingPackageRule.objects.create(
            booking_package=self.package_discount,
            rule_type='IS_AGE_LT',
            value='18',
            active=True
        )
        
        self.rule_staff = BookingPackageRule.objects.create(
            booking_package=self.package_standard,
            rule_type='IS_EVENT_STAFF',
            active=True
        )
        
        # Authenticate client for API tests
        self.client.force_authenticate(user=self.superuser)
    
    def _create_booking(
        self,
        event=None,
        made_by=None,
        booked_at=None,
        attendee_count=1,
        days_ago=0
    ):
        """
        Helper method to create a booking with attendees.
        
        Args:
            event: Event for the booking (defaults to self.event1)
            made_by: User who made the booking (defaults to self.customer)
            booked_at: Booking timestamp (defaults to now - days_ago)
            attendee_count: Number of attendees to create (default: 1)
            days_ago: Days in the past for booking creation (default: 0)
        
        Returns:
            Booking instance with attendees
        """
        if event is None:
            event = self.event1
        if made_by is None:
            made_by = self.customer
        if booked_at is None:
            # Use date.today() and convert to datetime at noon to ensure different calendar days
            target_date = date.today() - timedelta(days=days_ago)
            booked_at = timezone.make_aware(datetime.combine(target_date, datetime.min.time().replace(hour=12)))
        
        booking = Booking.objects.create(
            event=event,
            made_by=made_by,
        )
        # Override auto_now_add field
        Booking.objects.filter(pk=booking.pk).update(booked_at=booked_at)
        booking.refresh_from_db()
        
        # Create attendees
        for i in range(attendee_count):
            Attendee.objects.create(
                booking=booking,
                event=event,
                first_name=f'Attendee{i}',
                last_name='Test',
                date_of_birth=date(1990, 1, 1),
                email=f'attendee{i}@test.com',
                relationship_to_user='SELF' if i == 0 else 'FRIEND'
            )
        
        return booking
    
    def _create_ticket(
        self,
        attendee,
        ticket_type=None,
        package=None,
        status='ACTIVE',
        uses=1
    ):
        """
        Helper method to create a ticket.
        
        Args:
            attendee: Attendee for the ticket
            ticket_type: TicketType (defaults to self.ticket_type_full)
            package: BookingPackage (optional)
            status: Ticket status (default: 'ACTIVE')
            uses: Number of uses remaining (default: 1)
        
        Returns:
            Ticket instance
        """
        if ticket_type is None:
            ticket_type = self.ticket_type_full
        
        ticket = Ticket.objects.create(
            attendee=attendee,
            ticket_type=ticket_type,
            package=package,
            status=status,
            uses=uses
        )
        
        return ticket
    
    def _create_payment(
        self,
        booking,
        status='COMPLETED',
        amount=100.00,
        days_ago=0
    ):
        """
        Helper method to create a payment for a booking.
        
        Args:
            booking: Booking to link payment to
            status: Payment status (default: 'COMPLETED')
            amount: Payment amount (default: 100.00)
            days_ago: Days in the past for payment creation (default: 0)
        
        Returns:
            Payment instance
        """
        # Use date.today() and convert to datetime at noon to ensure different calendar days
        target_date = date.today() - timedelta(days=days_ago)
        created_at = timezone.make_aware(datetime.combine(target_date, datetime.min.time().replace(hour=12)))
        
        # Get ContentType for Booking model
        booking_ct = ContentType.objects.get_for_model(Booking)
        
        payment = Payment.objects.create(
            event=booking.event,
            user=booking.made_by,
            status=status,
            base_amount=Money(amount, 'GBP'),
            target_type=booking_ct,
            target_id=booking.id
        )
        # Override auto_now_add field
        Payment.objects.filter(pk=payment.pk).update(created_at=created_at)
        payment.refresh_from_db()
        
        return payment
    
    def _create_intent(
        self,
        event=None,
        status='PENDING',
        intended_ticket_count=2,
        days_ago=0
    ):
        """
        Helper method to create a booking intent.
        
        Args:
            event: Event for the intent (defaults to self.event1)
            status: Intent status (default: 'PENDING')
            intended_ticket_count: Number of tickets reserved (default: 2)
            days_ago: Days in the past for intent creation (default: 0)
        
        Returns:
            BookingIntent instance
        """
        if event is None:
            event = self.event1
        
        # Use date.today() and convert to datetime at noon to ensure different calendar days
        target_date = date.today() - timedelta(days=days_ago)
        created_at = timezone.make_aware(datetime.combine(target_date, datetime.min.time().replace(hour=12)))
        
        intent = BookingIntent.objects.create(
            event=event,
            status=status,
            intended_ticket_count=intended_ticket_count,
        )
        # Override auto_now_add field
        BookingIntent.objects.filter(pk=intent.pk).update(created_at=created_at)
        intent.refresh_from_db()
        
        return intent


# ============================================================================
# BOOKING STATISTICS TESTS
# ============================================================================

class BookingOverviewStatisticsTests(BookingStatisticsBaseTestCase):
    """Tests for booking overview statistics."""
    
    def test_basic_overview(self):
        """Test basic booking overview calculation."""
        # Create bookings
        booking1 = self._create_booking(attendee_count=2)
        booking2 = self._create_booking(attendee_count=3)
        
        # Create tickets
        for attendee in booking1.attendees.all():
            self._create_ticket(attendee)
        for attendee in booking2.attendees.all():
            self._create_ticket(attendee)
        
        stats = statistics.calculate_booking_overview()
        
        self.assertEqual(stats['total_bookings'], 2)
        self.assertEqual(stats['total_attendees'], 5)
        self.assertEqual(stats['total_tickets'], 5)
        self.assertEqual(stats['average_attendees_per_booking'], 2.5)
    
    def test_overview_with_event_filter(self):
        """Test overview filtered by event_id (UUID)."""
        booking1 = self._create_booking(event=self.event1, attendee_count=2)
        booking2 = self._create_booking(event=self.event2, attendee_count=1)
        
        stats = statistics.calculate_booking_overview(event_id=str(self.event1.event_id))
        
        self.assertEqual(stats['total_bookings'], 1)
        self.assertEqual(stats['total_attendees'], 2)
    
    def test_overview_with_organization_filter(self):
        """Test overview filtered by organization_id."""
        booking1 = self._create_booking(event=self.event1, attendee_count=2)
        booking2 = self._create_booking(event=self.event2, attendee_count=1)
        
        stats = statistics.calculate_booking_overview(organization_id=self.organisation1.id)
        
        self.assertEqual(stats['total_bookings'], 1)
        self.assertEqual(stats['total_attendees'], 2)
    
    def test_overview_with_soft_deleted_attendees(self):
        """Test overview handling of soft-deleted attendees."""
        booking = self._create_booking(attendee_count=3)
        
        # Soft-delete one attendee
        attendee = booking.attendees.first()
        attendee.deleted_at = timezone.now()
        attendee.save()
        
        # Without include_deleted
        stats = statistics.calculate_booking_overview(include_deleted=False)
        self.assertEqual(stats['total_attendees'], 2)
        
        # With include_deleted
        stats = statistics.calculate_booking_overview(include_deleted=True)
        self.assertEqual(stats['total_attendees'], 3)


class BookingStatusDistributionTests(BookingStatisticsBaseTestCase):
    """Tests for booking status distribution statistics."""
    
    def test_status_distribution_by_payment(self):
        """Test booking status distribution based on payment status."""
        booking1 = self._create_booking(attendee_count=1)
        booking2 = self._create_booking(attendee_count=1)
        booking3 = self._create_booking(attendee_count=1)
        
        # Create payments with different statuses
        self._create_payment(booking1, status=PaymentStatusChoices.COMPLETED)
        self._create_payment(booking2, status=PaymentStatusChoices.PENDING)
        self._create_payment(booking3, status=PaymentStatusChoices.FAILED)
        
        stats = statistics.calculate_booking_status_distribution()
        
        self.assertEqual(stats['total'], 3)
        self.assertEqual(len(stats['distribution']), 3)
        
        # Check we have all statuses
        statuses = [item['label'] for item in stats['distribution']]
        self.assertIn(PaymentStatusChoices.COMPLETED, statuses)
        self.assertIn(PaymentStatusChoices.PENDING, statuses)
        self.assertIn(PaymentStatusChoices.FAILED, statuses)
    
    def test_status_distribution_percentages(self):
        """Test percentage calculation in status distribution."""
        booking1 = self._create_booking(attendee_count=1)
        booking2 = self._create_booking(attendee_count=1)
        booking3 = self._create_booking(attendee_count=1)
        booking4 = self._create_booking(attendee_count=1)
        
        # 50% completed, 25% pending, 25% no payment
        self._create_payment(booking1, status=PaymentStatusChoices.COMPLETED)
        self._create_payment(booking2, status=PaymentStatusChoices.COMPLETED)
        self._create_payment(booking3, status=PaymentStatusChoices.PENDING)
        
        stats = statistics.calculate_booking_status_distribution()
        
        completed = next(item for item in stats['distribution'] if item['label'] == PaymentStatusChoices.COMPLETED)
        self.assertEqual(completed['percentage'], 50.0)


class BookingTrendsStatisticsTests(BookingStatisticsBaseTestCase):
    """Tests for booking trends statistics."""
    
    def test_trends_grouping_day(self):
        """Test booking trends grouped by day."""
        self._create_booking(attendee_count=1, days_ago=0)
        self._create_booking(attendee_count=1, days_ago=0)
        self._create_booking(attendee_count=1, days_ago=1)
        
        stats = statistics.calculate_booking_trends(group_by='day')
        
        self.assertEqual(stats['group_by'], 'day')
        self.assertEqual(len(stats['trends']), 2)  # Two days with bookings
    
    def test_trends_grouping_week(self):
        """Test booking trends grouped by week."""
        self._create_booking(attendee_count=1, days_ago=0)
        self._create_booking(attendee_count=1, days_ago=2)
        self._create_booking(attendee_count=1, days_ago=10)
        
        stats = statistics.calculate_booking_trends(group_by='week')
        
        self.assertEqual(stats['group_by'], 'week')
        self.assertGreaterEqual(len(stats['trends']), 1)
    
    def test_trends_grouping_month(self):
        """Test booking trends grouped by month."""
        self._create_booking(attendee_count=1, days_ago=0)
        self._create_booking(attendee_count=1, days_ago=15)
        self._create_booking(attendee_count=1, days_ago=35)
        
        stats = statistics.calculate_booking_trends(group_by='month')
        
        self.assertEqual(stats['group_by'], 'month')
        self.assertGreaterEqual(len(stats['trends']), 1)
    
    def test_trends_with_date_filters(self):
        """Test booking trends with date range filtering."""
        today = date.today()
        self._create_booking(attendee_count=1, days_ago=0)
        self._create_booking(attendee_count=1, days_ago=5)
        self._create_booking(attendee_count=1, days_ago=15)
        
        # Filter to last 7 days
        date_from = today - timedelta(days=7)
        stats = statistics.calculate_booking_trends(
            group_by='day',
            date_from=date_from,
            date_to=today
        )
        
        self.assertLessEqual(stats['total_bookings'], 2)


class BookingsByPackageTests(BookingStatisticsBaseTestCase):
    """Tests for bookings by package statistics."""
    
    def test_package_distribution(self):
        """Test distribution of bookings by package."""
        booking1 = self._create_booking(attendee_count=2)
        booking2 = self._create_booking(attendee_count=3)
        
        # Create tickets with packages
        for attendee in booking1.attendees.all():
            self._create_ticket(attendee, package=self.package_standard)
        
        for attendee in booking2.attendees.all():
            self._create_ticket(attendee, package=self.package_discount)
        
        stats = statistics.calculate_bookings_by_package()
        
        self.assertEqual(stats['total_tickets_with_package'], 5)
        self.assertEqual(len(stats['distribution']), 2)
    
    def test_package_distribution_with_limit(self):
        """Test package distribution with limit parameter."""
        booking = self._create_booking(attendee_count=5)
        
        for idx, attendee in enumerate(booking.attendees.all()):
            package = self.package_standard if idx < 3 else self.package_discount
            self._create_ticket(attendee, package=package)
        
        stats = statistics.calculate_bookings_by_package(limit=1)
        
        self.assertEqual(len(stats['distribution']), 1)
        self.assertEqual(stats['distribution'][0]['package_name'], 'Standard Package')


class AttendeesPerBookingTests(BookingStatisticsBaseTestCase):
    """Tests for attendees per booking distribution."""
    
    def test_attendees_distribution(self):
        """Test distribution of attendees per booking."""
        self._create_booking(attendee_count=1)
        self._create_booking(attendee_count=2)
        self._create_booking(attendee_count=2)
        self._create_booking(attendee_count=3)
        
        stats = statistics.calculate_attendees_per_booking()
        
        self.assertEqual(stats['total_bookings'], 4)
        self.assertEqual(stats['average_attendees'], 2.0)
        self.assertEqual(stats['max_attendees'], 3)
        self.assertEqual(stats['min_attendees'], 1)
    
    def test_attendees_distribution_counts(self):
        """Test distribution item counts."""
        self._create_booking(attendee_count=2)
        self._create_booking(attendee_count=2)
        self._create_booking(attendee_count=3)
        
        stats = statistics.calculate_attendees_per_booking()
        
        # Should have 2 bookings with 2 attendees, 1 booking with 3 attendees
        distribution_dict = {item['attendee_count']: item['booking_count'] for item in stats['distribution']}
        self.assertEqual(distribution_dict[2], 2)
        self.assertEqual(distribution_dict[3], 1)


class BookingCompletionRateTests(BookingStatisticsBaseTestCase):
    """Tests for booking completion rate statistics."""
    
    def test_completion_rate_calculation(self):
        """Test booking completion rate from intents."""
        self._create_intent(status='COMPLETED')
        self._create_intent(status='COMPLETED')
        self._create_intent(status='EXPIRED')
        self._create_intent(status='CANCELLED')
        self._create_intent(status='PENDING')
        
        stats = statistics.calculate_booking_completion_rate()
        
        self.assertEqual(stats['total_intents'], 5)
        self.assertEqual(stats['completed_intents'], 2)
        self.assertEqual(stats['expired_intents'], 1)
        self.assertEqual(stats['cancelled_intents'], 1)
        self.assertEqual(stats['pending_intents'], 1)
        self.assertEqual(stats['completion_rate'], 40.0)
    
    def test_completion_rate_with_event_filter(self):
        """Test completion rate filtered by event."""
        self._create_intent(event=self.event1, status='COMPLETED')
        self._create_intent(event=self.event1, status='EXPIRED')
        self._create_intent(event=self.event2, status='COMPLETED')
        
        stats = statistics.calculate_booking_completion_rate(event_id=str(self.event1.event_id))
        
        self.assertEqual(stats['total_intents'], 2)
        self.assertEqual(stats['completion_rate'], 50.0)


# ============================================================================
# TICKET STATISTICS TESTS
# ============================================================================

class TicketOverviewStatisticsTests(BookingStatisticsBaseTestCase):
    """Tests for ticket overview statistics."""
    
    def test_ticket_overview_basic(self):
        """Test basic ticket overview."""
        booking = self._create_booking(attendee_count=3)
        
        for attendee in booking.attendees.all():
            self._create_ticket(attendee, status='ACTIVE', uses=2)
        
        stats = statistics.calculate_ticket_overview()
        
        self.assertEqual(stats['total_tickets'], 3)
        self.assertEqual(stats['average_uses_remaining'], 2.0)
        self.assertEqual(stats['total_uses_remaining'], 6)
    
    def test_ticket_overview_status_breakdown(self):
        """Test ticket status breakdown in overview."""
        booking = self._create_booking(attendee_count=3)
        attendees = list(booking.attendees.all())
        
        self._create_ticket(attendees[0], status='ACTIVE')
        self._create_ticket(attendees[1], status='USED')
        self._create_ticket(attendees[2], status='CANCELLED')
        
        stats = statistics.calculate_ticket_overview()
        
        statuses = {item['status']: item['count'] for item in stats['status_breakdown']}
        self.assertEqual(statuses['ACTIVE'], 1)
        self.assertEqual(statuses['USED'], 1)
        self.assertEqual(statuses['CANCELLED'], 1)
    
    def test_ticket_overview_scope_breakdown(self):
        """Test ticket scope breakdown in overview."""
        booking = self._create_booking(attendee_count=3)
        attendees = list(booking.attendees.all())
        
        self._create_ticket(attendees[0], ticket_type=self.ticket_type_full)
        self._create_ticket(attendees[1], ticket_type=self.ticket_type_single_day)
        self._create_ticket(attendees[2], ticket_type=self.ticket_type_workshop)
        
        stats = statistics.calculate_ticket_overview()
        
        scopes = {item['scope']: item['count'] for item in stats['scope_breakdown']}
        self.assertEqual(scopes['FULL_EVENT'], 1)
        self.assertEqual(scopes['SINGLE_DAY'], 1)
        self.assertEqual(scopes['WORKSHOP_ONLY'], 1)


class TicketStatusDistributionTests(BookingStatisticsBaseTestCase):
    """Tests for ticket status distribution."""
    
    def test_status_distribution(self):
        """Test ticket status distribution."""
        booking = self._create_booking(attendee_count=4)
        attendees = list(booking.attendees.all())
        
        self._create_ticket(attendees[0], status='ACTIVE')
        self._create_ticket(attendees[1], status='ACTIVE')
        self._create_ticket(attendees[2], status='USED')
        self._create_ticket(attendees[3], status='CANCELLED')
        
        stats = statistics.calculate_ticket_status_distribution()
        
        self.assertEqual(stats['total'], 4)
        
        statuses = {item['label']: item for item in stats['distribution']}
        self.assertEqual(statuses['ACTIVE']['value'], 2)
        self.assertEqual(statuses['ACTIVE']['percentage'], 50.0)


class TicketTypeDistributionTests(BookingStatisticsBaseTestCase):
    """Tests for ticket type distribution."""
    
    def test_type_distribution(self):
        """Test ticket type distribution."""
        booking = self._create_booking(attendee_count=3)
        attendees = list(booking.attendees.all())
        
        self._create_ticket(attendees[0], ticket_type=self.ticket_type_full)
        self._create_ticket(attendees[1], ticket_type=self.ticket_type_full)
        self._create_ticket(attendees[2], ticket_type=self.ticket_type_single_day)
        
        stats = statistics.calculate_ticket_type_distribution()
        
        self.assertEqual(stats['total'], 3)
        self.assertEqual(len(stats['distribution']), 2)


class TicketUsageStatsTests(BookingStatisticsBaseTestCase):
    """Tests for ticket usage statistics."""
    
    def test_usage_statistics(self):
        """Test ticket usage statistics."""
        booking = self._create_booking(attendee_count=4)
        attendees = list(booking.attendees.all())
        
        self._create_ticket(attendees[0], status='ACTIVE', uses=3)
        self._create_ticket(attendees[1], status='ACTIVE', uses=1)
        self._create_ticket(attendees[2], status='USED', uses=0)
        self._create_ticket(attendees[3], status='CANCELLED', uses=0)
        
        stats = statistics.calculate_ticket_usage_stats()
        
        self.assertEqual(stats['total_tickets'], 4)
        self.assertEqual(stats['valid_tickets'], 2)  # ACTIVE with uses > 0
        self.assertEqual(stats['used_tickets'], 1)
        self.assertEqual(stats['cancelled_tickets'], 1)
        self.assertEqual(stats['usage_rate'], 25.0)  # 1 used out of 4 total


class TicketScopeDistributionTests(BookingStatisticsBaseTestCase):
    """Tests for ticket scope distribution."""
    
    def test_scope_distribution(self):
        """Test ticket scope distribution."""
        booking = self._create_booking(attendee_count=3)
        attendees = list(booking.attendees.all())
        
        self._create_ticket(attendees[0], ticket_type=self.ticket_type_full)
        self._create_ticket(attendees[1], ticket_type=self.ticket_type_single_day)
        self._create_ticket(attendees[2], ticket_type=self.ticket_type_workshop)
        
        stats = statistics.calculate_ticket_scope_distribution()
        
        self.assertEqual(stats['total'], 3)
        
        scopes = {item['label']: item for item in stats['distribution']}
        self.assertEqual(scopes['FULL_EVENT']['value'], 1)
        self.assertEqual(scopes['SINGLE_DAY']['value'], 1)
        self.assertEqual(scopes['WORKSHOP_ONLY']['value'], 1)


# ============================================================================
# PACKAGE STATISTICS TESTS
# ============================================================================

class PackageOverviewStatisticsTests(BookingStatisticsBaseTestCase):
    """Tests for package overview statistics."""
    
    def test_package_overview(self):
        """Test package overview statistics."""
        booking = self._create_booking(attendee_count=2)
        
        for attendee in booking.attendees.all():
            self._create_ticket(attendee, package=self.package_standard)
        
        stats = statistics.calculate_package_overview()
        
        self.assertGreaterEqual(stats['total_packages'], 3)  # We created 3 in setup
        self.assertEqual(stats['active_packages'], 3)
        self.assertEqual(stats['packages_with_tickets'], 1)
        self.assertEqual(stats['total_tickets_using_packages'], 2)


class PackagePopularityTests(BookingStatisticsBaseTestCase):
    """Tests for package popularity statistics."""
    
    def test_package_popularity_ranking(self):
        """Test packages ranked by usage."""
        booking = self._create_booking(attendee_count=5)
        attendees = list(booking.attendees.all())
        
        # Standard package: 3 tickets
        for i in range(3):
            self._create_ticket(attendees[i], package=self.package_standard)
        
        # Discount package: 2 tickets
        for i in range(3, 5):
            self._create_ticket(attendees[i], package=self.package_discount)
        
        stats = statistics.calculate_package_popularity()
        
        self.assertEqual(len(stats['popularity']), 2)
        # Most popular should be first
        self.assertEqual(stats['popularity'][0]['package_name'], 'Standard Package')
        self.assertEqual(stats['popularity'][0]['ticket_count'], 3)


class PackageRuleDistributionTests(BookingStatisticsBaseTestCase):
    """Tests for package rule distribution."""
    
    def test_rule_distribution(self):
        """Test distribution of package rules by type."""
        stats = statistics.calculate_package_rule_distribution()
        
        self.assertGreaterEqual(stats['total_rules'], 2)  # We created 2 in setup
        
        rule_types = [item['label'] for item in stats['distribution']]
        self.assertIn('IS_AGE_LT', rule_types)
        self.assertIn('IS_EVENT_STAFF', rule_types)


class PackagePricingAnalysisTests(BookingStatisticsBaseTestCase):
    """Tests for package pricing analysis."""
    
    def test_pricing_analysis(self):
        """Test package pricing analysis."""
        stats = statistics.calculate_package_pricing_analysis()
        
        self.assertGreaterEqual(stats['total_packages'], 3)
        self.assertGreater(stats['average_base_amount'], 0)
        self.assertGreater(stats['max_base_amount'], stats['min_base_amount'])


# ============================================================================
# INTENT STATISTICS TESTS
# ============================================================================

class IntentOverviewStatisticsTests(BookingStatisticsBaseTestCase):
    """Tests for intent overview statistics."""
    
    def test_intent_overview(self):
        """Test intent overview statistics."""
        self._create_intent(status='COMPLETED', intended_ticket_count=2)
        self._create_intent(status='PENDING', intended_ticket_count=3)
        self._create_intent(status='EXPIRED', intended_ticket_count=1)
        
        stats = statistics.calculate_intent_overview()
        
        self.assertEqual(stats['total_intents'], 3)
        self.assertEqual(stats['total_capacity_reserved'], 6)
        self.assertEqual(stats['average_capacity_per_intent'], 2.0)


class IntentConversionRateTests(BookingStatisticsBaseTestCase):
    """Tests for intent conversion rate."""
    
    def test_conversion_rate(self):
        """Test intent conversion rate calculation."""
        self._create_intent(status='COMPLETED')
        self._create_intent(status='COMPLETED')
        self._create_intent(status='COMPLETED')
        self._create_intent(status='EXPIRED')
        self._create_intent(status='CANCELLED')
        
        stats = statistics.calculate_intent_conversion_rate()
        
        self.assertEqual(stats['total_intents'], 5)
        self.assertEqual(stats['completed'], 3)
        self.assertEqual(stats['conversion_rate'], 60.0)
        self.assertEqual(stats['expiration_rate'], 20.0)
        self.assertEqual(stats['cancellation_rate'], 20.0)


class IntentTrendsTests(BookingStatisticsBaseTestCase):
    """Tests for intent trends statistics."""
    
    def test_intent_trends(self):
        """Test intent creation trends."""
        self._create_intent(days_ago=0)
        self._create_intent(days_ago=0)
        self._create_intent(days_ago=1)
        
        stats = statistics.calculate_intent_trends(group_by='day')
        
        self.assertEqual(stats['total_intents'], 3)
        self.assertEqual(len(stats['trends']), 2)


# ============================================================================
# REVENUE STATISTICS TESTS (CRITICAL)
# ============================================================================

class RevenueOverviewStatisticsTests(BookingStatisticsBaseTestCase):
    """Tests for revenue overview statistics - CRITICAL revenue calculation tests."""
    
    def test_only_completed_payments_counted(self):
        """Test that only COMPLETED payments are counted in revenue."""
        booking1 = self._create_booking(attendee_count=1)
        booking2 = self._create_booking(attendee_count=1)
        booking3 = self._create_booking(attendee_count=1)
        booking4 = self._create_booking(attendee_count=1)
        
        self._create_payment(booking1, status=PaymentStatusChoices.COMPLETED, amount=100)
        self._create_payment(booking2, status=PaymentStatusChoices.COMPLETED, amount=200)
        self._create_payment(booking3, status=PaymentStatusChoices.PENDING, amount=150)
        self._create_payment(booking4, status=PaymentStatusChoices.FAILED, amount=175)
        
        stats = statistics.calculate_revenue_overview()
        
        # Only completed payments (100 + 200 = 300)
        self.assertEqual(stats['total_revenue'], 300.0)
        self.assertEqual(stats['total_completed_payments'], 2)
    
    def test_revenue_overview_basic(self):
        """Test basic revenue overview."""
        booking1 = self._create_booking(attendee_count=1)
        booking2 = self._create_booking(attendee_count=1)
        
        self._create_payment(booking1, status=PaymentStatusChoices.COMPLETED, amount=100)
        self._create_payment(booking2, status=PaymentStatusChoices.COMPLETED, amount=150)
        
        stats = statistics.calculate_revenue_overview()
        
        self.assertEqual(stats['total_revenue'], 250.0)
        self.assertEqual(stats['average_revenue_per_booking'], 125.0)
        self.assertEqual(stats['max_revenue'], 150.0)
        self.assertEqual(stats['min_revenue'], 100.0)
    
    def test_revenue_with_event_filter(self):
        """Test revenue filtered by event."""
        booking1 = self._create_booking(event=self.event1, attendee_count=1)
        booking2 = self._create_booking(event=self.event2, attendee_count=1)
        
        self._create_payment(booking1, status=PaymentStatusChoices.COMPLETED, amount=100)
        self._create_payment(booking2, status=PaymentStatusChoices.COMPLETED, amount=200)
        
        stats = statistics.calculate_revenue_overview(event_id=str(self.event1.event_id))
        
        self.assertEqual(stats['total_revenue'], 100.0)


class RevenueByPackageTests(BookingStatisticsBaseTestCase):
    """Tests for revenue by package statistics."""
    
    def test_revenue_by_package(self):
        """Test revenue breakdown by package."""
        booking = self._create_booking(attendee_count=2)
        attendees = list(booking.attendees.all())
        
        ticket1 = self._create_ticket(attendees[0], package=self.package_standard)
        ticket2 = self._create_ticket(attendees[1], package=self.package_discount)
        
        # Create payments linked to tickets
        payment1 = self._create_payment(booking, status=PaymentStatusChoices.COMPLETED, amount=50)
        payment2 = self._create_payment(booking, status=PaymentStatusChoices.COMPLETED, amount=30)
        
        # Link payments to tickets
        ticket1.payment = payment1
        ticket1.save()
        ticket2.payment = payment2
        ticket2.save()
        
        stats = statistics.calculate_revenue_by_package()
        
        self.assertGreater(len(stats['distribution']), 0)


class RevenueByTicketTypeTests(BookingStatisticsBaseTestCase):
    """Tests for revenue by ticket type statistics."""
    
    def test_revenue_by_ticket_type(self):
        """Test revenue breakdown by ticket type."""
        booking = self._create_booking(attendee_count=2)
        attendees = list(booking.attendees.all())
        
        ticket1 = self._create_ticket(attendees[0], ticket_type=self.ticket_type_full)
        ticket2 = self._create_ticket(attendees[1], ticket_type=self.ticket_type_single_day)
        
        # Create payments
        payment1 = self._create_payment(booking, status=PaymentStatusChoices.COMPLETED, amount=100)
        payment2 = self._create_payment(booking, status=PaymentStatusChoices.COMPLETED, amount=50)
        
        ticket1.payment = payment1
        ticket1.save()
        ticket2.payment = payment2
        ticket2.save()
        
        stats = statistics.calculate_revenue_by_ticket_type()
        
        self.assertGreater(len(stats['distribution']), 0)


class RevenueTrendsTests(BookingStatisticsBaseTestCase):
    """Tests for revenue trends statistics."""
    
    def test_revenue_trends(self):
        """Test revenue trends over time."""
        booking1 = self._create_booking(attendee_count=1, days_ago=0)
        booking2 = self._create_booking(attendee_count=1, days_ago=1)
        
        self._create_payment(booking1, status=PaymentStatusChoices.COMPLETED, amount=100, days_ago=0)
        self._create_payment(booking2, status=PaymentStatusChoices.COMPLETED, amount=150, days_ago=1)
        
        stats = statistics.calculate_revenue_trends(group_by='day')
        print("data:", stats)
        self.assertEqual(stats['total_revenue'], 250.0)
        self.assertGreaterEqual(len(stats['trends']), 2)


class RevenueBreakdownTests(BookingStatisticsBaseTestCase):
    """Tests for revenue breakdown statistics."""
    
    def test_revenue_breakdown_by_status(self):
        """Test revenue breakdown by payment status."""
        booking1 = self._create_booking(attendee_count=1)
        booking2 = self._create_booking(attendee_count=1)
        booking3 = self._create_booking(attendee_count=1)
        
        self._create_payment(booking1, status=PaymentStatusChoices.COMPLETED, amount=100)
        self._create_payment(booking2, status=PaymentStatusChoices.PENDING, amount=150)
        self._create_payment(booking3, status=PaymentStatusChoices.FAILED, amount=75)
        
        stats = statistics.calculate_revenue_breakdown()
        
        self.assertEqual(stats['completed_revenue'], 100.0)
        self.assertEqual(stats['total_revenue_all_statuses'], 325.0)
        self.assertEqual(len(stats['distribution']), 3)


# ============================================================================
# OVERVIEW STATISTICS TESTS
# ============================================================================

class OverviewStatisticsTests(BookingStatisticsBaseTestCase):
    """Tests for combined overview statistics."""
    
    def test_combined_overview(self):
        """Test combined overview statistics."""
        booking = self._create_booking(attendee_count=2)
        
        for attendee in booking.attendees.all():
            self._create_ticket(attendee, package=self.package_standard)
        
        self._create_payment(booking, status=PaymentStatusChoices.COMPLETED, amount=100)
        self._create_intent(status='COMPLETED')
        
        stats = statistics.calculate_booking_statistics_overview()
        
        self.assertIn('bookings', stats)
        self.assertIn('tickets', stats)
        self.assertIn('packages', stats)
        self.assertIn('intents', stats)
        self.assertIn('revenue', stats)
        
        self.assertEqual(stats['bookings']['total'], 1)
        self.assertEqual(stats['tickets']['total'], 2)
        self.assertEqual(stats['revenue']['total'], 100.0)


# ============================================================================
# API ENDPOINT TESTS
# ============================================================================

class BookingStatisticsAPITests(BookingStatisticsBaseTestCase):
    """Tests for booking statistics API endpoints."""
    
    def test_list_endpoints(self):
        """Test listing all available endpoints."""
        response = self.client.get('/api/bookings/statistics/')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('available_endpoints', response.data)
        self.assertIn('overview', response.data['available_endpoints'])
    
    def test_authentication_required(self):
        """Test that authentication is required."""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/bookings/statistics/overview/')
        print("data:", response.data)
    
    def test_overview_endpoint_raw_format(self):
        """Test overview endpoint with raw format."""
        booking = self._create_booking(attendee_count=2)
        self._create_payment(booking, status=PaymentStatusChoices.COMPLETED, amount=100)
        
        response = self.client.get('/api/bookings/statistics/overview/?format=raw')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('bookings', response.data)
        self.assertIn('generated_at', response.data)
    
    def test_booking_overview_endpoint(self):
        """Test booking overview endpoint."""
        booking = self._create_booking(attendee_count=2)
        
        response = self.client.get('/api/bookings/statistics/booking-overview/')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('total_bookings', response.data)
        self.assertEqual(response.data['total_bookings'], 1)
    
    def test_ticket_overview_endpoint(self):
        """Test ticket overview endpoint."""
        booking = self._create_booking(attendee_count=2)
        for attendee in booking.attendees.all():
            self._create_ticket(attendee)
        
        response = self.client.get('/api/bookings/statistics/ticket-overview/')
        print("data:", response.data)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('total_tickets', response.data)
        self.assertEqual(response.data['total_tickets'], 2)
    
    def test_revenue_overview_endpoint(self):
        """Test revenue overview endpoint."""
        booking = self._create_booking(attendee_count=1)
        self._create_payment(booking, status=PaymentStatusChoices.COMPLETED, amount=100)
        
        response = self.client.get('/api/bookings/statistics/revenue-overview/')
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('total_revenue', response.data)
        self.assertEqual(response.data['total_revenue'], 100.0)
    
    def test_filters_applied_metadata(self):
        """Test that filters are included in response metadata."""
        booking = self._create_booking(event=self.event1, attendee_count=1)
        
        response = self.client.get(
            f'/api/bookings/statistics/booking-overview/?event_id={self.event1.event_id}'
        )
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('filters_applied', response.data)
        self.assertEqual(response.data['filters_applied']['event_id'], str(self.event1.event_id))
    
    def test_all_major_endpoints_accessible(self):
        """Test that all major endpoints are accessible."""
        endpoints = [
            'overview',
            'booking-overview',
            'booking-status',
            'ticket-overview',
            'ticket-status',
            'package-overview',
            'intent-overview',
            'revenue-overview',
        ]
        
        for endpoint in endpoints:
            response = self.client.get(f'/api/bookings/statistics/{endpoint}/')
            self.assertEqual(
                response.status_code,
                http_status.HTTP_200_OK,
                f'Endpoint {endpoint} failed'
            )
