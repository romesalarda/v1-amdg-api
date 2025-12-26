from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money

from apps.bookings.models import (
    Booking, BookingPackage, BookingPackageRule,
    TicketType, Ticket, TicketScopeChoices, TicketStatusChoices,
    PackageRuleTypeChoices
)
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.organisations.models import Organisation

User = get_user_model()


class BookingFlowIntegrationTest(TestCase):
    """Test cases for the complete booking flow: Booking -> Attendees -> Tickets"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='flowuser',
            email='flow@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Flow Test Event',
            display_code='FLOW01',
            display_identifier='FLOW01CONF123',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN
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
        
    def test_complete_booking_flow_single_attendee(self):
        """Test complete flow: 1. Create booking, 2. Create attendee, 3. Create ticket"""
        # Step 1: Create booking
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-FLOW-001',
            made_by=self.user
        )
        
        self.assertIsNotNone(booking)
        self.assertEqual(booking.event, self.event)
        
        # Step 2: Create attendee linked to booking
        attendee = Attendee.objects.create(
            first_name='Flow',
            last_name='Test',
            event=self.event,
            user=self.user,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertEqual(attendee.booking, booking)
        self.assertIn(attendee, booking.attendees.all())
        
        # Step 3: Create ticket for the attendee
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=attendee,
            uses=1
        )
        
        self.assertEqual(ticket.attendee, attendee)
        self.assertIsNotNone(ticket.ticket_code)
        self.assertEqual(ticket.status, TicketStatusChoices.ACTIVE)
        
    def test_complete_booking_flow_multiple_attendees(self):
        """Test booking with multiple attendees (family registration)"""
        # Step 1: Create booking
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-FAM-001',
            made_by=self.user
        )
        
        # Step 2: Create multiple attendees
        parent = Attendee.objects.create(
            first_name='Parent',
            last_name='Smith',
            event=self.event,
            user=self.user,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1985, 1, 1)
        )
        
        child1 = Attendee.objects.create(
            first_name='Child1',
            last_name='Smith',
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user,
            date_of_birth=date(2015, 1, 1)
        )
        
        child2 = Attendee.objects.create(
            first_name='Child2',
            last_name='Smith',
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user,
            date_of_birth=date(2017, 1, 1)
        )
        
        # Verify all attendees linked to booking
        self.assertEqual(booking.attendees.count(), 3)
        
        # Step 3: Create tickets for each attendee
        tickets = []
        for attendee in [parent, child1, child2]:
            ticket = Ticket.objects.create(
                ticket_type=self.ticket_type,
                attendee=attendee,
                uses=1
            )
            tickets.append(ticket)
        
        self.assertEqual(len(tickets), 3)
        for ticket in tickets:
            self.assertEqual(ticket.status, TicketStatusChoices.ACTIVE)


class BookingPackageRuleIntegrationTest(TestCase):
    """Test cases for booking package rules with attendees"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='ruleuser',
            email='rule@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Package Rule Event',
            display_code='PKR001',
            display_identifier='PKR001CONF999',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='YOUTH',
            title='Youth Ticket',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
        
        self.package = BookingPackage.objects.create(
            name='Youth Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(50, 'GBP'),
            created_by=self.user
        )
        
    def test_package_rule_age_less_than(self):
        """Test IS_AGE_LT rule - evaluator should reject attendee >= 18"""
        # Create rule: age must be less than 18
        rule = BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.IS_AGE_LT,
            name='Under 18 Only',
            description='For attendees under 18 years',
            booking_package=self.package,
            value='18',
            added_by=self.user
        )
        
        self.assertEqual(rule.value, '18')
        self.assertEqual(rule.rule_type, PackageRuleTypeChoices.IS_AGE_LT)
        
        # Test with minor attendee (15 years old) - should PASS
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-AGE-LT-001',
            made_by=self.user
        )
        
        minor = Attendee.objects.create(
            first_name='Young',
            last_name='Person',
            event=self.event,
            booking=booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user,
            date_of_birth=date.today() - timedelta(days=365 * 15)  # 15 years old
        )
        
        self.assertTrue(minor.is_minor)
        self.assertLess(minor.age, 18)
        
        # Test can_use_package with evaluator - should PASS for minor
        result = self.package.can_use_package(self.user, minor)
        self.assertTrue(result, "Minor (15 years) should be able to use package with IS_AGE_LT rule")
        
        # Test with adult (25 years old) - should FAIL
        adult_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-AGE-LT-002',
            made_by=self.user
        )
        
        adult = Attendee.objects.create(
            first_name='Adult',
            last_name='Person',
            event=self.event,
            booking=adult_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1999, 1, 1)  # 25 years old
        )
        
        self.assertFalse(adult.is_minor)
        self.assertGreaterEqual(adult.age, 18)
        
        # Test can_use_package with evaluator - should FAIL for adult
        result = self.package.can_use_package(self.user, adult)
        self.assertFalse(result, "Adult (25 years) should NOT be able to use package with IS_AGE_LT 18 rule")
        
    def test_package_rule_age_greater_than(self):
        """Test IS_AGE_GT rule - evaluator should reject attendee <= 18"""
        adult_package = BookingPackage.objects.create(
            name='Adult Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            created_by=self.user
        )
        
        rule = BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.IS_AGE_GT,
            name='Adults Only',
            description='For attendees over 18 years',
            booking_package=adult_package,
            value='18',
            added_by=self.user
        )
        
        # Test with adult (40 years old) - should PASS
        adult_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-AGE-GT-001',
            made_by=self.user
        )
        
        adult = Attendee.objects.create(
            first_name='Adult',
            last_name='Person',
            event=self.event,
            booking=adult_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1985, 1, 1)
        )
        
        self.assertFalse(adult.is_minor)
        self.assertGreater(adult.age, 18)
        
        # Test can_use_package with evaluator - should PASS for adult
        result = adult_package.can_use_package(self.user, adult)
        self.assertTrue(result, "Adult (40 years) should be able to use package with IS_AGE_GT 18 rule")
        
        # Test with minor (15 years old) - should FAIL
        minor_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-AGE-GT-002',
            made_by=self.user
        )
        
        minor = Attendee.objects.create(
            first_name='Young',
            last_name='Person',
            event=self.event,
            booking=minor_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user,
            date_of_birth=date.today() - timedelta(days=365 * 15)
        )
        
        self.assertTrue(minor.is_minor)
        self.assertLess(minor.age, 18)
        
        # Test can_use_package with evaluator - should FAIL for minor
        result = adult_package.can_use_package(self.user, minor)
        self.assertFalse(result, "Minor (15 years) should NOT be able to use package with IS_AGE_GT 18 rule")
        
    def test_package_rule_organisation_matches(self):
        """Test ORGANISATION_MATCHES rule - evaluator should check metadata"""
        organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        org_package = BookingPackage.objects.create(
            name='Organisation Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(75, 'GBP'),
            created_by=self.user
        )
        
        rule = BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.ORGANISATION_MATCHES,
            name='Org Members Only',
            description='For organisation members',
            booking_package=org_package,
            value=str(organisation.title),
            added_by=self.user
        )
        
        # Create attendee who IS part of the organisation - should PASS
        member_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-ORG-001',
            made_by=self.user
        )
        
        member_attendee = Attendee.objects.create(
            first_name='Org',
            last_name='Member',
            event=self.event,
            booking=member_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        member_attendee.add_organisation(organisation)
        
        # Verify metadata contains organisation
        context = member_attendee.pricing_context()
        self.assertIn(organisation.title, context.metadata.get('organisations', []))
        
        # Test can_use_package with evaluator - should PASS
        result = org_package.can_use_package(self.user, member_attendee)
        self.assertTrue(result, "Member of organisation should be able to use package with ORGANISATION_MATCHES rule")
        
        # Create attendee who is NOT part of organisation - should FAIL
        non_member_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-ORG-002',
            made_by=self.user
        )
        
        non_member = Attendee.objects.create(
            first_name='Non',
            last_name='Member',
            event=self.event,
            booking=non_member_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        # Verify metadata does NOT contain organisation
        context = non_member.pricing_context()
        self.assertNotIn(str(organisation.id), context.metadata.get('organisations', []))
        
        # Test can_use_package with evaluator - should FAIL
        result = org_package.can_use_package(self.user, non_member)
        self.assertFalse(result, "Non-member should NOT be able to use package with ORGANISATION_MATCHES rule")
        
    def test_package_rule_name_matches(self):
        """Test NAME_MATCHES rule - evaluator should check full_name in metadata"""
        name_package = BookingPackage.objects.create(
            name='Special Name Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(80, 'GBP'),
            created_by=self.user
        )
        
        rule = BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.NAME_MATCHES,
            name='Name Contains John',
            description='For attendees named John',
            booking_package=name_package,
            value='John',
            added_by=self.user
        )
        
        # Test with attendee whose name contains "John" - should PASS
        john_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-NAME-001',
            made_by=self.user
        )
        
        john_attendee = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=self.event,
            booking=john_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertIn('John', john_attendee.full_name)
        
        # Test can_use_package with evaluator - should PASS
        result = name_package.can_use_package(self.user, john_attendee)
        self.assertTrue(result, "Attendee with name 'John' should be able to use package with NAME_MATCHES 'John' rule")
        
        # Test with attendee whose name does NOT contain "John" - should FAIL
        jane_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-NAME-002',
            made_by=self.user
        )
        
        jane_attendee = Attendee.objects.create(
            first_name='Jane',
            last_name='Smith',
            event=self.event,
            booking=jane_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertNotIn('John', jane_attendee.full_name)
        
        # Test can_use_package with evaluator - should FAIL
        result = name_package.can_use_package(self.user, jane_attendee)
        self.assertFalse(result, "Attendee without name 'John' should NOT be able to use package with NAME_MATCHES 'John' rule")
        
    def test_package_rule_multiple_rules_all_must_pass(self):
        """Test that ALL rules must pass for package to be usable"""
        strict_package = BookingPackage.objects.create(
            name='Strict Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(50, 'GBP'),
            created_by=self.user
        )
        
        # Rule 1: Age must be greater than 21
        BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.IS_AGE_GT,
            name='Over 21',
            booking_package=strict_package,
            value='21',
            added_by=self.user
        )
        
        # Rule 2: Name must contain "Smith"
        BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.NAME_MATCHES,
            name='Name Contains Smith',
            booking_package=strict_package,
            value='Smith',
            added_by=self.user
        )
        
        # Test with attendee who meets BOTH criteria - should PASS
        valid_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-MULTI-001',
            made_by=self.user
        )
        
        valid_attendee = Attendee.objects.create(
            first_name='John',
            last_name='Smith',
            event=self.event,
            booking=valid_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)  # ~35 years old
        )
        
        self.assertGreater(valid_attendee.age, 21)
        self.assertIn('Smith', valid_attendee.full_name)
        
        result = strict_package.can_use_package(self.user, valid_attendee)
        self.assertTrue(result, "Attendee meeting ALL rules should be able to use package")
        
        # Test with attendee who meets age but NOT name - should FAIL
        wrong_name_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-MULTI-002',
            made_by=self.user
        )
        
        wrong_name = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=self.event,
            booking=wrong_name_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)  # ~35 years old
        )
        
        self.assertGreater(wrong_name.age, 21)
        self.assertNotIn('Smith', wrong_name.full_name)
        
        result = strict_package.can_use_package(self.user, wrong_name)
        self.assertFalse(result, "Attendee failing ANY rule should NOT be able to use package")
        
        # Test with attendee who meets name but NOT age - should FAIL
        too_young_booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-MULTI-003',
            made_by=self.user
        )
        
        too_young = Attendee.objects.create(
            first_name='Jane',
            last_name='Smith',
            event=self.event,
            booking=too_young_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(2010, 1, 1)  # ~15 years old
        )
        
        self.assertLess(too_young.age, 21)
        self.assertIn('Smith', too_young.full_name)
        
        result = strict_package.can_use_package(self.user, too_young)
        self.assertFalse(result, "Attendee failing ANY rule should NOT be able to use package")
