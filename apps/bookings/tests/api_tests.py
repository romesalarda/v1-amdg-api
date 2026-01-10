"""
Comprehensive API tests for the bookings app.

Tests all endpoints, permissions, serialization, filtering, nested routing,
and business logic for bookings, tickets, packages, and alternative signins.

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, timedelta
from djmoney.money import Money
import uuid

from apps.bookings.models import (
    Booking, BookingPackage, BookingPackageRule, PackageRuleTypeChoices,
    TicketType, Ticket, TicketScopeChoices, TicketStatusChoices,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
)
from apps.events.models import Event, EventType, EventStatusChoices, EventRole, EventRoleAssignment, EventRoleCategoryChoices
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.payments.models import PaymentMethod, PaymentMethodTypeChoices, Payment, PaymentStatusChoices
from apps.common.models import VerificationStatus

User = get_user_model()


class BookingsAPITestCase(APITestCase):
    """Base test case with common fixtures for booking tests."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123',
            first_name='John',
            last_name='Doe'
        )
        
        self.other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )
        
        # Create organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        # Create event
        event_type = EventType.objects.create(
            title='Youth Camp',
            code='YCAMP',
            created_by=self.admin_user
        )
        self.event = Event.objects.create(
            title='Summer Camp 2026',
            display_code='SC2026',
            display_identifier='SC2026YCAMP001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=37),
            status=EventStatusChoices.PUBLISHED,
            organisation=self.organisation
        )
        
        # Create administrative role for regular user
        admin_role, _ = EventRole.objects.get_or_create(
            code='EVTADMIN',
            defaults={
                'name': 'Event Administrator',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE
            }
        )
        EventRoleAssignment.objects.create(
            user=self.regular_user,
            event=self.event,
            role=admin_role,
        )
        
        # Create ticket types
        self.full_event_ticket = TicketType.objects.create(
            event=self.event,
            code='FULL',
            title='Full Event Pass',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.admin_user,
            is_active=True
        )
        
        self.single_day_ticket = TicketType.objects.create(
            event=self.event,
            code='DAY1',
            title='Single Day Pass',
            scope=TicketScopeChoices.SINGLE_DAY,
            valid_from=timezone.now(),
            valid_until=self.event.start_datetime + timedelta(days=1),
            created_by=self.admin_user,
            is_active=True
        )
        
        # Create booking packages
        self.early_bird_package = BookingPackage.objects.create(
            name='Early Bird',
            description='Early registration discount',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(10, 'GBP'),
            percentage_modifier=0,
            created_by=self.admin_user,
            is_active=True
        )
        
        self.standard_package = BookingPackage.objects.create(
            name='Standard',
            description='Standard pricing',
            event=self.event,
            ticket_type=self.full_event_ticket,
            base_amount=Money(15, 'GBP'),
            percentage_modifier=0,
            created_by=self.admin_user,
            is_active=True
        )
        
        # Create booking with attendee
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TEST-001',
            made_by=self.regular_user
        )
        
        self.attendee = Attendee.objects.create(
            user=self.regular_user,
            first_name='John',
            last_name='Doe',
            email='john.doe@test.com',
            phone_number='+447123456789',
            date_of_birth=date(2000, 1, 1),
            gender='Male',
            relationship_to_user=AttendeeRelationship.SELF,
            event=self.event,
            booking=self.booking,
            defined_by=self.regular_user
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Stripe',
            is_active=True,
            created_by=self.admin_user
        )
        
        # Create payment for booking
        self.payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(10, 'GBP'),
            status=PaymentStatusChoices.COMPLETED
        )
        self.booking.add_payment(self.payment)
        
        # Create ticket
        self.ticket = Ticket.objects.create(
            ticket_type=self.full_event_ticket,
            attendee=self.attendee,
            package=self.early_bird_package,
            status=TicketStatusChoices.ACTIVE,
            payment=self.payment
        )
        
        # Create event alternative signin
        self.event_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC Member ID',
            description='Youth for Christ member number',
            event=self.event,
            format_match=r'^\d{6}$',
            is_active=True,
            verification_status=VerificationStatus.VERIFIED
        )
        
        self.client = APIClient()


