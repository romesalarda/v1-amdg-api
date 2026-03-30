from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import IntegrityError
from datetime import timedelta, date
import uuid

from apps.events.models import (
    Event, EventType, EventStatusChoices, EventSettings,
    EventAuthorization, EventAuthorizationStatusChoices,
    EventPermission, EventPermissionAssignment, EventPermissionCategoryChoices,
    EventRole, EventRoleAssignment, EventRoleCategoryChoices,
    EventStaff, EventStaffAvailability, EventStaffInvite,
    EventReview,
    EventQuestion, EventQuestionTypeChoices, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice
)
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee, AttendeeRelationship

User = get_user_model()


class EventTypeModelTest(TestCase):
    """Test cases for the EventType model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
    
    def test_event_type_creation(self):
        """Test basic event type creation"""
        event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            description='Conference events',
            created_by=self.user
        )
        
        self.assertEqual(event_type.title, 'Conference')
        self.assertEqual(event_type.code, 'CONF')
        self.assertEqual(event_type.description, 'Conference events')
        self.assertEqual(event_type.created_by, self.user)
        self.assertIsNotNone(event_type.created_at)
        
    def test_event_type_code_auto_generation(self):
        """Test that code is auto-generated from title if not provided"""
        event_type = EventType.objects.create(
            title='Workshop Sessions',
            created_by=self.user
        )
        
        self.assertEqual(event_type.code, 'WORKS')
        
    def test_event_type_code_uppercase_conversion(self):
        """Test that code is converted to uppercase"""
        event_type = EventType.objects.create(
            title='Retreat',
            code='retr',
            created_by=self.user
        )
        
        self.assertEqual(event_type.code, 'RETR')
        
    def test_event_type_code_max_length(self):
        """Test that code is truncated to max length"""
        event_type = EventType.objects.create(
            title='Very Long Event Type Name',
            created_by=self.user
        )
        
        self.assertEqual(len(event_type.code), 5)
        
    def test_event_type_title_trimming(self):
        """Test that title is trimmed"""
        event_type = EventType.objects.create(
            title='  Conference  ',
            code='CONF',
            created_by=self.user
        )
        
        self.assertEqual(event_type.title, 'Conference')
        
    def test_event_type_unique_code_constraint(self):
        """Test that code must be unique"""
        EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        with self.assertRaises(IntegrityError):
            EventType.objects.create(
                title='Another Conference',
                code='CONF',
                created_by=self.user
            )
            
    def test_event_type_str_representation(self):
        """Test the string representation"""
        event_type = EventType.objects.create(
            title='Workshop',
            code='WORK',
            created_by=self.user
        )
        
        self.assertEqual(str(event_type), 'Workshop')


class EventModelTest(TestCase):
    """Test cases for the Event model"""
    
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
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.start_time = timezone.now() + timedelta(days=30)
        self.end_time = timezone.now() + timedelta(days=32)
    
    def test_event_creation(self):
        """Test basic event creation"""
        event = Event.objects.create(
            title='Test Conference 2025',
            display_code='TC2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )
        
        self.assertIsNotNone(event.event_id)
        self.assertEqual(event.title, 'Test Conference 2025')
        self.assertEqual(event.display_code, 'TC2025')
        self.assertEqual(event.status, EventStatusChoices.DRAFTING)
        self.assertIsNotNone(event.display_identifier)
        self.assertIsNotNone(event.url_safe_title)
        
    def test_event_url_safe_title_generation(self):
        """Test that url_safe_title is generated from title"""
        event = Event.objects.create(
            title='Test Conference 2025',
            display_code='TC2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )

        self.assertTrue(event.url_safe_title.startswith('test-conference-2025-'))
        
    def test_event_display_identifier_generation(self):
        """Test that display_identifier is auto-generated"""
        event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )
        
        self.assertIsNotNone(event.display_identifier)
        self.assertTrue(event.display_identifier.startswith('TE2025CONF'))
        self.assertTrue(len(event.display_identifier) >= 6)
        
    def test_event_start_before_end_validation(self):
        """Test that start_datetime must be before end_datetime"""
        with self.assertRaises(ValidationError):
            Event.objects.create(
                title='Invalid Event',
                display_code='IE2025',
                created_by=self.user,
                event_type=self.event_type,
                start_datetime=self.end_time,
                end_datetime=self.start_time,
                organisation=self.organisation
            )
            
    def test_event_start_equals_end_validation(self):
        """Test that start_datetime cannot equal end_datetime"""
        same_time = timezone.now() + timedelta(days=30)
        
        with self.assertRaises(ValidationError):
            Event.objects.create(
                title='Invalid Event',
                display_code='IE2025',
                created_by=self.user,
                event_type=self.event_type,
                start_datetime=same_time,
                end_datetime=same_time,
                organisation=self.organisation
            )
            
    def test_event_created_by_required(self):
        """Test that created_by is required"""
        with self.assertRaises(ValidationError):
            Event.objects.create(
                title='Invalid Event',
                display_code='IE2025',
                event_type=self.event_type,
                start_datetime=self.start_time,
                end_datetime=self.end_time,
                created_by=None,
                organisation=self.organisation
            )
            
    def test_event_unique_display_code(self):
        """Test that display_code must be unique"""
        Event.objects.create(
            title='Event 1',
            display_code='EV2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )
        
        with self.assertRaises(ValidationError):
            Event.objects.create(
                title='Event 2',
                display_code='EV2025',
                created_by=self.user,
                event_type=self.event_type,
                start_datetime=self.start_time,
                end_datetime=self.end_time,
                organisation=self.organisation
            )
            
    def test_event_duration_days_property(self):
        """Test the duration_days property"""
        event = Event.objects.create(
            title='Multi-Day Event',
            display_code='MD2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=33),
            organisation=self.organisation
        )
        
        self.assertGreaterEqual(event.duration_days, 3)
        
    def test_event_is_ongoing_property(self):
        """Test the is_ongoing property"""
        # Event in the future
        future_event = Event.objects.create(
            title='Future Event',
            display_code='FE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        self.assertFalse(future_event.is_ongoing)
        
        # Event happening now
        ongoing_event = Event.objects.create(
            title='Ongoing Event',
            display_code='OE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() - timedelta(hours=1),
            end_datetime=timezone.now() + timedelta(hours=1),
            organisation=self.organisation
        )
        
        self.assertTrue(ongoing_event.is_ongoing)
        
    def test_event_max_capacity_reached_property(self):
        """Test the max_capacity_reached property"""
        event = Event.objects.create(
            title='Limited Event',
            display_code='LE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            maximum_attendance=2,
            organisation=self.organisation
        )
        
        self.assertFalse(event.max_capacity_reached)
        
        # Add attendees
        Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertFalse(event.max_capacity_reached)
        
        Attendee.objects.create(
            first_name='Jane',
            last_name='Smith',
            event=event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SPOUSE,
            defined_by=self.user,
            date_of_birth=date(1992, 2, 2)
        )
        
        self.assertTrue(event.max_capacity_reached)
        
    def test_event_number_of_attendees_property(self):
        """Test the number_of_attendees property"""
        event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )
        
        self.assertEqual(event.number_of_attendees, 0)
        
        Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.assertEqual(event.number_of_attendees, 1)
        
    def test_event_str_representation(self):
        """Test the string representation"""
        event = Event.objects.create(
            title='Amazing Conference',
            display_code='AC2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )
        
        self.assertEqual(str(event), 'Amazing Conference')
        
    def test_event_repr_representation(self):
        """Test the repr representation"""
        event = Event.objects.create(
            title='Amazing Conference',
            display_code='AC2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )
        
        self.assertIn('AC2025', repr(event))
        self.assertIn('Amazing Conference', repr(event))


class EventSettingsModelTest(TestCase):
    """Test cases for the EventSettings model"""
    
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
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
    
    def test_event_settings_creation(self):
        """Test that event settings are auto-created via signal"""
        # Settings should be auto-created by signal when event is created
        self.assertTrue(hasattr(self.event, 'settings'))
        settings = self.event.settings
        
        self.assertEqual(settings.event, self.event)
        self.assertIsNotNone(settings)
        
        # Test updating settings
        settings.payment_enabled = True
        settings.product_selling_enabled = True
        settings.donation_enabled = True
        settings.save()
        
        settings.refresh_from_db()
        self.assertTrue(settings.payment_enabled)
        self.assertTrue(settings.product_selling_enabled)
        self.assertTrue(settings.donation_enabled)
        
    def test_event_settings_payment_disabled_validation(self):
        """Test that payment-dependent features cannot be enabled when payment is disabled"""
        settings = self.event.settings
        
        # Test donation cannot be enabled without payment
        settings.payment_enabled = False
        settings.donation_enabled = True
        with self.assertRaises(ValidationError):
            settings.clean()
            
        # Reset and test refunds
        settings.donation_enabled = False
        settings.refunds_enabled = True
        with self.assertRaises(ValidationError):
            settings.clean()
            
        # Reset and test product selling
        settings.refunds_enabled = False
        settings.product_selling_enabled = True
        with self.assertRaises(ValidationError):
            settings.clean()
            
    def test_event_settings_enable_payments_method(self):
        """Test the enable_payments method"""
        settings = self.event.settings
        settings.payment_enabled = False
        settings.save()
        
        settings.enable_payments()
        
        self.assertTrue(settings.payment_enabled)
        
    def test_event_settings_disable_payments_method(self):
        """Test the disable_payments method"""
        settings = self.event.settings
        settings.payment_enabled = True
        settings.donation_enabled = True
        settings.refunds_enabled = True
        settings.product_selling_enabled = True
        settings.save()
        
        settings.disable_payments()
        
        self.assertFalse(settings.payment_enabled)
        self.assertFalse(settings.donation_enabled)
        self.assertFalse(settings.refunds_enabled)
        self.assertFalse(settings.product_selling_enabled)
        
    def test_event_settings_event_required(self):
        """Test that event is required"""
        with self.assertRaises(Exception):  # Will raise IntegrityError or ValidationError
            settings = EventSettings(event=None, payment_enabled=True)
            settings.save()
            
    def test_event_settings_str_representation(self):
        """Test the string representation"""
        settings = self.event.settings
        
        self.assertIn(self.event.title, str(settings))
        
    def test_event_settings_repr_representation(self):
        """Test the repr representation"""
        settings = self.event.settings
        settings.payment_enabled = True
        settings.save()
        
        self.assertIn(self.event.display_code, repr(settings))
        self.assertIn('payment_enabled=True', repr(settings))


class EventAuthorizationModelTest(TestCase):
    """Test cases for the EventAuthorization model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.reviewer = User.objects.create_user(
            username='reviewer',
            email='reviewer@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
    
    def test_event_authorization_creation(self):
        """Test basic event authorization creation"""
        auth = EventAuthorization.objects.create(
            event=self.event,
            reviewed_by=self.reviewer,
            status=EventAuthorizationStatusChoices.APPROVED,
            reason='Looks good',
            notes='All requirements met'
        )
        
        self.assertIsNotNone(auth.review_id)
        self.assertIsNotNone(auth.review_code)
        self.assertEqual(auth.event, self.event)
        self.assertEqual(auth.reviewed_by, self.reviewer)
        self.assertEqual(auth.status, EventAuthorizationStatusChoices.APPROVED)
        
    def test_event_authorization_review_code_generation(self):
        """Test that review_code is auto-generated"""
        auth = EventAuthorization.objects.create(
            event=self.event,
            reviewed_by=self.reviewer
        )
        
        self.assertIsNotNone(auth.review_code)
        self.assertTrue(auth.review_code.startswith('EVT-AUTH-'))
        
    def test_event_authorization_default_status(self):
        """Test default status is PENDING"""
        auth = EventAuthorization.objects.create(
            event=self.event,
            reviewed_by=self.reviewer
        )
        
        self.assertEqual(auth.status, EventAuthorizationStatusChoices.PENDING)
        
    def test_event_authorization_unique_together(self):
        """Test that event and reviewed_by must be unique together"""
        EventAuthorization.objects.create(
            event=self.event,
            reviewed_by=self.reviewer
        )
        
        with self.assertRaises(IntegrityError):
            EventAuthorization.objects.create(
                event=self.event,
                reviewed_by=self.reviewer
            )
            
    def test_event_authorization_str_representation(self):
        """Test the string representation"""
        auth = EventAuthorization.objects.create(
            event=self.event,
            reviewed_by=self.reviewer,
            status=EventAuthorizationStatusChoices.APPROVED
        )
        
        self.assertIn(str(self.event), str(auth))
        self.assertIn(str(self.reviewer), str(auth))
        self.assertIn('APPROVED', str(auth))


class EventPermissionModelTest(TestCase):
    """Test cases for the EventPermission model"""
    
    def setUp(self):
        """Set up test data"""
        pass
    
    def test_event_permission_creation(self):
        """Test basic event permission creation"""
        permission = EventPermission.objects.create(
            name='Can Manage Products',
            code='manage_products',
            description='Allows managing event products',
            category=EventPermissionCategoryChoices.PRODUCT_MANAGEMENT
        )
        
        self.assertIsNotNone(permission.permission_id)
        self.assertEqual(permission.name, 'Can Manage Products')
        self.assertEqual(permission.code, 'manage_products')
        self.assertEqual(permission.category, EventPermissionCategoryChoices.PRODUCT_MANAGEMENT)
        
    def test_event_permission_unique_name(self):
        """Test that name must be unique"""
        EventPermission.objects.create(
            name='Can Edit Event',
            code='edit_event'
        )
        
        with self.assertRaises(IntegrityError):
            EventPermission.objects.create(
                name='Can Edit Event',
                code='edit_event_2'
            )
            
    def test_event_permission_unique_code(self):
        """Test that code must be unique"""
        EventPermission.objects.create(
            name='Can Edit Event',
            code='edit_event'
        )
        
        with self.assertRaises(IntegrityError):
            EventPermission.objects.create(
                name='Can Edit Event 2',
                code='edit_event'
            )
            
    def test_event_permission_default_category(self):
        """Test default category is GENERAL"""
        permission = EventPermission.objects.create(
            name='General Permission',
            code='general_perm'
        )
        
        self.assertEqual(permission.category, EventPermissionCategoryChoices.GENERAL)
        
    def test_event_permission_str_representation(self):
        """Test the string representation"""
        permission = EventPermission.objects.create(
            name='Can View Reports',
            code='view_reports'
        )
        
        self.assertEqual(str(permission), 'Can View Reports')


class EventPermissionAssignmentModelTest(TestCase):
    """Test cases for the EventPermissionAssignment model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.assigner = User.objects.create_user(
            username='assigner',
            email='assigner@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        self.permission = EventPermission.objects.create(
            name='Can Edit Event',
            code='edit_event'
        )
    
    def test_event_permission_assignment_creation(self):
        """Test basic permission assignment creation"""
        assignment = EventPermissionAssignment.objects.create(
            event=self.event,
            user=self.user,
            permission=self.permission,
            assigned_by=self.assigner
        )
        
        self.assertEqual(assignment.event, self.event)
        self.assertEqual(assignment.user, self.user)
        self.assertEqual(assignment.permission, self.permission)
        self.assertEqual(assignment.assigned_by, self.assigner)
        self.assertIsNotNone(assignment.assigned_at)


class EventRoleModelTest(TestCase):
    """Test cases for the EventRole model"""
    
    def setUp(self):
        """Set up test data"""
        pass
    
    def test_event_role_creation(self):
        """Test basic event role creation"""
        role = EventRole.objects.create(
            name='Event Coordinator',
            code='COORD',
            description='Coordinates event activities',
            category=EventRoleCategoryChoices.COORDINATOR
        )
        
        self.assertEqual(role.name, 'Event Coordinator')
        self.assertEqual(role.code, 'COORD')
        self.assertEqual(role.description, 'Coordinates event activities')
        self.assertEqual(role.category, EventRoleCategoryChoices.COORDINATOR)
        
    def test_event_role_unique_name(self):
        """Test that name must be unique"""
        EventRole.objects.create(
            name='Volunteer',
            code='VOL'
        )
        
        with self.assertRaises(IntegrityError):
            EventRole.objects.create(
                name='Volunteer',
                code='VOL2'
            )
            
    def test_event_role_unique_code(self):
        """Test that code must be unique"""
        EventRole.objects.create(
            name='Volunteer',
            code='VOL'
        )
        
        with self.assertRaises(IntegrityError):
            EventRole.objects.create(
                name='Volunteer 2',
                code='VOL'
            )
            
    def test_event_role_default_category(self):
        """Test default category is VOLUNTEER"""
        role = EventRole.objects.create(
            name='Helper',
            code='HELP'
        )
        
        self.assertEqual(role.category, EventRoleCategoryChoices.VOLUNTEER)
        
    def test_event_role_str_representation(self):
        """Test the string representation"""
        role = EventRole.objects.create(
            name='Speaker',
            code='SPKR'
        )
        
        self.assertEqual(str(role), 'Speaker')


class EventRoleAssignmentModelTest(TestCase):
    """Test cases for the EventRoleAssignment model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.assigner = User.objects.create_user(
            username='assigner',
            email='assigner@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        self.role = EventRole.objects.create(
            name='Volunteer',
            code='VOL'
        )
    
    def test_event_role_assignment_creation(self):
        """Test basic role assignment creation"""
        assignment = EventRoleAssignment.objects.create(
            event=self.event,
            user=self.user,
            role=self.role,
            assigned_by=self.assigner
        )
        
        self.assertEqual(assignment.event, self.event)
        self.assertEqual(assignment.user, self.user)
        self.assertEqual(assignment.role, self.role)
        self.assertEqual(assignment.assigned_by, self.assigner)
        self.assertIsNotNone(assignment.assigned_at)
        
    def test_event_role_assignment_unique_together(self):
        """Test that event, user, and role must be unique together"""
        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.user,
            role=self.role,
            assigned_by=self.assigner
        )
        
        with self.assertRaises(IntegrityError):
            EventRoleAssignment.objects.create(
                event=self.event,
                user=self.user,
                role=self.role,
                assigned_by=self.assigner
            )
            
    def test_event_role_assignment_str_representation(self):
        """Test the string representation"""
        assignment = EventRoleAssignment.objects.create(
            event=self.event,
            user=self.user,
            role=self.role,
            assigned_by=self.assigner
        )
        
        self.assertIn(self.user.username, str(assignment))
        self.assertIn(self.role.name, str(assignment))
        self.assertIn(self.event.display_identifier, str(assignment))


