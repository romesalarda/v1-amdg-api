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
    PackageRuleTypeChoices,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier
)
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.organisations.models import Organisation
from apps.common.models.verification import VerificationStatus

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
        
        self.organisation = Organisation.objects.create(
            title='Flow Test Organisation',
            created_by=self.user
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
        
        self.organisation = Organisation.objects.create(
            title='Package Rule Test Organisation',
            created_by=self.user
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
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
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
        
        self.organisation = Organisation.objects.create(
            title='Ticket Type Test Organisation',
            created_by=self.user
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
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
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
        
        self.organisation = Organisation.objects.create(
            title='Ticket Test Organisation',
            created_by=self.user
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
            end_datetime=timezone.now() + timedelta(days=32),
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
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
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
        
        self.organisation = Organisation.objects.create(
            title='Package Test Organisation',
            created_by=self.user
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
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
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
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
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
        
        self.organisation = Organisation.objects.create(
            title='Rule Test Organisation',
            created_by=self.user
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
            end_datetime=timezone.now() + timedelta(days=32),
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
        
        self.organisation = Organisation.objects.create(
            title='Booking Test Organisation',
            created_by=self.user
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
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
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


class EventAlternativeSigninIdentifierModelTest(TestCase):
    """Test cases for EventAlternativeSigninIdentifier model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='signinuser',
            email='signin@example.com',
            password='testpass123'
        )
        
        self.organisation = Organisation.objects.create(
            title='Signin Test Organisation',
            created_by=self.user
        )
        
        self.event_type = EventType.objects.create(
            title='Youth Event',
            code='YOUTH',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='YFC Youth Event',
            display_code='YFC001',
            display_identifier='YFC001YOUTH',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
    
    def test_alternative_signin_creation(self):
        """Test creating an alternative sign-in identifier"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC YIM Number'.capitalize(),
            description='Youth in Mission membership number',
            event=self.event,
            format_match=r'^YIM\d{6}$',
            max_uses_per_signin=3,
            is_active=True
        )
        
        self.assertIsNotNone(alt_signin.id)
        self.assertEqual(alt_signin.title, 'Yfc Yim Number')  # Title case
        self.assertEqual(alt_signin.event, self.event)
        self.assertEqual(alt_signin.max_uses_per_signin, 3)
        self.assertTrue(alt_signin.is_active)
    
    def test_alternative_signin_str_method(self):
        """Test __str__ method returns title"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC YIM Number'.capitalize(),
            event=self.event
        )
        
        self.assertEqual(str(alt_signin), 'Yfc Yim Number')
    
    def test_alternative_signin_repr_method(self):
        """Test __repr__ method"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC YIM Number',
            event=self.event
        )
        
        repr_str = repr(alt_signin)
        self.assertIn('EventAlternativeSigninIdentifier', repr_str)
        self.assertIn('Yfc Yim Number', repr_str)
        self.assertIn(str(self.event.id), repr_str)
    
    def test_alternative_signin_unique_together(self):
        """Test unique_together constraint on event and title"""
        EventAlternativeSigninIdentifier.objects.create(
            title='YFC Number',
            event=self.event
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            EventAlternativeSigninIdentifier.objects.create(
                title='YFC Number',
                event=self.event
            )
    
    def test_alternative_signin_title_validation(self):
        """Test that empty title raises ValidationError"""
        alt_signin = EventAlternativeSigninIdentifier(
            title='',
            event=self.event
        )
        
        with self.assertRaises(ValidationError) as cm:
            alt_signin.save()
        
        self.assertIn('title', cm.exception.message_dict)
    
    def test_alternative_signin_title_stripping_and_title_case(self):
        """Test that title is stripped and converted to title case"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='  yfc yim number  ',
            event=self.event
        )
        
        self.assertEqual(alt_signin.title, 'Yfc Yim Number'.capitalize())
    
    def test_alternative_signin_is_valid_property(self):
        """Test is_valid property returns is_active status"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='Active Signin',
            event=self.event,
            is_active=True
        )
        
        self.assertTrue(alt_signin.is_valid)
        
        alt_signin.is_active = False
        self.assertFalse(alt_signin.is_valid)
    
    def test_validate_code_format_with_regex(self):
        """Test validate_code_format with regex pattern"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC YIM Number',
            event=self.event,
            format_match=r'^YIM\d{6}$'  # Pattern: YIM followed by 6 digits
        )
        
        # Valid codes
        self.assertTrue(alt_signin.validate_code_format('YIM123456'))
        self.assertTrue(alt_signin.validate_code_format('YIM000000'))
        
        # Invalid codes
        self.assertFalse(alt_signin.validate_code_format('YIM12345'))  # Too short
        self.assertFalse(alt_signin.validate_code_format('YIM1234567'))  # Too long
        self.assertFalse(alt_signin.validate_code_format('yim123456'))  # Wrong case
        self.assertFalse(alt_signin.validate_code_format('ABC123456'))  # Wrong prefix
    
    def test_validate_code_format_without_regex(self):
        """Test validate_code_format returns True when no format_match is set"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='Flexible ID',
            event=self.event,
            format_match=None
        )
        
        # Any code should be valid
        self.assertTrue(alt_signin.validate_code_format('anything'))
        self.assertTrue(alt_signin.validate_code_format('12345'))
        self.assertTrue(alt_signin.validate_code_format(''))
    
    def test_verification_status_defaults_to_pending(self):
        """Test that verification_status defaults to PENDING (from RequiresVerificationModel)"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='Pending Signin',
            event=self.event
        )
        
        self.assertEqual(alt_signin.verification_status, VerificationStatus.PENDING)
    
    def test_mark_verified_updates_status(self):
        """Test mark_verified method from RequiresVerificationModel"""
        alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='To Be Verified',
            event=self.event
        )
        
        alt_signin.mark_verified(self.user)
        
        self.assertEqual(alt_signin.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(alt_signin.verified_by, self.user)
        self.assertIsNotNone(alt_signin.verified_updated_at)


class AttendeeAlternativeSigninIdentifierModelTest(TestCase):
    """Test cases for AttendeeAlternativeSigninIdentifier model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='attendeeuser',
            email='attendee@example.com',
            password='testpass123'
        )
        
        self.organisation = Organisation.objects.create(
            title='Attendee Signin Organisation',
            created_by=self.user
        )
        
        self.event_type = EventType.objects.create(
            title='Youth Event',
            code='YOUTH',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='YFC Youth Conference',
            display_code='YFCCONF',
            display_identifier='YFCCONFYOUTH',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='YOUTH',
            title='Youth Pass',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-SIGNIN-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='John',
            last_name='Youth',
            event=self.event,
            user=self.user,
            booking=self.booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(2010, 5, 15)
        )
        
        self.ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            uses=1
        )
        
        self.event_alt_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC Number',
            description='YFC membership number',
            event=self.event,
            format_match=r'^YFC\d{6}$',
            max_uses_per_signin=3,
            is_active=True
        )
    
    def test_attendee_alternative_signin_creation(self):
        """Test creating an attendee alternative sign-in identifier"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.assertIsNotNone(attendee_signin.sign_id)
        self.assertEqual(attendee_signin.attendee, self.attendee)
        self.assertEqual(attendee_signin.ticket, self.ticket)
        self.assertEqual(attendee_signin.identifier, 'YFC123456')
        self.assertEqual(attendee_signin.uses, 0)
    
    def test_attendee_alternative_signin_str_method(self):
        """Test __str__ method"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        expected = f"{self.attendee} - YFC123456"
        self.assertEqual(str(attendee_signin), expected)
    
    def test_attendee_alternative_signin_repr_method(self):
        """Test __repr__ method"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        repr_str = repr(attendee_signin)
        self.assertIn('AttendeeAlternativeSigninIdentifier', repr_str)
        self.assertIn(str(self.attendee.attendee_display_id), repr_str)
        self.assertIn('YFC123456', repr_str)
    
    def test_identifier_stripping(self):
        """Test that identifier is stripped of whitespace"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='  YFC123456  ',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.assertEqual(attendee_signin.identifier, 'YFC123456')
    
    def test_empty_identifier_validation(self):
        """Test that empty identifier raises ValidationError"""
        attendee_signin = AttendeeAlternativeSigninIdentifier(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        with self.assertRaises(ValidationError) as cm:
            attendee_signin.save()
        
        self.assertIn('identifier', cm.exception.message_dict)
    
    def test_identifier_format_validation(self):
        """Test that identifier is validated against event's format_match"""
        # Valid format
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.assertIsNotNone(attendee_signin.pk)
        
        # Invalid format
        invalid_signin = AttendeeAlternativeSigninIdentifier(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='INVALID123',  # Doesn't match YFC\d{6} pattern
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        with self.assertRaises(ValidationError) as cm:
            invalid_signin.save()
        
        self.assertIn('identifier', cm.exception.message_dict)
    
    def test_event_mismatch_validation(self):
        """Test that event_alternative_signin must belong to same event as ticket"""
        # Create another event
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OTHER',
            display_identifier='OTHERYOUTH',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        other_event_signin = EventAlternativeSigninIdentifier.objects.create(
            title='Other Number',
            event=other_event,
            is_active=True
        )
        
        attendee_signin = AttendeeAlternativeSigninIdentifier(
            attendee=self.attendee,
            ticket=self.ticket,  # ticket is for self.event
            identifier='ABC123',
            event_alternative_signin=other_event_signin,  # but this is for other_event
            defined_by=self.user
        )
        
        with self.assertRaises(ValidationError) as cm:
            attendee_signin.save()
        
        self.assertIn('event_alternative_signin', cm.exception.message_dict)
    
    def test_ticket_attendee_mismatch_validation(self):
        """Test that ticket must belong to the same attendee"""
        # Create another attendee
        other_attendee = Attendee.objects.create(
            first_name='Jane',
            last_name='Smith',
            event=self.event,
            booking=self.booking,
            relationship_to_user=AttendeeRelationship.FRIEND,
            defined_by=self.user,
            date_of_birth=date(2008, 3, 20)
        )
        
        attendee_signin = AttendeeAlternativeSigninIdentifier(
            attendee=other_attendee,  # Different attendee
            ticket=self.ticket,  # But ticket belongs to self.attendee
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        with self.assertRaises(ValidationError) as cm:
            attendee_signin.save()
        
        self.assertIn('ticket', cm.exception.message_dict)
    
    def test_inactive_event_signin_validation(self):
        """Test that event_alternative_signin must be active"""
        self.event_alt_signin.is_active = False
        self.event_alt_signin.save()
        
        attendee_signin = AttendeeAlternativeSigninIdentifier(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        with self.assertRaises(ValidationError) as cm:
            attendee_signin.save()
        
        self.assertIn('event_alternative_signin', cm.exception.message_dict)
    
    def test_unique_together_constraint(self):
        """Test unique_together constraint on attendee, event_alternative_signin, identifier"""
        AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        with self.assertRaises(Exception):  # IntegrityError or ValidationError
            AttendeeAlternativeSigninIdentifier.objects.create(
                attendee=self.attendee,
                ticket=self.ticket,
                identifier='YFC123456',
                event_alternative_signin=self.event_alt_signin,
                defined_by=self.user
            )
    
    def test_has_ticket_property(self):
        """Test has_ticket property"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.assertTrue(attendee_signin.has_ticket)
        
        # Test with null ticket
        attendee_signin.ticket = None
        self.assertFalse(attendee_signin.has_ticket)
    
    def test_is_valid_property_basic(self):
        """Test is_valid property with active event signin"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.assertTrue(attendee_signin.is_valid)
    
    def test_is_valid_property_inactive_event_signin(self):
        """Test is_valid returns False when event signin is inactive"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.event_alt_signin.is_active = False
        self.event_alt_signin.save()
        attendee_signin.refresh_from_db()
        
        self.assertFalse(attendee_signin.is_valid)
    
    def test_is_valid_property_max_uses_reached(self):
        """Test is_valid returns False when max uses is reached"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        # max_uses_per_signin is 3
        attendee_signin.uses = 3
        attendee_signin.save()
        
        self.assertFalse(attendee_signin.is_valid)
    
    def test_is_valid_property_no_ticket(self):
        """Test is_valid returns False when no ticket is linked"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=None,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.assertFalse(attendee_signin.is_valid)
    
    def test_use_method_increments_uses(self):
        """Test use() method increments the uses count"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        self.assertEqual(attendee_signin.uses, 0)
        
        attendee_signin.use()
        self.assertEqual(attendee_signin.uses, 1)
        
        attendee_signin.use()
        self.assertEqual(attendee_signin.uses, 2)
    
    def test_use_method_respects_max_uses(self):
        """Test use() method raises ValidationError when max uses reached"""
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        # Use it 3 times (max_uses_per_signin = 3)
        attendee_signin.use()
        attendee_signin.use()
        attendee_signin.use()
        
        # 4th use should fail
        with self.assertRaises(ValidationError):
            attendee_signin.use()
    
    def test_use_method_unlimited_uses(self):
        """Test use() method works when max_uses_per_signin is None (unlimited)"""
        self.event_alt_signin.max_uses_per_signin = None
        self.event_alt_signin.save()
        
        attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=self.attendee,
            ticket=self.ticket,
            identifier='YFC123456',
            event_alternative_signin=self.event_alt_signin,
            defined_by=self.user
        )
        
        # Should be able to use many times
        for i in range(10):
            attendee_signin.use()
        
        self.assertEqual(attendee_signin.uses, 10)
        self.assertTrue(attendee_signin.is_valid)


class AlternativeSigninIntegrationTest(TestCase):
    """Integration tests for the alternative sign-in flow"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='integuser',
            email='integ@example.com',
            password='testpass123'
        )
        
        self.organisation = Organisation.objects.create(
            title='Integration Test Organisation',
            created_by=self.user
        )
        
        self.event_type = EventType.objects.create(
            title='Youth Event',
            code='YOUTH',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Multi-Signin Event',
            display_code='MULTI',
            display_identifier='MULTIYOUTH',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='FULL',
            title='Full Access',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=60),
            created_by=self.user
        )
    
    def test_complete_alternative_signin_flow(self):
        """Test complete flow: Event setup -> Booking -> Ticket -> Alternative signin"""
        # Step 1: Create event alternative signin identifiers
        yfc_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC Number',
            description='YFC membership',
            event=self.event,
            format_match=r'^YFC\d{6}$',
            is_active=True
        )
        
        scout_signin = EventAlternativeSigninIdentifier.objects.create(
            title='Scout ID',
            description='Scout membership',
            event=self.event,
            format_match=r'^SCT\d{5}$',
            is_active=True
        )
        
        # Step 2: Create booking and attendee
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-MULTI-001',
            made_by=self.user
        )
        
        attendee = Attendee.objects.create(
            first_name='Multi',
            last_name='Signin',
            event=self.event,
            user=self.user,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(2005, 6, 10)
        )
        
        # Step 3: Create ticket
        ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=attendee,
            uses=1
        )
        
        # Step 4: Add multiple alternative signin identifiers for the attendee
        yfc_attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=attendee,
            ticket=ticket,
            identifier='YFC654321',
            event_alternative_signin=yfc_signin,
            defined_by=self.user
        )
        
        scout_attendee_signin = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=attendee,
            ticket=ticket,
            identifier='SCT12345',
            event_alternative_signin=scout_signin,
            defined_by=self.user
        )
        
        # Verify both alternative signins are linked to the same attendee and ticket
        self.assertEqual(attendee.alternative_signins.count(), 2)
        self.assertEqual(ticket.attendee_alternative_signins.count(), 2)
        
        # Verify both are valid
        self.assertTrue(yfc_attendee_signin.is_valid)
        self.assertTrue(scout_attendee_signin.is_valid)
    
    def test_multiple_attendees_same_event_signin_type(self):
        """Test multiple attendees can use the same event signin type with different identifiers"""
        yfc_signin = EventAlternativeSigninIdentifier.objects.create(
            title='YFC Number',
            event=self.event,
            format_match=r'^YFC\d{6}$',
            is_active=True
        )
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-MULTI-ATT-001',
            made_by=self.user
        )
        
        # Create two attendees
        attendee1 = Attendee.objects.create(
            first_name='First',
            last_name='Attendee',
            event=self.event,
            user=self.user,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(2005, 1, 1)
        )
        
        attendee2 = Attendee.objects.create(
            first_name='Second',
            last_name='Attendee',
            event=self.event,
            booking=booking,
            relationship_to_user=AttendeeRelationship.FRIEND,
            defined_by=self.user,
            date_of_birth=date(2006, 2, 2)
        )
        
        # Create tickets for both
        ticket1 = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=attendee1,
            uses=1
        )
        
        ticket2 = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=attendee2,
            uses=1
        )
        
        # Both can have YFC numbers (but different ones)
        signin1 = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=attendee1,
            ticket=ticket1,
            identifier='YFC111111',
            event_alternative_signin=yfc_signin,
            defined_by=self.user
        )
        
        signin2 = AttendeeAlternativeSigninIdentifier.objects.create(
            attendee=attendee2,
            ticket=ticket2,
            identifier='YFC222222',
            event_alternative_signin=yfc_signin,
            defined_by=self.user
        )
        
        self.assertNotEqual(signin1.identifier, signin2.identifier)
        self.assertTrue(signin1.is_valid)
        self.assertTrue(signin2.is_valid)