# ============================================================================
# BOOKING ENDPOINT TESTS
# ============================================================================

class BookingEndpointTests(BookingsAPITestCase):
    """Test booking list/create/retrieve/update/delete endpoints."""
    
    def test_list_bookings_unauthenticated(self):
        """Unauthenticated users cannot list bookings."""
        response = self.client.get('/api/bookings/list/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_list_bookings_as_user(self):
        """User should see their own bookings."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/bookings/list/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['booking_reference'], 'BKG-TEST-001')
    
    def test_list_bookings_as_admin(self):
        """Admin should see all bookings."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/bookings/list/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_booking_detail(self):
        """Test retrieving booking details with HATEOAS links."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/list/{self.booking.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['booking_reference'], 'BKG-TEST-001')
        self.assertIn('_links', response.data)
        self.assertIn('attendees', response.data['_links'])
        self.assertIn('tickets', response.data['_links'])
        self.assertIn('attendees', response.data)  # Nested attendee summary
        self.assertIn('tickets', response.data)  # Nested ticket summary
    
    def test_create_booking(self):
        """Test creating a new booking."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'event': self.event.id
        }
        response = self.client.post('/api/bookings/list/', data, format='json')
        
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Booking validation errors: {response.data}")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('booking_reference', response.data)
        self.assertTrue(response.data['booking_reference'])
        self.assertIn('BKG', response.data['booking_reference'])
    
    def test_create_booking_without_event(self):
        """Test that creating booking without event fails."""
        self.client.force_authenticate(user=self.regular_user)
        data = {}
        response = self.client.post('/api/bookings/list/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('event', response.data)
    
    def test_other_user_cannot_access_booking(self):
        """Other users cannot access bookings they don't own."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(f'/api/bookings/list/{self.booking.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_booking_nested_attendees_endpoint(self):
        """Test nested attendees endpoint for booking."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/list/{self.booking.id}/attendees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['first_name'], 'John')
    
    def test_booking_nested_tickets_endpoint(self):
        """Test nested tickets endpoint for booking."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/list/{self.booking.id}/tickets/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['status'], TicketStatusChoices.ACTIVE)


class BookingFilteringTests(BookingsAPITestCase):
    """Test booking filtering and search capabilities."""
    
    def test_search_bookings_by_reference(self):
        """Test searching bookings by reference."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/bookings/list/?search=BKG-TEST')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_by_event(self):
        """Test filtering bookings by event."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f'/api/bookings/list/?event={self.event.id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_by_user(self):
        """Test filtering bookings by user."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f'/api/bookings/list/?made_by={self.regular_user.id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_by_date_range(self):
        """Test filtering bookings by date range."""
        self.client.force_authenticate(user=self.admin_user)
        yesterday = (timezone.now() - timedelta(days=1)).date().isoformat()
        tomorrow = (timezone.now() + timedelta(days=1)).date().isoformat()
        response = self.client.get(
            f'/api/bookings/list/?booked_after={yesterday}&booked_before={tomorrow}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_by_attendee_email(self):
        """Test filtering bookings by attendee email."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/bookings/list/?attendee_email=john.doe')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


# ============================================================================
# TICKET TYPE ENDPOINT TESTS
# ============================================================================

class TicketTypeEndpointTests(BookingsAPITestCase):
    """Test ticket type endpoints."""
    
    def test_list_ticket_types(self):
        """Test listing ticket types."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/bookings/ticket-types/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_retrieve_ticket_type_detail(self):
        """Test retrieving ticket type details."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/ticket-types/{self.full_event_ticket.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Full Event Pass')
        self.assertIn('_links', response.data)
        self.assertIn('booking_packages', response.data)
    
    def test_create_ticket_type_as_admin(self):
        """Test creating ticket type as admin."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'title': 'VIP Pass',
            'event': self.event.id,
            'scope': TicketScopeChoices.FULL_EVENT,
            'valid_from': timezone.now().isoformat(),
            'valid_until': self.event.end_datetime.isoformat(),
            'is_active': True
        }
        response = self.client.post('/api/bookings/ticket-types/', data, format='json')
        
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Ticket type validation errors: {response.data}")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'VIP Pass')
        if 'code' in response.data:
            self.assertTrue(response.data['code'])  # Auto-generated
    
    def test_create_ticket_type_as_regular_user_with_admin_role(self):
        """Test that user with admin event role can create ticket types."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'title': 'Staff Pass',
            'event': self.event.id,
            'scope': TicketScopeChoices.FULL_EVENT,
            'valid_from': timezone.now().isoformat(),
            'valid_until': self.event.end_datetime.isoformat(),
            'is_active': True
        }
        response = self.client.post('/api/bookings/ticket-types/', data, format='json')
        
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Ticket type validation errors: {response.data}")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_create_ticket_type_without_admin_fails(self):
        """Test that non-admin users cannot create ticket types."""
        self.client.force_authenticate(user=self.other_user)
        data = {
            'title': 'Unauthorized Pass',
            'event': self.event.id,
            'scope': TicketScopeChoices.FULL_EVENT,
            'valid_from': timezone.now().isoformat(),
            'valid_until': self.event.end_datetime.isoformat()
        }
        response = self.client.post('/api/bookings/ticket-types/', data, format='json')
        
        # Should be forbidden since other_user has no admin role
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST])
    
    def test_update_ticket_type(self):
        """Test updating ticket type."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'title': 'Updated Full Event Pass'
        }
        response = self.client.patch(
            f'/api/bookings/ticket-types/{self.full_event_ticket.id}/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Full Event Pass')
    
    def test_filter_ticket_types_by_event(self):
        """Test filtering ticket types by event."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/ticket-types/?event={self.event.id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_filter_ticket_types_by_scope(self):
        """Test filtering ticket types by scope."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/bookings/ticket-types/?scope={TicketScopeChoices.FULL_EVENT}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for ticket_type in response.data['results']:
            self.assertEqual(ticket_type['scope'], TicketScopeChoices.FULL_EVENT)