class EventStaffModelTest(TestCase):
    """Test cases for the EventStaff model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.staff_user = User.objects.create_user(
            username='staffuser',
            email='staffuser@example.com',
            password='testpass123'
        )
        
        self.assigner = User.objects.create_user(
            username='assigner',
            email='assigner@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
    
    def test_event_staff_creation(self):
        """Test basic event staff creation"""
        staff = EventStaff.objects.create(
            event=self.event,
            user=self.staff_user,
            assigned_by=self.assigner,
            notes='Experienced staff member'
        )
        
        self.assertIsNotNone(staff.staff_id)
        self.assertEqual(staff.event, self.event)
        self.assertEqual(staff.user, self.staff_user)
        self.assertEqual(staff.assigned_by, self.assigner)
        self.assertEqual(staff.notes, 'Experienced staff member')
        self.assertIsNotNone(staff.assigned_at)
        
    def test_event_staff_unique_together(self):
        """Test that event and user must be unique together"""
        EventStaff.objects.create(
            event=self.event,
            user=self.staff_user,
            assigned_by=self.assigner
        )
        
        with self.assertRaises(IntegrityError):
            EventStaff.objects.create(
                event=self.event,
                user=self.staff_user,
                assigned_by=self.assigner
            )


class EventStaffAvailabilityModelTest(TestCase):
    """Test cases for the EventStaffAvailability model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.staff_user = User.objects.create_user(
            username='staffuser',
            email='staffuser@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        self.staff = EventStaff.objects.create(
            event=self.event,
            user=self.staff_user
        )
    
    def test_event_staff_availability_creation(self):
        """Test basic staff availability creation"""
        available_from = timezone.now() + timedelta(days=30)
        available_to = timezone.now() + timedelta(days=30, hours=8)
        
        availability = EventStaffAvailability.objects.create(
            staff=self.staff,
            available_from=available_from,
            available_to=available_to
        )
        
        self.assertEqual(availability.staff, self.staff)
        self.assertEqual(availability.available_from, available_from)
        self.assertEqual(availability.available_to, available_to)
        self.assertIsNotNone(availability.created_at)
        
    def test_event_staff_availability_validation(self):
        """Test that available_from must be before available_to"""
        available_from = timezone.now() + timedelta(days=30)
        available_to = timezone.now() + timedelta(days=29)
        
        availability = EventStaffAvailability(
            staff=self.staff,
            available_from=available_from,
            available_to=available_to
        )
        
        with self.assertRaises(ValueError):
            availability.validate_availability()