class TicketTypeModelTest(TestCase):
    """Test cases for the TicketType model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event 2025',
            display_code='TE2025',
            display_identifier='TE2025CONF123456',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN
        )
        
    def test_ticket_type_creation(self):
        """Test basic ticket type creation"""
        ticket_type = TicketType.objects.create(
            event=self.event,
            code='VIP',
            title='VIP Ticket',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user,
            max_entries=100
        )
        
        self.assertEqual(ticket_type.title, 'VIP Ticket')
        self.assertEqual(ticket_type.code, 'VIP')
        self.assertEqual(ticket_type.scope, TicketScopeChoices.FULL_EVENT)
        self.assertTrue(ticket_type.is_active)
        self.assertEqual(ticket_type.max_entries, 100)
        
    def test_ticket_type_str_method(self):
        """Test the __str__ method"""
        ticket_type = TicketType.objects.create(
            event=self.event,
            code='GA',
            title='General Admission',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
        
        str_repr = str(ticket_type)
        self.assertIn('General Admission', str_repr)
        self.assertIn('GA', str_repr)
        
    def test_ticket_type_unique_constraint(self):
        """Test that ticket type title must be unique per event"""
        TicketType.objects.create(
            event=self.event,
            code='UNIQUE1',
            title='Unique Title',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
        
        # Try to create another with same title for same event
        with self.assertRaises(Exception):
            TicketType.objects.create(
                event=self.event,
                code='UNIQUE2',
                title='Unique Title',
                scope=TicketScopeChoices.FULL_EVENT,
                valid_from=timezone.now(),
                valid_until=timezone.now() + timedelta(days=60),
                created_by=self.user
            )
            
    def test_ticket_type_validates_dates(self):
        """Test that valid_until must be after valid_from"""
        ticket_type = TicketType(
            event=self.event,
            code='INVALID',
            title='Invalid Dates',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now() + timedelta(days=60),
            valid_until=timezone.now(),
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            ticket_type.clean()


class TicketModelTest(TestCase):
    """Test cases for the Ticket model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='ticketuser',
            email='ticket@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Ticket Event',
            display_code='TCKE01',
            display_identifier='TCKE01CONF789',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
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
        
        # Create booking first
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TICKET-001',
            made_by=self.user
        )
        
        # Then create attendee linked to booking
        self.attendee = Attendee.objects.create(
            first_name='Ticket',
            last_name='Holder',
            event=self.event,
            user=self.user,
            booking=self.booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_ticket_creation(self):
        """Test basic ticket creation"""
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            uses=1
        )
        
        self.assertIsNotNone(ticket.ticket_id)
        self.assertIsNotNone(ticket.ticket_code)
        self.assertEqual(ticket.status, TicketStatusChoices.ACTIVE)
        self.assertEqual(ticket.attendee, self.attendee)
        self.assertEqual(ticket.ticket_type, self.ticket_type)
        
    def test_ticket_auto_generates_code(self):
        """Test that ticket code is auto-generated"""
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee
        )
        
        self.assertIsNotNone(ticket.ticket_code)
        self.assertIn('TCK', ticket.ticket_code)
        
    def test_ticket_use_functionality(self):
        """Test using a ticket"""
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            uses=2
        )
        
        initial_uses = ticket.uses
        ticket.use_ticket()
        
        self.assertEqual(ticket.uses, initial_uses - 1)
        self.assertEqual(ticket.status, TicketStatusChoices.ACTIVE)
        
        # Use again to deplete
        ticket.use_ticket()
        self.assertEqual(ticket.uses, 0)
        self.assertEqual(ticket.status, TicketStatusChoices.USED)
        
    def test_ticket_cannot_use_when_inactive(self):
        """Test that inactive tickets cannot be used"""
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            status=TicketStatusChoices.CANCELLED
        )
        
        with self.assertRaises(ValidationError):
            ticket.use_ticket()
            
    def test_ticket_cannot_use_when_no_uses_remaining(self):
        """Test that tickets with 0 uses cannot be used"""
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            uses=0,
            status=TicketStatusChoices.USED
        )
        
        with self.assertRaises(ValidationError):
            ticket.use_ticket()
            
    def test_ticket_cannot_use_when_no_uses_remaining(self):
        """Test that tickets with 0 uses cannot be used"""
        ticket = Ticket(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            uses=0
        )
        
        with self.assertRaises(ValidationError):
            ticket.use_ticket()
            
    def test_ticket_booking_property(self):
        """Test that ticket can access booking through attendee"""
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            uses=1
        )
        
        self.assertEqual(ticket.booking, self.booking)
        self.assertIsNotNone(ticket.booking)
        
    def test_ticket_validates_attendee_event_match(self):
        """Test that attendee must belong to same event as ticket type"""
        # Create another event
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OTH001',
            display_identifier='OTH001CONF999',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        # Create attendee for other event
        other_booking = Booking.objects.create(
            event=other_event,
            booking_reference='BKG-OTHER-001',
            made_by=self.user
        )
        
        other_attendee = Attendee.objects.create(
            first_name='Other',
            last_name='Event',
            event=other_event,
            booking=other_booking,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        # Try to create ticket with mismatched event
        ticket = Ticket(
            ticket_type=self.ticket_type,  # belongs to self.event
            attendee=other_attendee,  # belongs to other_event
            uses=1
        )
        
        with self.assertRaises(ValidationError):
            ticket.clean()


class BookingPackageModelTest(TestCase):
    """Test cases for the BookingPackage model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='packageuser',
            email='package@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Package Event',
            display_code='PKG001',
            display_identifier='PKG001CONF999',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='EARLY',
            title='Early Bird',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
        
    def test_booking_package_creation(self):
        """Test basic booking package creation"""
        package = BookingPackage.objects.create(
            name='Standard Package',
            description='Standard booking package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            percentage_modifier=Decimal('0.00'),
            created_by=self.user
        )
        
        self.assertEqual(package.name, 'Standard Package')
        self.assertEqual(package.event, self.event)
        self.assertEqual(package.ticket_type, self.ticket_type)
        self.assertTrue(package.is_active)
        self.assertEqual(package.base_amount, Money(100, 'GBP'))
        
    def test_booking_package_str_method(self):
        """Test the __str__ method"""
        package = BookingPackage.objects.create(
            name='VIP Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(200, 'GBP'),
            created_by=self.user
        )
        
        str_repr = str(package)
        self.assertIn('VIP Package', str_repr)
        self.assertIn(self.event.title, str_repr)
        
    def test_booking_package_unique_constraint(self):
        """Test that package name must be unique per event"""
        BookingPackage.objects.create(
            name='Unique Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            created_by=self.user
        )
        
        # Try to create another with same name for same event
        with self.assertRaises(Exception):
            BookingPackage.objects.create(
                name='Unique Package',
                event=self.event,
                ticket_type=self.ticket_type,
                base_amount=Money(150, 'GBP'),
                created_by=self.user
            )
            
    def test_booking_package_inherits_payable_model(self):
        """Test that BookingPackage has PayableModel fields"""
        package = BookingPackage.objects.create(
            name='Test Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            percentage_modifier=Decimal('10.00'),
            created_by=self.user
        )
        
        # Test modified_amount property from PayableModel
        expected_amount = Money(110, 'GBP')
        self.assertEqual(package.modified_amount, expected_amount)
        
    def test_booking_package_validates_ticket_type_event(self):
        """Test that ticket type must belong to same event"""
        # Create another event
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OTH001',
            display_identifier='OTH001CONF888',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        # Create ticket type for other event
        other_ticket_type = TicketType.objects.create(
            event=other_event,
            code='OTHER',
            title='Other Ticket',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
        
        # Try to create package with mismatched event and ticket type
        package = BookingPackage(
            name='Invalid Package',
            event=self.event,
            ticket_type=other_ticket_type,
            base_amount=Money(100, 'GBP'),
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            package.clean()


class BookingPackageRuleModelTest(TestCase):
    """Test cases for the BookingPackageRule model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='ruleuser2',
            email='rule2@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Rule Event',
            display_code='RLE001',
            display_identifier='RLE001CONF888',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
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
        
        self.package = BookingPackage.objects.create(
            name='Test Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            created_by=self.user
        )
        
    def test_package_rule_creation(self):
        """Test basic package rule creation"""
        rule = BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.IS_EVENT_STAFF,
            name='Staff Discount Rule',
            description='Only for event staff',
            booking_package=self.package,
            added_by=self.user
        )
        
        self.assertEqual(rule.rule_type, PackageRuleTypeChoices.IS_EVENT_STAFF)
        self.assertEqual(rule.name, 'Staff Discount Rule')
        self.assertTrue(rule.active)
        self.assertEqual(rule.booking_package, self.package)
        
    def test_package_rule_with_value(self):
        """Test package rule with value"""
        rule = BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.IS_AGE_LT,
            name='Youth Discount',
            description='For attendees under 18',
            booking_package=self.package,
            value='18',
            added_by=self.user
        )
        
        self.assertEqual(rule.value, '18')
        
    def test_package_rule_validation_requires_value(self):
        """Test that certain rule types require a value"""
        rule = BookingPackageRule(
            rule_type=PackageRuleTypeChoices.IS_AGE_LT,
            name='Test Rule',
            booking_package=self.package,
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            rule.clean()
            
    def test_package_rule_validation_age_integer(self):
        """Test that age rules require integer values"""
        rule = BookingPackageRule(
            rule_type=PackageRuleTypeChoices.IS_AGE_GT,
            name='Adult Discount',
            booking_package=self.package,
            value='not_a_number',
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            rule.clean()
            
    def test_package_rule_str_method(self):
        """Test the __str__ method"""
        rule = BookingPackageRule.objects.create(
            rule_type=PackageRuleTypeChoices.NAME_MATCHES,
            name='Name Match Rule',
            booking_package=self.package,
            value='John',
            added_by=self.user
        )
        
        self.assertEqual(str(rule), 'Name Match Rule')


class BookingModelTest(TestCase):
    """Test cases for the Booking model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='bookinguser',
            email='booking@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Booking Event',
            display_code='BKE001',
            display_identifier='BKE001CONF777',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
    def test_booking_creation(self):
        """Test basic booking creation"""
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TEST-001',
            made_by=self.user
        )
        
        self.assertEqual(booking.event, self.event)
        self.assertEqual(booking.made_by, self.user)
        self.assertIsNotNone(booking.booked_at)
        self.assertEqual(booking.booking_reference, 'BKG-TEST-001')
        
    def test_booking_str_method(self):
        """Test the __str__ method"""
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TEST-002',
            made_by=self.user
        )
        
        str_repr = str(booking)
        self.assertIn('BKG-TEST-002', str_repr)
        self.assertIn(str(self.user), str_repr)
        
    def test_booking_unique_reference(self):
        """Test that booking reference must be unique"""
        Booking.objects.create(
            event=self.event,
            booking_reference='UNIQUE-REF-001',
            made_by=self.user
        )
        
        # Try to create another with same reference
        with self.assertRaises(Exception):
            Booking.objects.create(
                event=self.event,
                booking_reference='UNIQUE-REF-001',
                made_by=self.user
            )
            
    def test_booking_validates_reference(self):
        """Test that booking reference cannot be empty"""
        booking = Booking(
            event=self.event,
            booking_reference='',
            made_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            booking.clean()


class PackageRuleTypeChoicesTest(TestCase):
    """Test cases for PackageRuleTypeChoices enum"""
    
    def test_all_rule_types_exist(self):
        """Test that all expected rule types are defined"""
        expected_types = [
            'IS_EVENT_STAFF',
            'IS_AGE_LT',
            'IS_AGE_GT',
            'ORGANISATION_MATCHES',
            'VALUE_MATCHES',
            'EVENT_STAFF_ROLE_MATCHES',
            'NAME_MATCHES',
            'LOCATION_MATCHES'
        ]
        
        for rule_type in expected_types:
            self.assertTrue(hasattr(PackageRuleTypeChoices, rule_type))


class TicketScopeChoicesTest(TestCase):
    """Test cases for TicketScopeChoices enum"""
    
    def test_all_scope_types_exist(self):
        """Test that all expected scope types are defined"""
        expected_scopes = [
            'FULL_EVENT',
            'SINGLE_DAY',
            'WORKSHOP_ONLY'
        ]
        
        for scope in expected_scopes:
            self.assertTrue(hasattr(TicketScopeChoices, scope))


class TicketStatusChoicesTest(TestCase):
    """Test cases for TicketStatusChoices enum"""
    
    def test_all_status_types_exist(self):
        """Test that all expected status types are defined"""
        expected_statuses = [
            'ACTIVE',
            'CANCELLED',
            'USED'
        ]
        
        for status in expected_statuses:
            self.assertTrue(hasattr(TicketStatusChoices, status))