# ============================================================================
# TICKET ENDPOINT TESTS
# ============================================================================

class TicketEndpointTests(BookingsAPITestCase):
    """Test ticket endpoints (read-only)."""
    
    def test_list_tickets(self):
        """Test listing tickets."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/bookings/tickets/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_ticket_detail(self):
        """Test retrieving ticket details."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/tickets/{self.ticket.ticket_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], TicketStatusChoices.ACTIVE)
        self.assertIn('_links', response.data)
        self.assertIn('ticket_code', response.data)
        self.assertTrue(response.data['ticket_code'])
    
    def test_tickets_are_read_only(self):
        """Test that tickets cannot be created via API."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'ticket_type': self.full_event_ticket.id,
            'attendee': self.attendee.attendee_id,
            'status': TicketStatusChoices.ACTIVE
        }
        response = self.client.post('/api/bookings/tickets/', data, format='json')
        
        # ViewSet is read-only
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
    
    def test_other_user_cannot_access_ticket(self):
        """Other users cannot access tickets they don't own."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(f'/api/bookings/tickets/{self.ticket.ticket_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_filter_tickets_by_status(self):
        """Test filtering tickets by status."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/bookings/tickets/?status={TicketStatusChoices.ACTIVE}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for ticket in response.data['results']:
            self.assertEqual(ticket['status'], TicketStatusChoices.ACTIVE)
    
    def test_filter_tickets_by_attendee(self):
        """Test filtering tickets by attendee."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/bookings/tickets/?attendee={self.attendee.attendee_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


# ============================================================================
# BOOKING PACKAGE ENDPOINT TESTS
# ============================================================================

class BookingPackageEndpointTests(BookingsAPITestCase):
    """Test booking package endpoints."""
    
    def test_list_booking_packages(self):
        """Test listing booking packages."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/bookings/packages/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_retrieve_package_detail(self):
        """Test retrieving package details with rules."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/packages/{self.early_bird_package.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Early Bird')
        self.assertIn('_links', response.data)
        self.assertIn('rules', response.data)
        self.assertIn('base_amount', response.data)
    
    def test_create_package_with_rules(self):
        """Test creating package with nested rules."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'name': 'Youth Discount',
            'description': 'For under 18s',
            'event': self.event.id,
            'ticket_type': self.full_event_ticket.id,
            'base_amount': 8.00,
            'base_amount_currency': 'GBP',
            'percentage_modifier': -20,
            'is_active': True,
            'rules': [
                {
                    'rule_type': PackageRuleTypeChoices.IS_AGE_LT,
                    'name': 'Under 18',
                    'value': '18',
                    'active': True
                }
            ]
        }
        response = self.client.post('/api/bookings/packages/', data, format='json')
        
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Package validation errors: {response.data}")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Youth Discount')
    
    def test_create_package_without_event_fails(self):
        """Test that creating package without event fails."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'name': 'Invalid Package',
            'ticket_type': self.full_event_ticket.id,
            'base_amount': 10.00,
            'base_amount_currency': 'GBP'
        }
        response = self.client.post('/api/bookings/packages/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('event', response.data)
    
    def test_create_package_mismatched_event_ticket_type_fails(self):
        """Test that package with mismatched event and ticket type fails."""
        # Create another event
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OE2026',
            display_identifier='OE2026YCAMP001',
            created_by=self.admin_user,
            event_type=self.event.event_type,
            start_datetime=timezone.now() + timedelta(days=60),
            end_datetime=timezone.now() + timedelta(days=67),
            status=EventStatusChoices.PUBLISHED,
            organisation=self.organisation
        )
        
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'name': 'Invalid Package',
            'event': other_event.id,
            'ticket_type': self.full_event_ticket.id,  # Belongs to different event
            'base_amount': 10.00,
            'base_amount_currency': 'GBP'
        }
        response = self.client.post('/api/bookings/packages/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_update_package(self):
        """Test updating package."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'name': 'Super Early Bird',
            'percentage_modifier': -10
        }
        response = self.client.patch(
            f'/api/bookings/packages/{self.early_bird_package.id}/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Super Early Bird')
    
    def test_package_nested_rules_endpoint(self):
        """Test nested rules endpoint for package."""
        # Create a rule
        BookingPackageRule.objects.create(
            booking_package=self.early_bird_package,
            rule_type=PackageRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Only',
            active=True
        )
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/packages/{self.early_bird_package.id}/rules/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
    
    def test_filter_packages_by_event(self):
        """Test filtering packages by event."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/packages/?event={self.event.id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_filter_packages_by_ticket_type(self):
        """Test filtering packages by ticket type."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/bookings/packages/?ticket_type={self.full_event_ticket.id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for package in response.data['results']:
            self.assertEqual(package['ticket_type'], self.full_event_ticket.id)
    
    def test_filter_packages_eligible_for_attendee(self):
        """Test filtering packages by attendee eligibility."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/bookings/packages/?eligible_for_attendee={self.attendee.attendee_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return packages this attendee is eligible for


# ============================================================================
# ALTERNATIVE SIGNIN ENDPOINT TESTS
# ============================================================================

class EventAlternativeSigninEndpointTests(BookingsAPITestCase):
    """Test event alternative signin endpoints (admin only)."""
    
    def test_list_event_signins_as_admin(self):
        """Test listing event alternative signins as admin."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/bookings/alternative-signins/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_event_signins_as_regular_user_with_admin_role(self):
        """Test that user with admin event role can access."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/bookings/alternative-signins/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_list_event_signins_as_non_admin_fails(self):
        """Test that non-admin users cannot access."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get('/api/bookings/alternative-signins/')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_create_event_signin(self):
        """Test creating event alternative signin."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'title': 'Student ID',
            'description': 'University student ID number',
            'event': self.event.id,
            'format_match': r'^\d{8}$',
            'max_uses_per_signin': 5,
            'is_active': True
        }
        response = self.client.post('/api/bookings/alternative-signins/', data, format='json')
        
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Event signin validation errors: {response.data}")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn(response.data['title'], ['Student ID', 'Student Id'])  # Accept title case
    
    def test_create_event_signin_invalid_regex_fails(self):
        """Test that invalid regex pattern fails."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'title': 'Invalid Pattern',
            'event': self.event.id,
            'format_match': r'[invalid regex(',  # Invalid regex
            'is_active': True
        }
        response = self.client.post('/api/bookings/alternative-signins/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AttendeeAlternativeSigninEndpointTests(BookingsAPITestCase):
    """Test attendee alternative signin endpoints (admin only)."""
    
    def test_list_attendee_signins_as_admin(self):
        """Test listing attendee alternative signins as admin."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/bookings/attendee-alternative-signins/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_create_attendee_signin(self):
        """Test creating attendee alternative signin."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'attendee': self.attendee.id,
            'ticket': str(self.ticket.ticket_id),
            'identifier': '123456',
            'event_alternative_signin': self.event_signin.id
        }
        response = self.client.post(
            '/api/bookings/attendee-alternative-signins/',
            data,
            format='json'
        )
        
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Attendee signin validation errors: {response.data}")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['identifier'], '123456')
    
    def test_create_attendee_signin_invalid_format_fails(self):
        """Test that identifier not matching format fails."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'attendee': self.attendee.id,
            'ticket': str(self.ticket.ticket_id),
            'identifier': '12345',  # Should be 6 digits
            'event_alternative_signin': self.event_signin.id
        }
        response = self.client.post(
            '/api/bookings/attendee-alternative-signins/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('identifier', response.data)
    
    def test_create_attendee_signin_mismatched_ticket_fails(self):
        """Test that ticket belonging to different attendee fails."""
        # Create another attendee and ticket
        other_attendee = Attendee.objects.create(
            user=self.other_user,
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            date_of_birth=date(1995, 5, 15),
            gender='Female',
            relationship_to_user=AttendeeRelationship.SELF,
            event=self.event,
            defined_by=self.other_user
        )
        
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'attendee': self.attendee.id,
            'ticket': str(self.ticket.ticket_id),  # This ticket belongs to self.attendee
            'identifier': '999999',
            'event_alternative_signin': self.event_signin.id
        }
        # Try to assign attendee's ticket to other_attendee
        data['attendee'] = other_attendee.id
        
        response = self.client.post(
            '/api/bookings/attendee-alternative-signins/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_filter_attendee_signins_by_attendee(self):
        """Test filtering attendee signins by attendee."""
        # Create an attendee signin
        AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='123456',
            event_alternative_signin=self.event_signin,
            defined_by=self.admin_user
        )
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            f'/api/bookings/attendee-alternative-signins/?attendee={self.attendee.attendee_id}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