class EventReviewModelTest(TestCase):
    """Test cases for the EventReview model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.reviewer = User.objects.create_user(
            username='reviewer',
            email='reviewer@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
    
    def test_event_review_creation(self):
        """Test basic event review creation"""
        review = EventReview.objects.create(
            event=self.event,
            user=self.reviewer,
            rating=5,
            comment='Excellent event!',
            approved=True
        )
        
        self.assertEqual(review.event, self.event)
        self.assertEqual(review.user, self.reviewer)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.comment, 'Excellent event!')
        self.assertTrue(review.approved)
        self.assertIsNotNone(review.created_at)
        
    def test_event_review_default_approved(self):
        """Test default approved status is False"""
        review = EventReview.objects.create(
            event=self.event,
            user=self.reviewer,
            rating=4
        )
        
        self.assertFalse(review.approved)
        
    def test_event_review_str_representation(self):
        """Test the string representation"""
        review = EventReview.objects.create(
            event=self.event,
            user=self.reviewer,
            rating=5
        )
        
        self.assertIn(str(self.reviewer), str(review))
        self.assertIn(str(self.event), str(review))
        self.assertIn('5', str(review))


class EventQuestionModelTest(TestCase):
    """Test cases for the EventQuestion model"""
    
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
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
    
    def test_event_question_creation(self):
        """Test basic event question creation"""
        question = EventQuestion.objects.create(
            event=self.event,
            question_title='What is your name?',
            question_body='Please provide your full name',
            question_type=EventQuestionTypeChoices.SHORT_ANSWER,
            required=True,
            public=True,
            order=1
        )
        
        self.assertIsNotNone(question.id)
        self.assertEqual(question.event, self.event)
        self.assertEqual(question.question_title, 'What is your name?')
        self.assertEqual(question.question_type, EventQuestionTypeChoices.SHORT_ANSWER)
        self.assertTrue(question.required)
        
    def test_event_question_slider_validation(self):
        """Test slider question requires min and max values"""
        with self.assertRaises(ValidationError):
            question = EventQuestion.objects.create(
                event=self.event,
                question_title='Rate our service',
                question_body='Please rate from 1-10',
                question_type=EventQuestionTypeChoices.SLIDER,
                order=1
            )
            question.clean()
            
    def test_event_question_slider_min_max_validation(self):
        """Test slider min value must be less than max value"""
        with self.assertRaises(ValidationError):
            question = EventQuestion(
                event=self.event,
                question_title='Rate our service',
                question_body='Please rate',
                question_type=EventQuestionTypeChoices.SLIDER,
                min_value=10,
                max_value=5,
                order=1
            )
            question.clean()
            
    def test_event_question_non_slider_no_min_max(self):
        """Test non-slider questions cannot have min/max values"""
        with self.assertRaises(ValidationError):
            question = EventQuestion(
                event=self.event,
                question_title='Your name',
                question_body='Please provide name',
                question_type=EventQuestionTypeChoices.SHORT_ANSWER,
                min_value=1,
                max_value=10,
                order=1
            )
            question.clean()
            
    def test_event_question_unique_order_per_event(self):
        """Test that order must be unique per event"""
        EventQuestion.objects.create(
            event=self.event,
            question_title='Question 1',
            question_body='Body 1',
            order=1
        )
        
        with self.assertRaises(IntegrityError):
            from django.db import connection, transaction

            with transaction.atomic():
                EventQuestion.objects.create(
                    event=self.event,
                    question_title='Question 2',
                    question_body='Body 2',
                    order=1
                )
                with connection.cursor() as cursor:
                    cursor.execute('SET CONSTRAINTS unique_question_order_per_event IMMEDIATE')
            
    def test_event_question_ordering(self):
        """Test that questions are ordered by order field"""
        q3 = EventQuestion.objects.create(
            event=self.event,
            question_title='Question 3',
            question_body='Body 3',
            order=3
        )
        q1 = EventQuestion.objects.create(
            event=self.event,
            question_title='Question 1',
            question_body='Body 1',
            order=1
        )
        q2 = EventQuestion.objects.create(
            event=self.event,
            question_title='Question 2',
            question_body='Body 2',
            order=2
        )
        
        questions = list(EventQuestion.objects.filter(event=self.event))
        self.assertEqual(questions[0], q1)
        self.assertEqual(questions[1], q2)
        self.assertEqual(questions[2], q3)
        
    def test_event_question_validate_answer_slider(self):
        """Test answer validation for slider questions"""
        question = EventQuestion.objects.create(
            event=self.event,
            question_title='Rate us',
            question_body='Rate from 1-10',
            question_type=EventQuestionTypeChoices.SLIDER,
            min_value=1,
            max_value=10,
            order=1
        )
        
        # Valid answer
        question.validate_answer('5')
        
        # Invalid - too low
        with self.assertRaises(ValidationError):
            question.validate_answer('0')
            
        # Invalid - too high
        with self.assertRaises(ValidationError):
            question.validate_answer('11')
            
        # Invalid - not an integer
        with self.assertRaises(ValidationError):
            question.validate_answer('abc')
            
    def test_event_question_validate_answer_text(self):
        """Test answer validation for text questions"""
        question = EventQuestion.objects.create(
            event=self.event,
            question_title='Your name',
            question_body='Please provide name',
            question_type=EventQuestionTypeChoices.SHORT_ANSWER,
            order=1
        )
        
        # Valid answer
        question.validate_answer('John Doe')
        
        # Invalid - not a string
        with self.assertRaises(ValidationError):
            question.validate_answer(123)


class EventQuestionOptionModelTest(TestCase):
    """Test cases for the EventQuestionOption model"""
    
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
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        self.question = EventQuestion.objects.create(
            event=self.event,
            question_title='Choose an option',
            question_body='Select one',
            question_type=EventQuestionTypeChoices.SINGLE_CHOICE,
            order=1
        )
    
    def test_event_question_option_creation(self):
        """Test basic question option creation"""
        option = EventQuestionOption.objects.create(
            question=self.question,
            option_text='Option A',
            order=1
        )
        
        self.assertEqual(option.question, self.question)
        self.assertEqual(option.option_text, 'Option A')
        self.assertEqual(option.order, 1)
        self.assertIsNotNone(option.created_at)
        
    def test_event_question_option_unique_order_per_question(self):
        """Test that order must be unique per question"""
        EventQuestionOption.objects.create(
            question=self.question,
            option_text='Option A',
            order=1
        )
        
        with self.assertRaises(IntegrityError):
            EventQuestionOption.objects.create(
                question=self.question,
                option_text='Option B',
                order=1
            )
            
    def test_event_question_option_unique_text_per_question(self):
        """Test that option_text must be unique per question"""
        EventQuestionOption.objects.create(
            question=self.question,
            option_text='Option A',
            order=1
        )
        
        with self.assertRaises(IntegrityError):
            EventQuestionOption.objects.create(
                question=self.question,
                option_text='Option A',
                order=2
            )

from datetime import date

class EventQuestionAnswerModelTest(TestCase):
    """Test cases for the EventQuestionAnswer model"""
    
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
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        self.attendee = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.question = EventQuestion.objects.create(
            event=self.event,
            question_title='What is your name?',
            question_body='Please provide name',
            question_type=EventQuestionTypeChoices.SHORT_ANSWER,
            order=1
        )
    
    def test_event_question_answer_creation(self):
        """Test basic question answer creation"""
        answer = EventQuestionAnswer.objects.create(
            question=self.question,
            attendee=self.attendee,
            answer_text='John Doe'
        )
        
        self.assertEqual(answer.question, self.question)
        self.assertEqual(answer.attendee, self.attendee)
        self.assertEqual(answer.answer_text, 'John Doe')
        self.assertIsNotNone(answer.submitted_at)
        
    def test_event_question_answer_unique_together(self):
        """Test that question and attendee must be unique together"""
        EventQuestionAnswer.objects.create(
            question=self.question,
            attendee=self.attendee,
            answer_text='John Doe'
        )
        
        with self.assertRaises(IntegrityError):
            EventQuestionAnswer.objects.create(
                question=self.question,
                attendee=self.attendee,
                answer_text='Jane Doe'
            )
            
    def test_event_question_answer_validation(self):
        """Test answer validation on clean"""
        slider_question = EventQuestion.objects.create(
            event=self.event,
            question_title='Rate us',
            question_body='Rate from 1-10',
            question_type=EventQuestionTypeChoices.SLIDER,
            min_value=1,
            max_value=10,
            order=2
        )
        
        # Valid answer
        answer = EventQuestionAnswer(
            question=slider_question,
            attendee=self.attendee,
            answer_text='5'
        )
        answer.clean()
        
        # Invalid answer
        with self.assertRaises(ValidationError):
            answer_invalid = EventQuestionAnswer(
                question=slider_question,
                attendee=self.attendee,
                answer_text='15'
            )
            answer_invalid.clean()


class EventQuestionAnswerChoiceModelTest(TestCase):
    """Test cases for the EventQuestionAnswerChoice model"""
    
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
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
        
        self.attendee = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=self.event,
            user=self.user,
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.user,
            date_of_birth=date(1990, 1, 1)
        )
        
        self.question = EventQuestion.objects.create(
            event=self.event,
            question_title='Choose options',
            question_body='Select options',
            question_type=EventQuestionTypeChoices.MULTIPLE_CHOICE,
            order=1
        )
        
        self.option1 = EventQuestionOption.objects.create(
            question=self.question,
            option_text='Option A',
            order=1
        )
        
        self.option2 = EventQuestionOption.objects.create(
            question=self.question,
            option_text='Option B',
            order=2
        )
        
        self.answer = EventQuestionAnswer.objects.create(
            question=self.question,
            attendee=self.attendee,
            answer_text=''
        )
    
    def test_event_question_answer_choice_creation(self):
        """Test basic answer choice creation"""
        choice = EventQuestionAnswerChoice.objects.create(
            answer=self.answer,
            option=self.option1
        )
        
        self.assertEqual(choice.answer, self.answer)
        self.assertEqual(choice.option, self.option1)
        self.assertIsNotNone(choice.selected_at)
        
    def test_event_question_answer_choice_unique_together(self):
        """Test that answer and option must be unique together"""
        EventQuestionAnswerChoice.objects.create(
            answer=self.answer,
            option=self.option1
        )
        
        with self.assertRaises(IntegrityError):
            EventQuestionAnswerChoice.objects.create(
                answer=self.answer,
                option=self.option1
            )
            
    def test_event_question_answer_choice_validation(self):
        """Test that option must belong to the same question as answer"""
        other_question = EventQuestion.objects.create(
            event=self.event,
            question_title='Other question',
            question_body='Different question',
            question_type=EventQuestionTypeChoices.SINGLE_CHOICE,
            order=2
        )
        
        other_option = EventQuestionOption.objects.create(
            question=other_question,
            option_text='Other Option',
            order=1
        )
        
        with self.assertRaises(ValidationError):
            choice = EventQuestionAnswerChoice(
                answer=self.answer,
                option=other_option
            )
            choice.clean()


class EventStaffInviteModelTest(TestCase):
    """Test cases for the EventStaffInvite model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.target_user = User.objects.create_user(
            username='targetuser',
            email='targetuser@example.com',
            password='testpass123'
        )
        
        self.inviter = User.objects.create_user(
            username='inviter',
            email='inviter@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.organisation
        )
    
    def test_staff_invite_creation(self):
        """Test basic staff invite creation"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        self.assertIsNotNone(invite.id)
        self.assertEqual(invite.event, self.event)
        self.assertEqual(invite.target_user, self.target_user)
        self.assertEqual(invite.invited_by, self.inviter)
        self.assertFalse(invite.accepted)
        self.assertTrue(invite.is_active)
        self.assertIsNotNone(invite.added_at)
        self.assertIsNone(invite.accepted_at)
    
    def test_staff_invite_unique_constraint(self):
        """Test that event and target_user must be unique together"""
        EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter
        )
        
        with self.assertRaises(IntegrityError):
            EventStaffInvite.objects.create(
                event=self.event,
                target_user=self.target_user,
                invited_by=self.inviter
            )
    
    def test_staff_invite_is_valid_active(self):
        """Test is_valid property returns True for active, unexpired, unaccepted invite"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        self.assertTrue(invite.is_valid)
    
    def test_staff_invite_is_valid_inactive(self):
        """Test is_valid property returns False for inactive invite"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter,
            is_active=False
        )
        
        self.assertFalse(invite.is_valid)
    
    def test_staff_invite_is_valid_accepted(self):
        """Test is_valid property returns False for accepted invite"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter
        )
        invite.accepted = True
        invite.save()
        
        self.assertFalse(invite.is_valid)
    
    def test_staff_invite_is_valid_expired(self):
        """Test is_valid property returns False for expired invite"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        self.assertFalse(invite.is_valid)
    
    def test_staff_invite_accept_invite_success(self):
        """Test accepting a valid invite"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter
        )
        
        invite.accept_invite()
        
        self.assertTrue(invite.accepted)
        self.assertIsNotNone(invite.accepted_at)
        self.assertFalse(invite.is_active)
    
    def test_staff_invite_accept_invalid_invite_fails(self):
        """Test accepting an invalid invite raises error"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter,
            is_active=False
        )
        
        with self.assertRaises(ValidationError):
            invite.accept_invite()
    
    def test_staff_invite_clean_past_expiry_fails(self):
        """Test that clean() validates expiry date is not in the past"""
        invite = EventStaffInvite(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        with self.assertRaises(ValidationError):
            invite.clean()
    
    def test_staff_invite_str_representation(self):
        """Test the string representation"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter
        )
        
        self.assertIn(str(self.target_user), str(invite))
        self.assertIn(self.event.title, str(invite))
    
    def test_staff_invite_repr_representation(self):
        """Test the repr representation"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter
        )
        
        repr_str = repr(invite)
        self.assertIn('EventStaffInvite', repr_str)
        self.assertIn(str(invite.id), repr_str)
        self.assertIn('accepted=False', repr_str)
    
    def test_staff_invite_no_expiry(self):
        """Test invite without expiry date is valid"""
        invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter,
            expires_at=None
        )
        
        self.assertTrue(invite.is_valid)
    
    def test_staff_invite_ordering(self):
        """Test that invites are ordered by added_at descending"""
        invite1 = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.inviter
        )
        
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        
        invite2 = EventStaffInvite.objects.create(
            event=self.event,
            target_user=other_user,
            invited_by=self.inviter
        )
        
        invites = list(EventStaffInvite.objects.all())
        self.assertEqual(invites[0], invite2)
        self.assertEqual(invites[1], invite1)
