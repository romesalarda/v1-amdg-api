"""
Serializer tests for the common app.

Tests cover:
1. AvailabilityWindowSerializer validation and serialization
2. ResourceSerializer for different resource types
3. AccessRuleSerializer validation
4. Mixin serializers (SoftDelete, Verification, Attendable)
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIRequestFactory

from apps.common.models import (
    AvailabilityWindow,
    Resource,
    AccessRule,
    AvailabilityTypeChoices,
    ResourceTypeChoices,
    BaseEventRuleChoices,
)
from apps.common.api.serializers import (
    AvailabilityWindowSerializer,
    ResourceSerializer,
    AccessRuleSerializer,
    SoftDeleteMixinSerializer,
    VerificationMixinSerializer,
    AttendableMixinSerializer,
)

User = get_user_model()


class AvailabilityWindowSerializerTest(TestCase):
    """Test cases for AvailabilityWindowSerializer."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.content_type = ContentType.objects.get_for_model(User)
        self.factory = APIRequestFactory()
        
        now = timezone.now()
        self.window = AvailabilityWindow.objects.create(
            name='Test Window',
            description='Test description',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=self.content_type,
            target_id=self.user.id,
            available_from=now,
            available_to=now + timedelta(days=7)
        )
    
    def test_serialize_availability_window(self):
        """Test serializing an availability window."""
        serializer = AvailabilityWindowSerializer(self.window)
        data = serializer.data
        
        self.assertEqual(data['name'], 'Test Window')
        self.assertEqual(data['description'], 'Test description')
        self.assertEqual(data['availability_type'], AvailabilityTypeChoices.REGISTRATION)
        self.assertIn('availability_id', data)
        self.assertIn('target_model', data)
        self.assertIn('is_active', data)
    
    def test_target_model_field(self):
        """Test that target_model returns the correct model name."""
        serializer = AvailabilityWindowSerializer(self.window)
        data = serializer.data
        
        self.assertEqual(data['target_model'], 'communityuser')
    
    def test_is_active_field_true(self):
        """Test is_active field when window is currently active."""
        serializer = AvailabilityWindowSerializer(self.window)
        data = serializer.data
        
        self.assertTrue(data['is_active'])
    
    def test_is_active_field_false(self):
        """Test is_active field when window is not active."""
        now = timezone.now()
        past_window = AvailabilityWindow.objects.create(
            name='Past Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=self.content_type,
            target_id=self.user.id,
            available_from=now - timedelta(days=14),
            available_to=now - timedelta(days=7)
        )
        
        serializer = AvailabilityWindowSerializer(past_window)
        data = serializer.data
        
        self.assertFalse(data['is_active'])
    
    def test_validation_available_to_after_from(self):
        """Test validation that available_to must be after available_from."""
        now = timezone.now()
        data = {
            'name': 'Invalid Window',
            'availability_type': AvailabilityTypeChoices.REGISTRATION,
            'target_type': self.content_type.id,
            'target_id': self.user.id,
            'available_from': now,
            'available_to': now - timedelta(days=1)
        }
        
        serializer = AvailabilityWindowSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('available_to', serializer.errors)
    
    def test_create_availability_window(self):
        """Test creating an availability window through serializer."""
        now = timezone.now()
        data = {
            'name': 'New Window',
            'description': 'New window description',
            'availability_type': AvailabilityTypeChoices.PRODUCT,
            'target_type': self.content_type.id,
            'target_id': self.user.id,
            'available_from': now.isoformat(),
            'available_to': (now + timedelta(days=30)).isoformat(),
            'timezone': 'UTC'
        }
        
        serializer = AvailabilityWindowSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        window = serializer.save()
        
        self.assertEqual(window.name, 'New Window')
        self.assertEqual(window.availability_type, AvailabilityTypeChoices.PRODUCT)