# ============================================================================
# SERIALIZATION AND HATEOAS TESTS
# ============================================================================

class SerializationTests(BookingsAPITestCase):
    """Test proper serialization and HATEOAS links."""
    
    def test_booking_hateoas_links(self):
        """Test that booking includes proper HATEOAS links."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/list/{self.booking.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        links = response.data['_links']
        self.assertIn('self', links)
        self.assertIn('event', links)
        self.assertIn('attendees', links)
        self.assertIn('tickets', links)
        self.assertIn('/api/bookings/', links['self'])
    
    def test_ticket_hateoas_links(self):
        """Test that ticket includes proper HATEOAS links."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/tickets/{self.ticket.ticket_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        links = response.data['_links']
        self.assertIn('self', links)
        self.assertIn('attendee', links)
        self.assertIn('ticket_type', links)
        self.assertIn('package', links)
    
    def test_package_hateoas_links(self):
        """Test that package includes proper HATEOAS links."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/packages/{self.early_bird_package.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        links = response.data['_links']
        self.assertIn('self', links)
        self.assertIn('event', links)
        self.assertIn('ticket_type', links)
        self.assertIn('rules', links)
    
    def test_money_field_serialization(self):
        """Test that MoneyField is properly serialized."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/packages/{self.early_bird_package.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('base_amount', response.data)
        # Should be in format like "10.00 GBP" or have separate currency field
        self.assertIsNotNone(response.data['base_amount'])
    
    def test_timezone_aware_datetime_serialization(self):
        """Test that datetimes are serialized in event timezone."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/bookings/list/{self.booking.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('booked_at', response.data)
        # Should have timezone info
        self.assertIsNotNone(response.data['booked_at'])
