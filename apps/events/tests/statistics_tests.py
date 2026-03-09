"""
Event Statistics API Tests

Comprehensive test suite for event statistics endpoints testing:
- Authentication and permissions
- Raw JSON format responses
- ECharts format responses
- Filtering capabilities (event_id, event_type, organization, status, dates)
- Data accuracy and calculations
- Edge cases (no data, invalid parameters)
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta
from decimal import Decimal

from apps.events.models import (
    Event, EventType, EventStatusChoices, EventStaff, EventReview
)
from apps.organisations.models import Organisation
from apps.bookings.models import Booking, BookingPackage
from apps.bookings.models.ticket import TicketType
from apps.attendee.models import Attendee
from apps.payments.models import Payment, PaymentStatusChoices
from apps.products.models import Product
from apps.users.models import CommunityUser as AppUser
from datetime import date
from djmoney.money import Money

User = get_user_model()


class EventStatisticsBaseTestCase(TestCase):
    """Base test case with common setup for event statistics tests."""
    
    def setUp(self):
        """Set up test data including events, bookings, payments, and reviews."""
        self.client = APIClient()
        
        # Create users
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.staff_user = User.objects.create_user(
            username='staffuser',
            email='staffuser@example.com',
            password='testpass123',
            is_staff=True
        )
        
        # Create organizations
        self.org1 = Organisation.objects.create(
            title='Organization A',
            description='First test organization',
            created_by=self.user
        )
        
        self.org2 = Organisation.objects.create(
            title='Organization B',
            description='Second test organization',
            created_by=self.user
        )
        
        # Create event types
        self.workshop_type = EventType.objects.create(
            title='Workshop',
            code='WORK',
            description='Workshop events',
            created_by=self.user
        )
        
        self.conference_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            description='Conference events',
            created_by=self.user
        )
        
        # Create events with various statuses - PAST
        self.completed_event = self._create_event(
            title='Completed Workshop',
            event_type=self.workshop_type,
            organization=self.org1,
            status=EventStatusChoices.COMPLETED,
            days_offset=-30,
            duration_days=2,
            max_attendance=50
        )
        
        # PRESENT - Open events
        self.open_event1 = self._create_event(
            title='Open Conference',
            event_type=self.conference_type,
            organization=self.org1,
            status=EventStatusChoices.OPEN,
            days_offset=10,
            duration_days=3,
            max_attendance=100
        )
        
        self.open_event2 = self._create_event(
            title='Open Workshop',
            event_type=self.workshop_type,
            organization=self.org2,
            status=EventStatusChoices.OPEN,
            days_offset=15,
            duration_days=1,
            max_attendance=30
        )
        
        # FUTURE - Published events
        self.published_event = self._create_event(
            title='Published Seminar',
            event_type=self.workshop_type,
            organization=self.org1,
            status=EventStatusChoices.PUBLISHED,
            days_offset=30,
            duration_days=1,
            max_attendance=40
        )
        
        # Cancelled event
        self.cancelled_event = self._create_event(
            title='Cancelled Event',
            event_type=self.conference_type,
            organization=self.org2,
            status=EventStatusChoices.CANCELLED,
            days_offset=20,
            duration_days=2,
            max_attendance=60
        )
        
        # Create attendees (will link to bookings later)
        self.attendee1 = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@example.com',
            event=self.open_event1,
            date_of_birth=date(1990, 1, 1),
            defined_by=self.user,
            user=self.user
        )
        
        self.attendee2 = Attendee.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@example.com',
            event=self.open_event1,
            date_of_birth=date(1992, 5, 15),
            defined_by=self.user,
            user=self.user
        )
        
        self.attendee3 = Attendee.objects.create(
            first_name='Bob',
            last_name='Johnson',
            email='bob@example.com',
            event=self.open_event2,
            date_of_birth=date(1988, 8, 20),
            defined_by=self.user,
            user=self.user
        )
        
        # Create ticket types first (required by BookingPackage)
        self.ticket_type1 = TicketType.objects.create(
            event=self.open_event1,
            title='VIP Ticket',
            created_by=self.user
        )
        
        self.ticket_type2 = TicketType.objects.create(
            event=self.open_event1,
            title='General Ticket',
            created_by=self.user
        )
        
        self.ticket_type3 = TicketType.objects.create(
            event=self.open_event2,
            title='Standard Ticket',
            created_by=self.user
        )
        
        # Create booking packages for events
        self.package1 = BookingPackage.objects.create(
            event=self.open_event1,
            name='VIP Package',
            description='VIP access',
            base_amount=Money(500, 'GBP'),
            ticket_type=self.ticket_type1,
            created_by=self.user
        )
        
        self.package2 = BookingPackage.objects.create(
            event=self.open_event1,
            name='General Package',
            description='General admission',
            base_amount=Money(200, 'GBP'),
            ticket_type=self.ticket_type2,
            created_by=self.user
        )
        
        self.package3 = BookingPackage.objects.create(
            event=self.open_event2,
            name='Standard Package',
            description='Standard access',
            base_amount=Money(150, 'GBP'),
            ticket_type=self.ticket_type3,
            created_by=self.user
        )
        
        # Create bookings (all bookings are confirmed by definition)
        self.booking1 = Booking.objects.create(
            event=self.open_event1,
            made_by=self.user
        )
        
        self.booking2 = Booking.objects.create(
            event=self.open_event1,
            made_by=self.user
        )
        
        self.booking3 = Booking.objects.create(
            event=self.open_event2,
            made_by=self.user
        )
        
        self.booking4 = Booking.objects.create(
            event=self.completed_event,
            made_by=self.user
        )
        
        # Link attendees to bookings (Attendee.booking FK)
        self.attendee1.booking = self.booking1
        self.attendee1.save()
        
        self.attendee2.booking = self.booking2
        self.attendee2.save()
        
        self.attendee3.booking = self.booking3
        self.attendee3.save()
        
        # Create payments (revenue tracking)
        self.payment1 = Payment.objects.create(
            user=self.user,
            event=self.open_event1,
            base_amount=Money(500, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        self.payment1.target = self.booking1
        self.payment1.save()
        
        self.payment2 = Payment.objects.create(
            user=self.user,
            event=self.open_event1,
            base_amount=Money(200, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        self.payment2.target = self.booking2
        self.payment2.save()
        
        self.payment3 = Payment.objects.create(
            user=self.user,
            event=self.open_event2,
            base_amount=Money(150, 'GBP'),
            status=PaymentStatusChoices.PENDING
        )
        self.payment3.target = self.booking3
        self.payment3.save()
        
        self.payment4 = Payment.objects.create(
            user=self.user,
            event=self.completed_event,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        self.payment4.target = self.booking4
        self.payment4.save()
        
        # Create event staff
        self.staff1 = EventStaff.objects.create(
            event=self.open_event1,
            user=self.staff_user,
            assigned_by=self.user
        )
        
        self.staff2 = EventStaff.objects.create(
            event=self.completed_event,
            user=self.staff_user,
            assigned_by=self.user
        )
        
        # Create reviews
        self.review1 = EventReview.objects.create(
            event=self.completed_event,
            user=self.user,
            rating=5,
            comment='Excellent event!',
            approved=True
        )
        
        self.review2 = EventReview.objects.create(
            event=self.completed_event,
            user=self.staff_user,
            rating=4,
            comment='Very good',
            approved=True
        )
        
        # Authenticate by default
        self.client.force_authenticate(user=self.user)
    
    def _create_event(self, title, event_type, organization, status, 
                     days_offset, duration_days, max_attendance):
        """Helper to create an event with specific timing."""
        start_time = timezone.now() + timedelta(days=days_offset)
        end_time = start_time + timedelta(days=duration_days)
        
        return Event.objects.create(
            title=title,
            display_code=title.replace(' ', '').upper()[:10],
            created_by=self.user,
            event_type=event_type,
            start_datetime=start_time,
            end_datetime=end_time,
            organisation=organization,
            status=status,
            maximum_attendance=max_attendance
        )


class OverviewStatisticsTest(EventStatisticsBaseTestCase):
    """Test the overview statistics endpoint."""
    
    def test_overview_authenticated(self):
        """Test overview endpoint requires authentication."""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/event/statistics/overview/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_overview_raw_format(self):
        """Test overview returns correct data in raw format."""
        response = self.client.get('/api/event/statistics/overview/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('total_events', data)
        self.assertIn('active_events', data)
        self.assertIn('upcoming_events', data)
        self.assertIn('completed_events', data)
        self.assertIn('total_revenue', data)
        self.assertIn('total_bookings', data)
        
        # Verify counts
        self.assertEqual(data['total_events'], 5)  # All non-deleted events
        self.assertEqual(data['completed_events'], 1)
        self.assertGreater(data['total_bookings'], 0)
    
    def test_overview_echarts_format(self):
        """Test overview returns ECharts configuration."""
        response = self.client.get('/api/event/statistics/overview/?format=echarts')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('dashboard', data)
        self.assertIn('metrics', data['dashboard'])
        self.assertIn('charts', data['dashboard'])
    
    def test_overview_with_organization_filter(self):
        """Test overview with organization filter."""
        response = self.client.get(
            f'/api/event/statistics/overview/?organization_id={self.org1.id}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('filters_applied', data)
        self.assertEqual(data['filters_applied']['organization_id'], self.org1.id)
        
        # Should have fewer events than total
        self.assertLess(data['total_events'], 5)
    
    def test_overview_with_date_filter(self):
        """Test overview with date range filter."""
        date_from = (timezone.now() + timedelta(days=5)).date().isoformat()
        date_to = (timezone.now() + timedelta(days=20)).date().isoformat()
        
        response = self.client.get(
            f'/api/event/statistics/overview/?date_from={date_from}&date_to={date_to}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('filters_applied', data)


class StatusDistributionTest(EventStatisticsBaseTestCase):
    """Test the status distribution endpoint."""
    
    def test_status_distribution_raw(self):
        """Test status distribution returns correct counts."""
        response = self.client.get('/api/event/statistics/status-distribution/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('distribution', data)
        self.assertIn('total_events', data)
        self.assertEqual(data['total_events'], 5)
        
        # Verify distribution structure
        distribution = data['distribution']
        self.assertIsInstance(distribution, list)
        self.assertGreater(len(distribution), 0)
        
        # Each item should have label, code, value, percentage
        for item in distribution:
            self.assertIn('label', item)
            self.assertIn('code', item)
            self.assertIn('value', item)
            self.assertIn('percentage', item)
        
        # Find OPEN status
        open_status = next((d for d in distribution if d['code'] == 'OPEN'), None)
        self.assertIsNotNone(open_status)
        self.assertEqual(open_status['value'], 2)  # We created 2 open events
    
    def test_status_distribution_echarts(self):
        """Test status distribution returns ECharts donut chart."""
        response = self.client.get('/api/event/statistics/status-distribution/?format=echarts')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('title', data)
        self.assertIn('series', data)
        self.assertEqual(data['series'][0]['type'], 'pie')


class TypeDistributionTest(EventStatisticsBaseTestCase):
    """Test the type distribution endpoint."""
    
    def test_type_distribution_raw(self):
        """Test type distribution returns correct counts."""
        response = self.client.get('/api/event/statistics/type-distribution/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('distribution', data)
        self.assertIn('total_events', data)
        
        # Verify we have both types
        distribution = data['distribution']
        workshop_count = next((d['value'] for d in distribution if d['label'] == 'Workshop'), 0)
        conference_count = next((d['value'] for d in distribution if d['label'] == 'Conference'), 0)
        
        self.assertGreater(workshop_count, 0)
        self.assertGreater(conference_count, 0)
    
    def test_type_distribution_with_status_filter(self):
        """Test type distribution with status filter."""
        response = self.client.get(
            f'/api/event/statistics/type-distribution/?status={EventStatusChoices.OPEN}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('filters_applied', data)
        self.assertEqual(data['total_events'], 2)  # 2 open events


class OrganizationDistributionTest(EventStatisticsBaseTestCase):
    """Test the organization distribution endpoint."""
    
    def test_organization_distribution_raw(self):
        """Test organization distribution returns correct counts."""
        response = self.client.get('/api/event/statistics/organization-distribution/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('distribution', data)
        self.assertIn('total_events', data)
        
        # Verify both organizations are represented
        distribution = data['distribution']
        org_labels = [d['label'] for d in distribution]
        self.assertIn('Organization A', org_labels)
        self.assertIn('Organization B', org_labels)
    
    def test_organization_distribution_limit(self):
        """Test organization distribution respects limit parameter."""
        response = self.client.get('/api/event/statistics/organization-distribution/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertLessEqual(len(data['distribution']), 1)


class UpcomingEventsTest(EventStatisticsBaseTestCase):
    """Test the upcoming events endpoint."""
    
    def test_upcoming_events_default_timeframe(self):
        """Test upcoming events with default 30-day timeframe."""
        response = self.client.get('/api/event/statistics/upcoming/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('events', data)
        self.assertIn('total_upcoming', data)
        self.assertIn('date_range', data)
        
        # Should include events within 30 days
        self.assertGreater(data['total_upcoming'], 0)
        
        # Each event should have required fields
        for event in data['events']:
            self.assertIn('event_id', event)
            self.assertIn('title', event)
            self.assertIn('start_datetime', event)
            self.assertIn('type', event)
            self.assertIn('status', event)
    
    def test_upcoming_events_custom_timeframe(self):
        """Test upcoming events with custom days_ahead."""
        response = self.client.get('/api/event/statistics/upcoming/?days_ahead=20')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        # Events beyond 20 days should be excluded
        days_20_ahead = timezone.now() + timedelta(days=20)
        
        for event in data['events']:
            event_start = timezone.datetime.fromisoformat(event['start_datetime'].replace('Z', '+00:00'))
            self.assertLessEqual(event_start, days_20_ahead)
    
    def test_upcoming_events_by_type(self):
        """Test upcoming events filtered by type."""
        response = self.client.get(
            f'/api/event/statistics/upcoming/?event_type_id={self.workshop_type.id}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        # All returned events should be workshops
        for event in data['events']:
            self.assertEqual(event['type'], 'Workshop')


class RevenueOverviewTest(EventStatisticsBaseTestCase):
    """Test the revenue overview endpoint."""
    
    def test_revenue_overview_raw(self):
        """Test revenue overview returns correct totals."""
        response = self.client.get('/api/event/statistics/revenue-overview/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('total_revenue', data)
        self.assertIn('booking_revenue', data)
        self.assertIn('product_revenue', data)
        self.assertIn('donation_revenue', data)
        self.assertIn('breakdown', data)
        
        # Verify numeric values
        total = Decimal(str(data['total_revenue']))
        booking = Decimal(str(data['booking_revenue']))
        
        self.assertGreater(total, 0)
        self.assertGreater(booking, 0)
        
        # Total should be sum of parts
        product = Decimal(str(data['product_revenue']))
        donation = Decimal(str(data['donation_revenue']))
        self.assertEqual(total, booking + product + donation)
    
    def test_revenue_overview_echarts(self):
        """Test revenue overview returns ECharts pie chart."""
        response = self.client.get('/api/event/statistics/revenue-overview/?format=echarts')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('title', data)
        self.assertIn('series', data)
        self.assertIn('color', data)
        
        # Should have custom revenue colors
        self.assertIsInstance(data['color'], list)
    
    def test_revenue_overview_by_event(self):
        """Test revenue overview filtered by specific event."""
        response = self.client.get(
            f'/api/event/statistics/revenue-overview/?event_id={self.open_event1.id}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        # Revenue should only include this event's payments
        # payment1 (500) + payment2 (200) = 700
        expected_revenue = Decimal('700.00')
        actual_revenue = Decimal(str(data['total_revenue']))
        self.assertEqual(actual_revenue, expected_revenue)


class RevenueByEventTest(EventStatisticsBaseTestCase):
    """Test the revenue by event endpoint."""
    
    def test_revenue_by_event_raw(self):
        """Test revenue by event returns correct data."""
        response = self.client.get('/api/event/statistics/revenue-by-event/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('events', data)
        self.assertIn('total_events', data)
        
        # Each event should have revenue data
        for event in data['events']:
            self.assertIn('event_id', event)
            self.assertIn('title', event)
            self.assertIn('total_revenue', event)
            self.assertIn('booking_revenue', event)
    
    def test_revenue_by_event_sorting(self):
        """Test revenue by event can be sorted."""
        response = self.client.get(
            '/api/event/statistics/revenue-by-event/?sort_by=total_revenue&limit=5'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        events = data['events']
        
        # Verify descending order
        revenues = [float(e['total_revenue']) for e in events]
        self.assertEqual(revenues, sorted(revenues, reverse=True))
    
    def test_revenue_by_event_breakdown(self):
        """Test revenue by event with breakdown."""
        response = self.client.get(
            '/api/event/statistics/revenue-by-event/?show_breakdown=true'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        # When show_breakdown is echarts, should get stacked chart
        # In raw format, should have breakdown fields
        for event in data['events']:
            self.assertIn('booking_revenue', event)
            self.assertIn('product_revenue', event)
            self.assertIn('donation_revenue', event)


class PaymentStatusDistributionTest(EventStatisticsBaseTestCase):
    """Test the payment status distribution endpoint."""
    
    def test_payment_status_distribution_raw(self):
        """Test payment status distribution returns correct counts."""
        response = self.client.get('/api/event/statistics/payment-status/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('distribution', data)
        self.assertIn('total_bookings', data)
        self.assertIn('total_amount', data)
        
        # Should have different payment statuses
        distribution = data['distribution']
        self.assertGreater(len(distribution), 0)
        
        # Verify structure
        for item in distribution:
            self.assertIn('label', item)
            self.assertIn('count', item)
            self.assertIn('amount', item)
        
        # We created 3 completed and 1 pending payment
        self.assertEqual(data['total_payments'], 4)


class CapacityUtilizationTest(EventStatisticsBaseTestCase):
    """Test the capacity utilization endpoint."""
    
    def test_capacity_utilization_raw(self):
        """Test capacity utilization calculates correctly."""
        response = self.client.get('/api/event/statistics/capacity-utilization/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('events', data)
        self.assertIn('average_utilization', data)
        
        # Each event should have utilization data
        for event in data['events']:
            self.assertIn('event_id', event)
            self.assertIn('title', event)
            self.assertIn('registered_count', event)
            self.assertIn('maximum_attendance', event)
            self.assertIn('utilization_percentage', event)
            
            # Verify calculation
            if event['maximum_attendance'] > 0:
                expected_util = (event['registered_count'] / event['maximum_attendance']) * 100
                self.assertAlmostEqual(event['utilization_percentage'], expected_util, places=1)
    
    def test_capacity_utilization_echarts(self):
        """Test capacity utilization returns color-coded bar chart."""
        response = self.client.get('/api/event/statistics/capacity-utilization/?format=echarts')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('series', data)
        
        # Should have color-coded bars based on utilization
        series_data = data['series'][0]['data']
        for item in series_data:
            self.assertIn('itemStyle', item)
            self.assertIn('color', item['itemStyle'])


class RegistrationTrendsTest(EventStatisticsBaseTestCase):
    """Test the registration trends endpoint."""
    
    def test_registration_trends_by_month(self):
        """Test registration trends grouped by month."""
        response = self.client.get('/api/event/statistics/registration-trends/?period=month')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('trends', data)
        self.assertIn('total_registrations', data)
        self.assertIn('period', data)
        self.assertEqual(data['period'], 'month')
        
        # Each trend point should have period and count
        for trend in data['trends']:
            self.assertIn('period', trend)
            self.assertIn('count', trend)
    
    def test_registration_trends_cumulative(self):
        """Test registration trends with cumulative data."""
        response = self.client.get(
            '/api/event/statistics/registration-trends/?period=week&cumulative=true'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        
        # Should include cumulative field
        for trend in data['trends']:
            self.assertIn('cumulative', trend)
        
        # Cumulative should be non-decreasing
        cumulative_values = [t['cumulative'] for t in data['trends']]
        for i in range(1, len(cumulative_values)):
            self.assertGreaterEqual(cumulative_values[i], cumulative_values[i-1])


class ReviewStatisticsTest(EventStatisticsBaseTestCase):
    """Test the review statistics endpoint."""
    
    def test_review_statistics_raw(self):
        """Test review statistics returns correct data."""
        response = self.client.get('/api/event/statistics/reviews/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('total_reviews', data)
        self.assertIn('average_rating', data)
        self.assertIn('rating_distribution', data)
        self.assertIn('approval_status', data)
        
        # Verify average rating calculation
        self.assertEqual(data['total_reviews'], 2)
        expected_avg = (5 + 4) / 2
        self.assertAlmostEqual(data['average_rating'], expected_avg, places=1)
        
        # Rating distribution should cover 1-5
        distribution = data['rating_distribution']
        ratings = {item['rating'] for item in distribution}
        self.assertIn(4, ratings)
        self.assertIn(5, ratings)
    
    def test_review_statistics_echarts(self):
        """Test review statistics returns rating bar chart."""
        response = self.client.get('/api/event/statistics/reviews/?format=echarts')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('title', data)
        self.assertIn('series', data)
        
        # Should show average in subtitle
        if 'subtext' in data['title']:
            self.assertIn('Average', data['title']['subtext'])


class StaffAllocationTest(EventStatisticsBaseTestCase):
    """Test the staff allocation endpoint."""
    
    def test_staff_allocation_raw(self):
        """Test staff allocation returns correct data."""
        response = self.client.get('/api/event/statistics/staff-allocation/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('events', data)
        self.assertIn('total_staff_assignments', data)
        self.assertIn('average_staff_per_event', data)
        
        # Each event should have staff count
        for event in data['events']:
            self.assertIn('event_id', event)
            self.assertIn('event_title', event)
            self.assertIn('staff_count', event)
        
        # Verify total
        self.assertEqual(data['total_staff_assignments'], 2)  # We created 2 staff assignments


class BookingPackagePerformanceTest(EventStatisticsBaseTestCase):
    """Test the booking package performance endpoint."""
    
    def test_booking_package_performance_raw(self):
        """Test booking package performance returns correct data."""
        response = self.client.get('/api/event/statistics/booking-packages/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('packages', data)
        self.assertIn('total_packages', data)
        self.assertIn('total_bookings', data)
        self.assertIn('total_revenue', data)
        
        # Each package should have performance data
        for package in data['packages']:
            self.assertIn('package_id', package)
            self.assertIn('package_name', package)
            self.assertIn('event_title', package)
            self.assertIn('bookings', package)
            self.assertIn('revenue', package)
        
        # Find VIP package
        vip_package = next((p for p in data['packages'] if p['package_name'] == 'VIP Package'), None)
        self.assertIsNotNone(vip_package)
        self.assertEqual(vip_package['bookings'], 1)
        self.assertEqual(float(vip_package['revenue']), 500.00)
    
    def test_booking_package_performance_echarts(self):
        """Test booking package performance returns dual-axis chart."""
        response = self.client.get('/api/event/statistics/booking-packages/?format=echarts')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('series', data)
        self.assertIn('yAxis', data)
        
        # Should have two y-axes (bookings and revenue)
        self.assertEqual(len(data['yAxis']), 2)
        
        # Should have bar and line series
        series_types = [s['type'] for s in data['series']]
        self.assertIn('bar', series_types)
        self.assertIn('line', series_types)


class StatisticsFilteringTest(EventStatisticsBaseTestCase):
    """Test filtering capabilities across all statistics endpoints."""
    
    def test_filter_by_multiple_parameters(self):
        """Test combining multiple filters."""
        response = self.client.get(
            f'/api/event/statistics/overview/?'
            f'organization_id={self.org1.id}&'
            f'status={EventStatusChoices.OPEN}&'
            f'event_type_id={self.conference_type.id}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertIn('filters_applied', data)
        
        # Should have significantly fewer events
        self.assertEqual(data['total_events'], 1)  # Only open_event1 matches all filters
    
    def test_invalid_parameters_handled_gracefully(self):
        """Test that invalid parameters don't crash endpoints."""
        response = self.client.get(
            '/api/event/statistics/overview/?organization_id=99999'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should return zero/empty results, not error
        data = response.data
        self.assertEqual(data['total_events'], 0)


class StatisticsEdgeCasesTest(EventStatisticsBaseTestCase):
    """Test edge cases and error handling."""
    
    def test_no_data_returns_empty_results(self):
        """Test endpoints with filters that match no data."""
        # Filter for non-existent organization
        response = self.client.get('/api/event/statistics/overview/?organization_id=99999')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertEqual(data['total_events'], 0)
    
    def test_format_parameter_case_insensitive(self):
        """Test format parameter accepts various cases."""
        for format_value in ['echarts', 'ECHARTS', 'ECharts']:
            response = self.client.get(f'/api/event/statistics/overview/?format={format_value}')
            # Should not error (though may treat as raw if not exactly 'echarts')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_invalid_date_format(self):
        """Test invalid date format is handled."""
        response = self.client.get('/api/event/statistics/overview/?date_from=invalid-date')
        # Should either return 400 or ignore invalid date
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


class StatisticsPermissionsTest(EventStatisticsBaseTestCase):
    """Test permission requirements for statistics endpoints."""
    
    def test_all_endpoints_require_authentication(self):
        """Test all statistics endpoints require authentication."""
        self.client.force_authenticate(user=None)
        
        endpoints = [
            'overview',
            'status-distribution',
            'type-distribution',
            'organization-distribution',
            'upcoming',
            'revenue-overview',
            'revenue-by-event',
            'payment-status',
            'capacity-utilization',
            'registration-trends',
            'reviews',
            'staff-allocation',
            'booking-packages',
        ]
        
        for endpoint in endpoints:
            response = self.client.get(f'/api/event/statistics/{endpoint}/')
            self.assertEqual(
                response.status_code,
                status.HTTP_401_UNAUTHORIZED,
                f"Endpoint {endpoint} should require authentication"
            )
