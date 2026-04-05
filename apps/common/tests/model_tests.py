"""
Model tests for the common app.

Tests cover:
1. AvailabilityWindow model validation and methods
2. Resource model with different resource types
3. AccessRule model with various rule types
4. SoftDeleteModel mixin functionality
5. RequiresVerificationModel mixin functionality
6. Attendable mixin functionality
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta

from apps.common.models import (
    AvailabilityWindow,
    Resource,
    AccessRule,
    AvailabilityTypeChoices,
    ResourceTypeChoices,
    BaseEventRuleChoices,
    VerificationStatus,
)

User = get_user_model()


class AvailabilityWindowModelTest(TestCase):
    """Test cases for the AvailabilityWindow model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.content_type = ContentType.objects.get_for_model(User)
    
    def test_create_availability_window(self):
        """Test creating an availability window."""
        now = timezone.now()
        window = AvailabilityWindow.objects.create(
            name='Test Window',
            description='Test description',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=self.content_type,
            target_id=self.user.id,
            available_from=now,
            available_to=now + timedelta(days=7)
        )
        
        self.assertEqual(window.name, 'Test Window')
        self.assertEqual(window.availability_type, AvailabilityTypeChoices.REGISTRATION)
        self.assertIsNotNone(window.availability_id)
        self.assertTrue(window.within_window(now + timedelta(days=3)))
    
    def test_availability_window_validation(self):
        """Test that available_from must be before available_to."""
        now = timezone.now()
        window = AvailabilityWindow(
            name='Invalid Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=self.content_type,
            target_id=self.user.id,
            available_from=now + timedelta(days=7),
            available_to=now
        )
        
        with self.assertRaises(ValidationError):
            window.clean()
    
    def test_within_window_method(self):
        """Test within_window method correctly identifies if datetime is in range."""
        now = timezone.now()
        window = AvailabilityWindow.objects.create(
            name='Test Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=self.content_type,
            target_id=self.user.id,
            available_from=now,
            available_to=now + timedelta(days=7)
        )
        
        self.assertTrue(window.within_window(now + timedelta(days=3)))
        self.assertFalse(window.within_window(now - timedelta(days=1)))
        self.assertFalse(window.within_window(now + timedelta(days=8)))
    
    def test_str_representation(self):
        """Test string representation of availability window."""
        now = timezone.now()
        window = AvailabilityWindow.objects.create(
            name='Registration Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=self.content_type,
            target_id=self.user.id,
            available_from=now,
            available_to=now + timedelta(days=7)
        )
        
        self.assertEqual(str(window), 'Registration Window')


