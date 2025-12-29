from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date, timedelta, datetime

from apps.attendee.models import (
    Attendee, AttendeeGuardian, AttendeeRelationship, AttendeeAction,
    FamilyAttendee, FamilyGroup, AttendeeMessage,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    EmergencyContact, Consent, AttendeeConsent,
    EventAttendance, AttendeeOrganisation,
    AttendeeActionChoices, AttendeeMessagePriority,
    HumanRelationshipChoices
)
from apps.events.models import Event, EventType, EventStatusChoices
from apps.locations.models import (
    AreaLocation, CountryLocation, 
    ClusterLocation, ChapterLocation,
    GeneralSectorType, SpecificSectorType
    
    )
from apps.organisations.models import Organisation
from apps.common.models.verification import VerificationStatus

User = get_user_model()


class AttendeeModelTest(TestCase):
    """Test cases for the Attendee model"""
    
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
        
        self.country = CountryLocation.objects.create(
            country="UK",
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE
        )
        
        self.cluster = ClusterLocation.objects.create(
            cluster_name='Test Cluster',
            country=self.country
        )
        
        self.chapter = ChapterLocation.objects.create(
            chapter_name='Test Chapter',
            cluster=self.cluster
        )
        
        self.area = AreaLocation.objects.create(
            area_name='Test Area',
            area_code='TA',
            chapter=self.chapter
        )
        
    def test_attendee_creation(self):
        """Test basic attendee creation"""
        attendee = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=self.event,
            user=self.user,
            email='john.doe@example.com',
            phone_number='+1234567890',
            date_of_birth=date(1990, 1, 1),
            gender='Male',
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            area_from=self.area
        )
        
        self.assertIsNotNone(attendee.attendee_id)
        self.assertIsNotNone(attendee.attendee_display_id)
        self.assertEqual(attendee.first_name, 'John')
        self.assertEqual(attendee.last_name, 'Doe')
        self.assertEqual(attendee.email, 'john.doe@example.com')
        
    def test_attendee_full_name_property(self):
        """Test the full_name property"""
        attendee = Attendee.objects.create(
            first_name='Jane',
            last_name='Smith',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertEqual(attendee.full_name, 'Jane Smith')
        
    def test_attendee_age_calculation(self):
        """Test the age property calculation"""
        today = date.today()
        birth_date = today.replace(year=today.year - 25)
        attendee = Attendee.objects.create(
            first_name='Age',
            last_name='Test',
            event=self.event,
            user=self.user,
            date_of_birth=birth_date,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user
        )
        
        self.assertEqual(attendee.age, 25)
        
    def test_attendee_is_minor_property(self):
        """Test is_minor property"""
        # Create minor (15 years old)
        minor_birth_date = date.today() - timedelta(days=365 * 15)
        minor = Attendee.objects.create(
            first_name='Minor',
            last_name='Test',
            event=self.event,
            user=self.user,
            date_of_birth=minor_birth_date,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user
        )
        
        self.assertTrue(minor.is_minor)
        
        # Create adult (25 years old)
        adult_birth_date = date.today() - timedelta(days=365 * 25)
        adult = Attendee.objects.create(
            first_name='Adult',
            last_name='Test',
            event=self.event,
            user=self.user,
            date_of_birth=adult_birth_date,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user
        )
        
        self.assertFalse(adult.is_minor)
        
    def test_attendee_self_registered_property(self):
        """Test self_registered property"""
        self_attendee = Attendee.objects.create(
            first_name='Self',
            last_name='Registered',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertTrue(self_attendee.self_registered)
        
        child_attendee = Attendee.objects.create(
            first_name='Child',
            last_name='Registered',
            event=self.event,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user,
            date_of_birth=date(2015, 1, 1)
        )
        
        self.assertFalse(child_attendee.self_registered)
        
    def test_attendee_clean_validation_self_without_user(self):
        """Test that SELF relationship requires a user"""
        attendee = Attendee(
            first_name='Invalid',
            last_name='Attendee',
            event=self.event,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            attendee.clean()
            
    def test_attendee_clean_name_formatting(self):
        """Test that names are stripped and title-cased"""
        attendee = Attendee.objects.create(
            first_name='  john  ',
            last_name='  DOE  ',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertEqual(attendee.first_name, 'John')
        self.assertEqual(attendee.last_name, 'Doe')
        
    def test_attendee_str_method(self):
        """Test the __str__ method"""
        attendee = Attendee.objects.create(
            first_name='String',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        # Should not raise an error
        str_repr = str(attendee)
        self.assertIn('String Test', str_repr)
        self.assertIn(attendee.attendee_display_id, str_repr)
    
    def test_attendee_date_of_birth_required(self):
        """Test that date_of_birth is required"""
        attendee = Attendee(
            first_name='No',
            last_name='Birthday',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=None
        )
        
        with self.assertRaises(ValidationError):
            attendee.clean()
    
    def test_attendee_future_date_of_birth_invalid(self):
        """Test that future date of birth is invalid"""
        future_date = date.today() + timedelta(days=365)
        attendee = Attendee(
            first_name='Future',
            last_name='Baby',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=future_date
        )
        
        with self.assertRaises(ValidationError):
            attendee.clean()
    
    def test_is_event_staff_property(self):
        """Test is_event_staff property"""
        from apps.events.models import EventStaff
        
        # Create attendee with staff role
        EventStaff.objects.create(
            user=self.user,
            event=self.event,
            assigned_by=self.user
        )
        
        attendee = Attendee.objects.create(
            first_name='Staff',
            last_name='Member',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertTrue(attendee.is_event_staff)
        
        # Test non-staff attendee
        non_staff_user = User.objects.create_user(
            username='nonstaff',
            email='nonstaff@example.com',
            password='testpass123'
        )
        
        non_staff_attendee = Attendee.objects.create(
            first_name='Regular',
            last_name='Attendee',
            event=self.event,
            user=non_staff_user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=non_staff_user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertFalse(non_staff_attendee.is_event_staff)
    
    def test_staff_role_names_property(self):
        """Test staff_role_names property - Note: EventStaff doesn't store role names"""
        from apps.events.models import EventStaff
        
        # Create staff assignment
        EventStaff.objects.create(
            user=self.user,
            event=self.event,
            assigned_by=self.user
        )
        
        attendee = Attendee.objects.create(
            first_name='Multi',
            last_name='Role',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        # staff_role_names returns empty list as EventStaff model doesn't have role relationship
        role_names = attendee.staff_role_names
        self.assertIsInstance(role_names, list)
    
    def test_was_defined_by_event_staff_property(self):
        """Test was_defined_by_event_staff property"""
        from apps.events.models import EventStaff
        
        # Create staff user
        staff_user = User.objects.create_user(
            username='staffcreator',
            email='staffcreator@example.com',
            password='testpass123'
        )
        
        EventStaff.objects.create(
            user=staff_user,
            event=self.event,
            assigned_by=self.user
        )
        
        # Attendee created by staff
        attendee = Attendee.objects.create(
            first_name='Created',
            last_name='ByStaff',
            event=self.event,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=staff_user,
            date_of_birth=date(2015, 1, 1)
        )
        
        self.assertTrue(attendee.was_defined_by_event_staff)
        
        # Attendee created by non-staff
        non_staff_attendee = Attendee.objects.create(
            first_name='Self',
            last_name='Created',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertFalse(non_staff_attendee.was_defined_by_event_staff)
    
    def test_medical_conditions_property(self):
        """Test medical_conditions property"""
        attendee = Attendee.objects.create(
            first_name='Medical',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        condition = MedicalCondition.objects.create(
            code='TEST1',
            label='Test Condition',
            added_by=self.user
        )
        
        AttendeeMedicalCondition.objects.create(
            attendee=attendee,
            medical_condition=condition,
            added_by=self.user
        )
        
        medical_conditions = attendee.medical_conditions
        self.assertEqual(medical_conditions.count(), 1)
        self.assertEqual(medical_conditions.first().medical_condition, condition)
    
    def test_dietary_requirements_property(self):
        """Test dietary_requirements property"""
        attendee = Attendee.objects.create(
            first_name='Dietary',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        diet = DietaryRequirement.objects.create(
            code='TEST2',
            label='Test Diet',
            added_by=self.user
        )
        
        AttendeeDietaryRequirement.objects.create(
            attendee=attendee,
            dietary_requirement=diet,
            added_by=self.user
        )
        
        dietary_reqs = attendee.dietary_requirements
        self.assertEqual(dietary_reqs.count(), 1)
        self.assertEqual(dietary_reqs.first().dietary_requirement, diet)
    
    def test_accessibility_requirements_property(self):
        """Test accessibility_requirements property"""
        attendee = Attendee.objects.create(
            first_name='Access',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        access = AccessibilityRequirement.objects.create(
            code='TEST3',
            label='Test Access',
            added_by=self.user
        )
        
        AttendeeAccessibilityRequirement.objects.create(
            attendee=attendee,
            accessibility_requirement=access,
            added_by=self.user
        )
        
        access_reqs = attendee.accessibility_requirements
        self.assertEqual(access_reqs.count(), 1)
        self.assertEqual(access_reqs.first().accessibility_requirement, access)
    
    def test_consents_property(self):
        """Test consents property"""
        attendee = Attendee.objects.create(
            first_name='Consent',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        consent = Consent.objects.create(
            event=self.event,
            code='TEST4',
            title='Test Consent',
            description='Test',
            version='1.0',
            defined_by=self.user
        )
        
        AttendeeConsent.objects.create(
            attendee=attendee,
            consent=consent,
            consent_given=True,
            given_at=timezone.now(),
            given_by=self.user,
            recorded_by=self.user
        )
        
        consents = attendee.consents
        self.assertEqual(consents.count(), 1)
        self.assertEqual(consents.first().consent, consent)
    
    def test_is_cancelled_property(self):
        """Test is_cancelled property"""
        attendee = Attendee.objects.create(
            first_name='Cancel',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertFalse(attendee.is_cancelled)
        
        AttendeeAction.objects.create(
            action=AttendeeActionChoices.CANCELLED,
            attendee=attendee,
            performed_by=attendee
        )
        
        self.assertTrue(attendee.is_cancelled)
    
    def test_is_registered_property(self):
        """Test is_registered property"""
        attendee = Attendee.objects.create(
            first_name='Register',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertFalse(attendee.is_registered)
        
        AttendeeAction.objects.create(
            action=AttendeeActionChoices.REGISTERED,
            attendee=attendee,
            performed_by=attendee
        )
        
        self.assertTrue(attendee.is_registered)
    
    def test_is_checked_in_property(self):
        """Test is_checked_in property"""
        attendee = Attendee.objects.create(
            first_name='CheckIn',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertFalse(attendee.is_checked_in)
        
        attendance = EventAttendance.objects.create(
            event=self.event,
            attendee=attendee
        )
        attendance.check_in(timezone.now(), self.user)
        
        # Refresh from db
        attendee.refresh_from_db()
        self.assertTrue(attendee.is_checked_in)
    
    def test_mark_checked_in_method(self):
        """Test mark_checked_in method"""
        attendee = Attendee.objects.create(
            first_name='MarkCheckIn',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        attendance = attendee.mark_checked_in(self.event, self.user)
        
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance.attendee, attendee)
        self.assertEqual(attendance.event, self.event)
        
        # Check that action was created
        action = AttendeeAction.objects.filter(
            attendee=attendee,
            action=AttendeeActionChoices.CHECKED_IN
        ).first()
        self.assertIsNotNone(action)
    
    def test_mark_checked_out_method(self):
        """Test mark_checked_out method"""
        attendee = Attendee.objects.create(
            first_name='MarkCheckOut',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        # First check in
        attendee.mark_checked_in(self.event, self.user)
        
        # Then check out
        attendance = attendee.mark_checked_out(self.event, self.user)
        
        self.assertIsNotNone(attendance)
        self.assertIsNotNone(attendance.checked_out_by)
        
        # Test checking out without checking in first
        new_attendee = Attendee.objects.create(
            first_name='NoCheckIn',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user,
            date_of_birth=date(2015, 1, 1)
        )
        
        result = new_attendee.mark_checked_out(self.event, self.user)
        self.assertIsNone(result)
        
        # Test with raise_if_not_checked_in flag
        with self.assertRaises(ValidationError):
            new_attendee.mark_checked_out(self.event, self.user, raise_if_not_checked_in=True)
    
    def test_mark_registered_method(self):
        """Test mark_registered method"""
        attendee = Attendee.objects.create(
            first_name='MarkReg',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        attendee.mark_registered(performed_by=attendee) 
        
        self.assertTrue(attendee.is_registered)
        action = AttendeeAction.objects.filter(
            attendee=attendee,
            action=AttendeeActionChoices.REGISTERED
        ).first()
        self.assertIsNotNone(action)
    
    def test_mark_cancelled_method(self):
        """Test mark_cancelled method"""
        attendee = Attendee.objects.create(
            first_name='MarkCancel',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        cancellation_notes = 'User requested cancellation'
        attendee.mark_cancelled(notes=cancellation_notes)
        
        self.assertTrue(attendee.is_cancelled)
        action = AttendeeAction.objects.filter(
            attendee=attendee,
            action=AttendeeActionChoices.CANCELLED
        ).first()
        self.assertIsNotNone(action)
        self.assertEqual(action.notes, cancellation_notes)
    
    def test_pricing_context_method(self):
        """Test pricing_context method"""
        attendee = Attendee.objects.create(
            first_name='Pricing',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1),
            area_from=self.area
        )
        
        # Add organisation
        org = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        attendee.add_organisation(org)
        
        context = attendee.pricing_context()
        
        self.assertIsNotNone(context)
        self.assertEqual(context.user, self.user)
        self.assertEqual(context.event, self.event)
        self.assertIn('age', context.metadata)
        self.assertIn('organisations', context.metadata)
        self.assertIn('full_name', context.metadata)
        self.assertIn('location', context.metadata)
        self.assertEqual(context.metadata['full_name'], 'Pricing Test')
        self.assertEqual(context.metadata['location'], self.area.area_name)


class AttendeeGuardianModelTest(TestCase):
    """Test cases for the AttendeeGuardian model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='guardian',
            email='guardian@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE001',
            display_identifier='TE001CONF123',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Child',
            last_name='Attendee',
            event=self.event,
            relationship_to_user=AttendeeRelationship.CHILD,
            defined_by=self.user,
            date_of_birth=date(2015, 1, 1)
        )
        
    def test_guardian_creation(self):
        """Test creating a guardian relationship"""
        guardian = AttendeeGuardian.objects.create(
            user=self.user,
            attendee=self.attendee,
            relationship=AttendeeRelationship.CHILD
        )
        
        self.assertEqual(guardian.user, self.user)
        self.assertEqual(guardian.attendee, self.attendee)
        self.assertEqual(guardian.relationship, AttendeeRelationship.CHILD)
        
    def test_guardian_str_method(self):
        """Test the __str__ method"""
        guardian = AttendeeGuardian.objects.create(
            user=self.user,
            attendee=self.attendee,
            relationship=AttendeeRelationship.CHILD
        )
        
        str_repr = str(guardian)
        self.assertIn(str(self.user), str_repr)
        self.assertIn('guardian', str_repr)


class AttendeeActionModelTest(TestCase):
    """Test cases for the AttendeeAction model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='actionuser',
            email='action@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE001',
            display_identifier='TE001CONF456',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Action',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_action_creation(self):
        """Test creating an attendee action"""
        action = AttendeeAction.objects.create(
            action=AttendeeActionChoices.REGISTERED,
            attendee=self.attendee,
            performed_by=self.attendee,
            notes='Test registration'
        )
        
        self.assertEqual(action.action, AttendeeActionChoices.REGISTERED)
        self.assertEqual(action.attendee, self.attendee)
        self.assertIsNotNone(action.performed_at)
        
    def test_latest_action_method(self):
        """Test the latest_action method on Attendee"""
        action1 = AttendeeAction.objects.create(
            action=AttendeeActionChoices.REGISTERED,
            attendee=self.attendee,
            performed_by=self.attendee
        )
        
        # Wait a moment and create another action
        action2 = AttendeeAction.objects.create(
            action=AttendeeActionChoices.CHECKED_IN,
            attendee=self.attendee,
            performed_by=self.attendee
        )
        
        latest = self.attendee.latest_action()
        self.assertEqual(latest, action2)
        self.assertEqual(latest.action, AttendeeActionChoices.CHECKED_IN)


class FamilyGroupModelTest(TestCase):
    """Test cases for FamilyGroup and FamilyAttendee models"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='familyuser',
            email='family@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Family Event',
            display_code='FE001',
            display_identifier='FE001CONF789',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
    def test_family_group_creation(self):
        """Test creating a family group"""
        family = FamilyGroup.objects.create(
            family_name='Smith Family',
            created_by=self.user
        )
        
        self.assertEqual(family.family_name, 'Smith Family')
        self.assertEqual(family.created_by, self.user)
        self.assertIsNotNone(family.created_at)
        
    def test_family_attendee_creation(self):
        """Test linking attendees to a family group"""
        family = FamilyGroup.objects.create(
            family_name='Doe Family',
            created_by=self.user
        )
        
        parent = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1985, 1, 1)
        )
        
        family_link = FamilyAttendee.objects.create(
            family_group=family,
            attendee=parent,
            relationship=HumanRelationshipChoices.PARENT,
            is_primary_guardian=True
        )
        
        self.assertEqual(family_link.family_group, family)
        self.assertEqual(family_link.attendee, parent)
        self.assertTrue(family_link.is_primary_guardian)
        
    def test_family_attendee_unique_constraint(self):
        """Test that an attendee can only be in a family once"""
        family = FamilyGroup.objects.create(
            family_name='Unique Test',
            created_by=self.user
        )
        
        attendee = Attendee.objects.create(
            first_name='Unique',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        FamilyAttendee.objects.create(
            family_group=family,
            attendee=attendee,
            relationship=HumanRelationshipChoices.PARENT
        )
        
        # Try to add again - should fail
        with self.assertRaises(Exception):
            FamilyAttendee.objects.create(
                family_group=family,
                attendee=attendee,
                relationship=HumanRelationshipChoices.PARENT
            )


class AttendeeMessageModelTest(TestCase):
    """Test cases for AttendeeMessage model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='msguser',
            email='msg@example.com',
            password='testpass123'
        )
        
        self.responder = User.objects.create_user(
            username='responder',
            email='responder@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Message Event',
            display_code='ME001',
            display_identifier='ME001CONF999',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Message',
            last_name='Tester',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_message_creation(self):
        """Test creating an attendee message"""
        message = AttendeeMessage.objects.create(
            attendee=self.attendee,
            subject='Test Message',
            message='This is a test message content',
            priority=AttendeeMessagePriority.HIGH
        )
        
        self.assertEqual(message.attendee, self.attendee)
        self.assertEqual(message.subject, 'Test Message')
        self.assertEqual(message.priority, AttendeeMessagePriority.HIGH)
        self.assertIsNotNone(message.sent_at)
        
    def test_message_response(self):
        """Test responding to a message"""
        message = AttendeeMessage.objects.create(
            attendee=self.attendee,
            subject='Need Response',
            message='Please respond to this',
            priority=AttendeeMessagePriority.MEDIUM
        )
        
        message.response = 'This is the response'
        message.responsed_at = timezone.now()
        message.responsed_by = self.responder
        message.save()
        
        self.assertEqual(message.response, 'This is the response')
        self.assertIsNotNone(message.responsed_at)
        self.assertEqual(message.responsed_by, self.responder)


class AccessibilityRequirementModelTest(TestCase):
    """Test cases for AccessibilityRequirement and AttendeeAccessibilityRequirement"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='accessuser',
            email='access@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Access Event',
            display_code='AE001',
            display_identifier='AE001CONF111',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Access',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_accessibility_requirement_creation(self):
        """Test creating an accessibility requirement"""
        requirement = AccessibilityRequirement.objects.create(
            code='WHEEL',
            label='Wheelchair Access',
            description='Requires wheelchair accessible facilities',
            added_by=self.user
        )
        
        self.assertEqual(requirement.code, 'WHEEL')
        self.assertEqual(requirement.label, 'Wheelchair Access')
        self.assertTrue(requirement.active)
        
    def test_attendee_accessibility_requirement_link(self):
        """Test linking accessibility requirement to attendee"""
        requirement = AccessibilityRequirement.objects.create(
            code='HEAR',
            label='Hearing Impaired',
            added_by=self.user
        )
        
        attendee_req = AttendeeAccessibilityRequirement.objects.create(
            attendee=self.attendee,
            accessibility_requirement=requirement,
            details='Requires sign language interpreter',
            added_by=self.user
        )
        
        self.assertEqual(attendee_req.attendee, self.attendee)
        self.assertEqual(attendee_req.accessibility_requirement, requirement)
        self.assertEqual(attendee_req.details, 'Requires sign language interpreter')


class DietaryRequirementModelTest(TestCase):
    """Test cases for DietaryRequirement and AttendeeDietaryRequirement"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='dietuser',
            email='diet@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Diet Event',
            display_code='DE001',
            display_identifier='DE001CONF222',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Diet',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_dietary_requirement_creation(self):
        """Test creating a dietary requirement"""
        requirement = DietaryRequirement.objects.create(
            code='VEGAN',
            label='Vegan',
            description='No animal products',
            added_by=self.user
        )
        
        self.assertEqual(requirement.code, 'VEGAN')
        self.assertEqual(requirement.label, 'Vegan')
        
    def test_attendee_dietary_requirement_link(self):
        """Test linking dietary requirement to attendee"""
        requirement = DietaryRequirement.objects.create(
            code='GLUTE',
            label='Gluten Free',
            added_by=self.user
        )
        
        attendee_req = AttendeeDietaryRequirement.objects.create(
            attendee=self.attendee,
            dietary_requirement=requirement,
            details='Severe allergy',
            added_by=self.user
        )
        
        self.assertEqual(attendee_req.attendee, self.attendee)
        self.assertEqual(attendee_req.dietary_requirement, requirement)


class MedicalConditionModelTest(TestCase):
    """Test cases for MedicalCondition and AttendeeMedicalCondition"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='meduser',
            email='med@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Medical Event',
            display_code='ME001',
            display_identifier='ME001CONF333',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Medical',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_medical_condition_creation(self):
        """Test creating a medical condition"""
        condition = MedicalCondition.objects.create(
            code='ASTHM',
            label='Asthma',
            description='Respiratory condition',
            added_by=self.user
        )
        
        self.assertEqual(condition.code, 'ASTHM')
        self.assertEqual(condition.label, 'Asthma')
        
    def test_attendee_medical_condition_link(self):
        """Test linking medical condition to attendee"""
        condition = MedicalCondition.objects.create(
            code='DIABE',
            label='Diabetes',
            added_by=self.user
        )
        
        attendee_condition = AttendeeMedicalCondition.objects.create(
            attendee=self.attendee,
            medical_condition=condition,
            details='Type 1, requires insulin',
            added_by=self.user
        )
        
        self.assertEqual(attendee_condition.attendee, self.attendee)
        self.assertEqual(attendee_condition.medical_condition, condition)


class EmergencyContactModelTest(TestCase):
    """Test cases for EmergencyContact model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='emerguser',
            email='emerg@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Emergency Event',
            display_code='EE001',
            display_identifier='EE001CONF444',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Emergency',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_emergency_contact_creation(self):
        """Test creating an emergency contact"""
        contact = EmergencyContact.objects.create(
            attendee=self.attendee,
            first_name='Jane',
            last_name='Doe',
            relationship=HumanRelationshipChoices.SPOUSE,
            phone_number='+1234567890',
            email='jane@example.com',
            primary_contact=True,
            added_by=self.user
        )
        
        self.assertEqual(contact.attendee, self.attendee)
        self.assertEqual(contact.first_name, 'Jane')
        self.assertEqual(contact.last_name, 'Doe')
        self.assertTrue(contact.primary_contact)
        
    def test_emergency_contact_full_name_property(self):
        """Test the full_name property"""
        contact = EmergencyContact.objects.create(
            attendee=self.attendee,
            first_name='John',
            last_name='Smith',
            relationship=HumanRelationshipChoices.FRIEND,
            phone_number='+9876543210',
            added_by=self.user
        )
        
        self.assertEqual(contact.full_name, 'John Smith')


class ConsentModelTest(TestCase):
    """Test cases for Consent and AttendeeConsent models"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='consentuser',
            email='consent@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Consent Event',
            display_code='CE001',
            display_identifier='CE001CONF555',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Consent',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_consent_creation(self):
        """Test creating a consent"""
        consent = Consent.objects.create(
            event=self.event,
            code='PHOTO',
            title='Photography Consent',
            description='Allow photos to be taken',
            version='1.0',
            required=True,
            defined_by=self.user
        )
        
        self.assertEqual(consent.code, 'PHOTO')
        self.assertEqual(consent.title, 'Photography Consent')
        self.assertTrue(consent.required)
        
    def test_consent_version_validation(self):
        """Test that version format is validated"""
        consent = Consent(
            event=self.event,
            code='TEST',
            title='Test Consent',
            description='Test',
            version='invalid',
            defined_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            consent.clean()
            
    def test_attendee_consent_creation(self):
        """Test creating attendee consent"""
        consent = Consent.objects.create(
            event=self.event,
            code='VIDEO',
            title='Video Consent',
            description='Allow video recording',
            version='2.1',
            defined_by=self.user
        )
        
        attendee_consent = AttendeeConsent.objects.create(
            attendee=self.attendee,
            consent=consent,
            consent_given=True,
            given_at=timezone.now(),
            given_by=self.user,
            recorded_by=self.user
        )
        
        self.assertEqual(attendee_consent.attendee, self.attendee)
        self.assertEqual(attendee_consent.consent, consent)
        self.assertTrue(attendee_consent.consent_given)


class EventAttendanceModelTest(TestCase):
    """Test cases for EventAttendance model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='attuser',
            email='att@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Attendance Event',
            display_code='ATE001',
            display_identifier='ATE001CONF666',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Attendance',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
    def test_event_attendance_creation(self):
        """Test creating event attendance"""
        attendance = EventAttendance.objects.create(
            event=self.event,
            attendee=self.attendee
        )
        
        self.assertEqual(attendance.event, self.event)
        self.assertEqual(attendance.attendee, self.attendee)
        
    def test_event_attendance_check_in(self):
        """Test checking in an attendee"""
        attendance = EventAttendance.objects.create(
            event=self.event,
            attendee=self.attendee
        )
        
        check_in_time = timezone.now()
        attendance.check_in(check_in_time, self.user)
        
        self.assertIsNotNone(attendance.check_in_time)
        self.assertTrue(attendance.is_checked_in)
        self.assertEqual(attendance.check_in_by, self.user)
        
    def test_event_attendance_check_out(self):
        """Test checking out an attendee"""
        attendance = EventAttendance.objects.create(
            event=self.event,
            attendee=self.attendee
        )
        
        # First check in
        attendance.check_in(timezone.now(), self.user)
        
        # Then check out
        check_out_time = timezone.now() + timedelta(hours=2)
        attendance.check_out(check_out_time, self.user)
        
        self.assertIsNotNone(attendance.check_out_time)
        self.assertTrue(attendance.is_checked_out)


class AttendeeOrganisationModelTest(TestCase):
    """Test cases for AttendeeOrganisation model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='orguser',
            email='org@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Org Event',
            display_code='OE001',
            display_identifier='OE001CONF777',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32)
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Org',
            last_name='Test',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.user
        )
        
    def test_attendee_organisation_creation(self):
        """Test linking attendee to organisation"""
        link = AttendeeOrganisation.objects.create(
            attendee=self.attendee,
            organisation=self.organisation,
            added_by=self.user
        )
        
        self.assertEqual(link.attendee, self.attendee)
        self.assertEqual(link.organisation, self.organisation)
        
    def test_add_organisation_method(self):
        """Test the add_organisation method on Attendee"""
        link = self.attendee.add_organisation(self.organisation)
        
        self.assertIsNotNone(link)
        self.assertEqual(link.attendee, self.attendee)
        self.assertEqual(link.organisation, self.organisation)
        
    def test_is_part_of_organisation_method(self):
        """Test the is_part_of_organisation method"""
        self.attendee.add_organisation(self.organisation)
        
        self.assertTrue(self.attendee.is_part_of_organisation(self.organisation))


class VerificationModelTest(TestCase):
    """Test cases for RequiresVerificationModel mixin"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='verifyuser',
            email='verify@example.com',
            password='testpass123'
        )
        
        self.verifier = User.objects.create_user(
            username='verifier',
            email='verifier@example.com',
            password='testpass123'
        )
        
    def test_verification_default_status(self):
        """Test that default verification status is PENDING"""
        requirement = AccessibilityRequirement.objects.create(
            code='TEST',
            label='Test',
            added_by=self.user
        )
        
        self.assertEqual(requirement.verification_status, VerificationStatus.PENDING)
        self.assertTrue(requirement.is_pending)
        
    def test_mark_verified_method(self):
        """Test marking as verified"""
        requirement = AccessibilityRequirement.objects.create(
            code='VERIFY',
            label='Verify Test',
            added_by=self.user
        )
        
        requirement.mark_verified(self.verifier)
        
        self.assertEqual(requirement.verification_status, VerificationStatus.VERIFIED)
        self.assertTrue(requirement.is_verified)
        self.assertEqual(requirement.verified_by, self.verifier)
        self.assertIsNotNone(requirement.verified_updated_at)
        
    def test_mark_rejected_method(self):
        """Test marking as rejected"""
        requirement = AccessibilityRequirement.objects.create(
            code='REJECT',
            label='Reject Test',
            added_by=self.user
        )
        
        requirement.mark_rejected(self.verifier)
        
        self.assertEqual(requirement.verification_status, VerificationStatus.REJECTED)
        self.assertTrue(requirement.is_rejected)
        self.assertEqual(requirement.verified_by, self.verifier)
        
    def test_mark_pending_method(self):
        """Test marking back to pending"""
        requirement = AccessibilityRequirement.objects.create(
            code='PEND',
            label='Pending Test',
            added_by=self.user
        )
        
        # First verify it
        requirement.mark_verified(self.verifier)
        
        # Then mark as pending again
        requirement.mark_pending()
        
        self.assertEqual(requirement.verification_status, VerificationStatus.PENDING)
        self.assertTrue(requirement.is_pending)
        self.assertIsNone(requirement.verified_by)
        self.assertIsNone(requirement.verified_updated_at)