class ResourceSerializerTest(TestCase):
    """Test cases for ResourceSerializer."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.content_type = ContentType.objects.get_for_model(User)
        
        self.link_resource = Resource.objects.create(
            name='Test Link',
            description='Test link resource',
            resource_type=ResourceTypeChoices.LINK,
            link='https://example.com',
            target_type=self.content_type,
            target_id=str(self.user.id),
            public=True,
            added_by=self.user
        )
    
    def test_serialize_resource(self):
        """Test serializing a resource."""
        serializer = ResourceSerializer(self.link_resource)
        data = serializer.data
        
        self.assertEqual(data['name'], 'Test Link')
        self.assertEqual(data['resource_type'], ResourceTypeChoices.LINK)
        self.assertEqual(data['link'], 'https://example.com')
        self.assertTrue(data['public'])
        self.assertIn('resource_url', data)
        self.assertIn('target_model', data)
    
    def test_resource_url_field(self):
        """Test resource_url field returns correct URL."""
        serializer = ResourceSerializer(self.link_resource)
        data = serializer.data
        
        self.assertEqual(data['resource_url'], 'https://example.com')
    
    def test_added_by_email_field(self):
        """Test added_by_email shows the email of the user who added resource."""
        serializer = ResourceSerializer(self.link_resource)
        data = serializer.data
        
        self.assertEqual(data['added_by_email'], 'test@example.com')
    
    def test_validation_link_required_for_link_type(self):
        """Test that link is required for LINK resource type."""
        data = {
            'name': 'Link Resource',
            'resource_type': ResourceTypeChoices.LINK,
            'target_type': self.content_type.id,
            'target_id': str(self.user.id),
            'public': True
        }
        
        serializer = ResourceSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('link', serializer.errors)
    
    def test_validation_image_required_for_image_type(self):
        """Test that image is required for IMAGE resource type."""
        data = {
            'name': 'Image Resource',
            'resource_type': ResourceTypeChoices.IMAGE,
            'target_type': self.content_type.id,
            'target_id': str(self.user.id),
            'public': True
        }
        
        serializer = ResourceSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('image', serializer.errors)
    
    def test_create_link_resource(self):
        """Test creating a link resource through serializer."""
        data = {
            'name': 'New Link',
            'description': 'New link description',
            'resource_type': ResourceTypeChoices.LINK,
            'link': 'https://newlink.com',
            'target_type': self.content_type.id,
            'target_id': str(self.user.id),
            'public': True
        }
        
        serializer = ResourceSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        resource = serializer.save(added_by=self.user)
        
        self.assertEqual(resource.name, 'New Link')
        self.assertEqual(resource.link, 'https://newlink.com')


class AccessRuleSerializerTest(TestCase):
    """Test cases for AccessRuleSerializer."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.content_type = ContentType.objects.get_for_model(User)
        
        self.rule = AccessRule.objects.create(
            name='Age Limit',
            description='Must be over 18',
            rule_type=BaseEventRuleChoices.IS_AGE_GT,
            value='18',
            target_type=self.content_type,
            target_id=self.user.id,
            active=True,
            added_by=self.user
        )
    
    def test_serialize_access_rule(self):
        """Test serializing an access rule."""
        serializer = AccessRuleSerializer(self.rule)
        data = serializer.data
        
        self.assertEqual(data['name'], 'Age Limit')
        self.assertEqual(data['rule_type'], BaseEventRuleChoices.IS_AGE_GT)
        self.assertEqual(data['value'], '18')
        self.assertTrue(data['active'])
        self.assertIn('rule_id', data)
        self.assertIn('target_model', data)
        self.assertIn('requires_value', data)
    
    def test_requires_value_field_true(self):
        """Test requires_value field returns true for rules that need values."""
        serializer = AccessRuleSerializer(self.rule)
        data = serializer.data
        
        self.assertTrue(data['requires_value'])
    
    def test_requires_value_field_false(self):
        """Test requires_value field returns false for rules that don't need values."""
        staff_rule = AccessRule.objects.create(
            name='Staff Rule',
            rule_type=BaseEventRuleChoices.IS_EVENT_STAFF,
            target_type=self.content_type,
            target_id=self.user.id,
            added_by=self.user
        )
        
        serializer = AccessRuleSerializer(staff_rule)
        data = serializer.data
        
        self.assertFalse(data['requires_value'])
    
    def test_validation_value_required_for_age_rule(self):
        """Test that value is required for age-based rules."""
        data = {
            'name': 'Age Rule',
            'rule_type': BaseEventRuleChoices.IS_AGE_GT,
            'target_type': self.content_type.id,
            'target_id': self.user.id,
            'active': True
        }
        
        serializer = AccessRuleSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('value', serializer.errors)
    
    def test_validation_age_value_must_be_integer(self):
        """Test that age rules require integer values."""
        data = {
            'name': 'Age Rule',
            'rule_type': BaseEventRuleChoices.IS_AGE_GT,
            'value': 'not_a_number',
            'target_type': self.content_type.id,
            'target_id': self.user.id,
            'active': True
        }
        
        serializer = AccessRuleSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('value', serializer.errors)
    
    def test_create_access_rule(self):
        """Test creating an access rule through serializer."""
        data = {
            'name': 'New Rule',
            'description': 'New rule description',
            'rule_type': BaseEventRuleChoices.CODE_MATCHES,
            'value': 'PROMO2024',
            'target_type': self.content_type.id,
            'target_id': self.user.id,
            'active': True
        }
        
        serializer = AccessRuleSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        rule = serializer.save(added_by=self.user)
        
        self.assertEqual(rule.name, 'New Rule')
        self.assertEqual(rule.value, 'PROMO2024')


class MixinSerializerTest(TestCase):
    """Test cases for mixin serializers."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
    
    def test_soft_delete_mixin_serializer_fields(self):
        """Test SoftDeleteMixinSerializer provides expected fields."""
        serializer = SoftDeleteMixinSerializer()
        fields = serializer.get_fields()
        
        self.assertIn('deleted_at', fields)
        self.assertIn('deleted_by', fields)
        self.assertIn('is_deleted', fields)
    
    def test_verification_mixin_serializer_fields(self):
        """Test VerificationMixinSerializer provides expected fields."""
        serializer = VerificationMixinSerializer()
        fields = serializer.get_fields()
        
        self.assertIn('verification_status', fields)
        self.assertIn('verified_updated_at', fields)
        self.assertIn('verified_by', fields)
        self.assertIn('is_verified', fields)
        self.assertIn('is_pending', fields)
        self.assertIn('is_rejected', fields)
        self.assertIn('is_processed', fields)
    
    def test_attendable_mixin_serializer_fields(self):
        """Test AttendableMixinSerializer provides expected fields."""
        serializer = AttendableMixinSerializer()
        fields = serializer.get_fields()
        
        self.assertIn('check_in_time', fields)
        self.assertIn('check_out_time', fields)
        self.assertIn('check_in_by', fields)
        self.assertIn('check_out_by', fields)
        self.assertIn('is_checked_in', fields)
        self.assertIn('is_checked_out', fields)