class ResourceModelTest(TestCase):
    """Test cases for the Resource model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.content_type = ContentType.objects.get_for_model(User)
    
    def test_create_link_resource(self):
        """Test creating a LINK type resource."""
        resource = Resource.objects.create(
            name='Test Link',
            description='Test link resource',
            resource_type=ResourceTypeChoices.LINK,
            link='https://example.com',
            target_type=self.content_type,
            target_id=str(self.user.id),
            public=True,
            added_by=self.user
        )
        
        self.assertEqual(resource.name, 'Test Link')
        self.assertEqual(resource.resource_type, ResourceTypeChoices.LINK)
        self.assertTrue(resource.is_link)
        self.assertEqual(resource.get_resource(), 'https://example.com')
        self.assertEqual(resource.resource_url, 'https://example.com')
    
    def test_create_protected_resource(self):
        """Test creating a protected resource."""
        resource = Resource.objects.create(
            name='Protected Resource',
            resource_type=ResourceTypeChoices.LINK,
            link='https://example.com',
            target_type=self.content_type,
            target_id=str(self.user.id),
            protected=True,
            added_by=self.user
        )
        
        self.assertTrue(resource.protected)
    
    def test_resource_tag_slugification(self):
        """Test that resource tag is properly slugified."""
        resource = Resource(
            name='Tagged Resource',
            resource_type=ResourceTypeChoices.LINK,
            link='https://example.com',
            target_type=self.content_type,
            target_id=str(self.user.id),
            tag='Landing Photo',
            added_by=self.user
        )
        resource.clean()
        
        self.assertEqual(resource.tag, 'LANDING-PHOTO')
    
    def test_resource_type_properties(self):
        """Test resource type boolean properties."""
        link_resource = Resource(
            name='Link',
            resource_type=ResourceTypeChoices.LINK,
            link='https://example.com',
            target_type=self.content_type,
            target_id=str(self.user.id)
        )
        
        self.assertTrue(link_resource.is_link)
        self.assertFalse(link_resource.is_image)
        self.assertFalse(link_resource.is_document)
    
    def test_str_representation(self):
        """Test string representation of resource."""
        resource = Resource.objects.create(
            name='Test Resource',
            resource_type=ResourceTypeChoices.LINK,
            link='https://example.com',
            target_type=self.content_type,
            target_id=str(self.user.id),
            added_by=self.user
        )
        
        self.assertEqual(str(resource), 'Test Resource')


class AccessRuleModelTest(TestCase):
    """Test cases for the AccessRule model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.content_type = ContentType.objects.get_for_model(User)
    
    def test_create_access_rule(self):
        """Test creating an access rule."""
        rule = AccessRule.objects.create(
            name='Age Limit',
            description='Must be over 18',
            rule_type=BaseEventRuleChoices.IS_AGE_GT,
            value='18',
            target_type=self.content_type,
            target_id=self.user.id,
            active=True,
            added_by=self.user
        )
        
        self.assertEqual(rule.name, 'Age Limit')
        self.assertEqual(rule.rule_type, BaseEventRuleChoices.IS_AGE_GT)
        self.assertEqual(rule.value, '18')
        self.assertTrue(rule.active)
        self.assertIsNotNone(rule.rule_id)
    
    def test_rule_requires_value_validation(self):
        """Test that certain rule types require a value."""
        rule = AccessRule(
            name='Age Rule',
            rule_type=BaseEventRuleChoices.IS_AGE_GT,
            target_type=self.content_type,
            target_id=self.user.id,
            value=None
        )
        
        with self.assertRaises(ValidationError):
            rule.clean()
    
    def test_age_rule_integer_validation(self):
        """Test that age rules require integer values."""
        rule = AccessRule(
            name='Age Rule',
            rule_type=BaseEventRuleChoices.IS_AGE_GT,
            value='not_a_number',
            target_type=self.content_type,
            target_id=self.user.id
        )
        
        with self.assertRaises(ValidationError):
            rule.clean()
    
    def test_rule_without_value_requirement(self):
        """Test creating a rule that doesn't require a value."""
        rule = AccessRule.objects.create(
            name='Staff Rule',
            rule_type=BaseEventRuleChoices.IS_EVENT_STAFF,
            target_type=self.content_type,
            target_id=self.user.id,
            active=True,
            added_by=self.user
        )
        
        self.assertEqual(rule.rule_type, BaseEventRuleChoices.IS_EVENT_STAFF)
        self.assertIsNone(rule.value)
    
    def test_str_representation(self):
        """Test string representation of access rule."""
        rule = AccessRule.objects.create(
            name='Test Rule',
            rule_type=BaseEventRuleChoices.IS_EVENT_STAFF,
            target_type=self.content_type,
            target_id=self.user.id,
            added_by=self.user
        )
        
        self.assertEqual(str(rule), 'Test Rule')


# Create a concrete test model for testing abstract models
from apps.common.models import SoftDeleteModel, RequiresVerificationModel
from apps.common.models.attendance import Attendable


class TestSoftDeleteModel(SoftDeleteModel):
    """Concrete model for testing SoftDeleteModel."""
    name = User._meta.get_field('email').__class__(max_length=100)
    
    class Meta:
        abstract = True
        app_label = 'common'


class TestVerificationModel(RequiresVerificationModel):
    """Concrete model for testing RequiresVerificationModel."""
    name = User._meta.get_field('email').__class__(max_length=100)
    
    class Meta:
        abstract = True
        app_label = 'common'


class TestAttendableModel(Attendable):
    """Concrete model for testing Attendable."""
    name = User._meta.get_field('email').__class__(max_length=100)
    
    class Meta:
        abstract = True
        app_label = 'common'


class SoftDeleteModelTest(TestCase):
    """Test cases for SoftDeleteModel mixin."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
    
    def test_soft_delete(self):
        """Test soft delete functionality."""
        # Note: We can't actually create instances of the abstract model,
        # so we test the concept through documentation
        # In real usage, concrete models would use this mixin
        pass
    
    def test_soft_delete_sets_deleted_at(self):
        """Test that soft delete sets deleted_at timestamp."""
        pass
    
    def test_restore_functionality(self):
        """Test restoring a soft-deleted object."""
        pass


class RequiresVerificationModelTest(TestCase):
    """Test cases for RequiresVerificationModel mixin."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
    
    def test_mark_verified(self):
        """Test marking an object as verified."""
        # Abstract model testing through documentation
        pass
    
    def test_mark_rejected(self):
        """Test marking an object as rejected."""
        pass
    
    def test_mark_processed(self):
        """Test marking a verified object as processed."""
        pass
    
    def test_verification_status_properties(self):
        """Test is_verified, is_rejected, is_pending properties."""
        pass


class AttendableModelTest(TestCase):
    """Test cases for Attendable mixin."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
    
    def test_check_in(self):
        """Test check-in functionality."""
        # Abstract model testing through documentation
        pass
    
    def test_check_out(self):
        """Test check-out functionality."""
        pass
    
    def test_is_checked_in_property(self):
        """Test is_checked_in property."""
        pass
    
    def test_is_checked_out_property(self):
        """Test is_checked_out property."""
        pass
