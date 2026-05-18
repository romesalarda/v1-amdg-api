"""
Serializers for the common app models.

These serializers are designed to be used by other apps when serializing
related common models. They provide comprehensive field coverage with proper
validation and schema documentation.
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from django.contrib.contenttypes.models import ContentType

from apps.common.models import (
    AvailabilityWindow,
    AvailabilityWindowTemplate,
    Resource, 
    AccessRule,
    AvailabilityTypeChoices,
    ResourceTypeChoices,
    BaseEventRuleChoices,
    VerificationStatus
)


class AvailabilityWindowSerializer(serializers.ModelSerializer):
    """Serializer for AvailabilityWindow model.
    
    Note: target_type and target_id are internal fields used for generic relations.
    They are not exposed via API for security and should only be set internally.
    """
    
    timezone = serializers.CharField()
    is_active = serializers.SerializerMethodField()
    # Target fields for internal use only - not exposed in API responses
    target_type = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )
    target_id = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = AvailabilityWindow
        fields = (
            'availability_id', 'name', 'description', 'availability_type',
            'available_from', 'available_to', 'timezone', 'is_active',
            'target_type', 'target_id', 'created_at', 'updated_at'
        )
        read_only_fields = ('availability_id', 'created_at', 'updated_at')
        extra_kwargs = {
            'name': {'help_text': 'Name of the availability window'},
            'description': {'help_text': 'Optional description of the window'},
            'availability_type': {'help_text': 'Type of availability window'},
            'available_from': {'help_text': 'Start datetime of availability', 'default': None},
            'available_to': {'help_text': 'End datetime of availability', 'default': None},
            'timezone': {'help_text': 'Timezone for the availability window', 'source': '*'},  # Prevent TimeZoneField auto-generation
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_active(self, obj):
        """Check if the window is currently active."""
        from django.utils import timezone
        now = timezone.now()
        return obj.available_from <= now <= obj.available_to
    
    def validate(self, attrs):
        """Ensure available_from is before available_to."""
        if attrs.get('available_from') and attrs.get('available_to'):
            if attrs['available_from'] >= attrs['available_to']:
                raise serializers.ValidationError({
                    'available_to': 'Must be after available_from'
                })
        return attrs


class AvailabilityWindowTemplateSerializer(serializers.ModelSerializer):
    """Serializer for AvailabilityWindowTemplate model."""
    
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    organisation_name = serializers.CharField(source='organisation.name', read_only=True)
    windows_count = serializers.SerializerMethodField()
    
    class Meta:
        model = AvailabilityWindowTemplate
        fields = (
            'template_id', 'name', 'description', 'is_predefined',
            'organisation', 'organisation_name', 'windows_config',
            'created_by', 'created_by_email', 'windows_count',
            'created_at', 'updated_at'
        )
        read_only_fields = ('template_id', 'created_at', 'updated_at', 'created_by')
        extra_kwargs = {
            'name': {'help_text': 'Name of the template'},
            'description': {'help_text': 'Optional description of what this template provides'},
            'is_predefined': {'help_text': 'Whether this is a system-defined template', 'default': False},
            'windows_config': {'help_text': 'JSON configuration for availability windows in this template'},
            'organisation': {'help_text': 'Organization that owns this custom template (null for predefined)', 'required': False, 'allow_null': True},
        }
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_windows_count(self, obj):
        """Get the number of windows in this template."""
        return len(obj.windows_config) if obj.windows_config else 0
    
    def validate_windows_config(self, value):
        """Validate the windows_config JSON structure."""
        if not isinstance(value, list):
            raise serializers.ValidationError('windows_config must be a list')
        
        for idx, window in enumerate(value):
            if not isinstance(window, dict):
                raise serializers.ValidationError(f'Window {idx} must be an object')
            
            # Required fields
            if 'name' not in window:
                raise serializers.ValidationError(f'Window {idx} missing required field: name')
            if 'availability_type' not in window:
                raise serializers.ValidationError(f'Window {idx} missing required field: availability_type')
            if 'offset_from_event_start' not in window:
                raise serializers.ValidationError(f'Window {idx} missing required field: offset_from_event_start')
            if 'offset_to_event_start' not in window:
                raise serializers.ValidationError(f'Window {idx} missing required field: offset_to_event_start')
            
            # Validate availability_type is valid
            from apps.common.models import AvailabilityTypeChoices
            if window['availability_type'] not in [choice[0] for choice in AvailabilityTypeChoices.choices]:
                raise serializers.ValidationError(f'Window {idx} has invalid availability_type')
            
            # Validate offsets are numbers
            if not isinstance(window['offset_from_event_start'], (int, float)):
                raise serializers.ValidationError(f'Window {idx} offset_from_event_start must be a number')
            if not isinstance(window['offset_to_event_start'], (int, float)):
                raise serializers.ValidationError(f'Window {idx} offset_to_event_start must be a number')
            
            # Validate offset logic (from should be before to)
            if window['offset_from_event_start'] >= window['offset_to_event_start']:
                raise serializers.ValidationError(f'Window {idx} offset_from must be before offset_to')
        
        return value


class ResourceSerializer(serializers.ModelSerializer):
    """Serializer for Resource model.
    
    Note: target_type and target_id are internal fields used for generic relations.
    They are not exposed via API for security and should only be set internally.
    """
    
    resource_url = serializers.SerializerMethodField()
    added_by_email = serializers.EmailField(source='added_by.email', read_only=True)
    image_urls = serializers.SerializerMethodField()
    # Target fields for internal use only - not exposed in API responses
    target_type = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )
    target_id = serializers.CharField(
        write_only=True,
        required=False,
        allow_null=True,
        allow_blank=True
    )
    
    class Meta:
        model = Resource
        fields = (
            'id', 'name', 'description', 'tag', 'resource_type',
            'public', 'protected', 'file', 'link',
            'image', 'resource_url', 'added_by', 'added_by_email',
            'target_type', 'target_id', 'created_at', 'updated_at',
            'image_urls', 'image_width', 'image_height',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'added_by', 'image_width', 'image_height')
        extra_kwargs = {
            'name': {'help_text': 'Name of the resource'},
            'description': {'help_text': 'Optional description'},
            'tag': {'help_text': 'Tag for categorization (e.g., LANDING_PHOTO)'},
            'resource_type': {'help_text': 'Type of resource'},
            'public': {'help_text': 'Whether resource is publicly accessible'},
            'protected': {'help_text': 'If true, resource cannot be auto-deleted'},
            'file': {'help_text': 'File upload for DOCUMENT/OTHER types'},
            'link': {'help_text': 'URL for LINK type resources'},
            'image': {'help_text': 'Image file for IMAGE type resources'},
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.URI)
    def get_resource_url(self, obj):
        """Returns the URL/path to access the resource."""
        return obj.resource_url

    @extend_schema_field({
        'type': 'object',
        'nullable': True,
        'properties': {
            'thumbnail': {'type': 'string', 'format': 'uri', 'nullable': True},
            'medium': {'type': 'string', 'format': 'uri', 'nullable': True},
            'large': {'type': 'string', 'format': 'uri', 'nullable': True},
            'original': {'type': 'string', 'format': 'uri', 'nullable': True},
        },
    })
    def get_image_urls(self, obj):
        """Return a dict of image variant URLs, or None for non-image resources.

        All entries are optional/nullable so callers must handle missing variants
        gracefully. Existing consumers of ``image`` and ``resource_url`` are
        unaffected — this field is purely additive.
        """
        if not obj.image:
            return None

        request = self.context.get('request')

        def _build_url(url):
            if request is not None:
                return request.build_absolute_uri(url)
            return url

        def _variant_url(spec_field):
            try:
                url = spec_field.url
                return _build_url(url) if url else None
            except Exception:
                return None

        return {
            'thumbnail': _variant_url(obj.image_thumbnail),
            'medium': _variant_url(obj.image_medium),
            'large': _variant_url(obj.image_large),
            'original': _build_url(obj.image.url),
        }

    def validate(self, attrs):
        """Validate resource based on resource_type."""
        resource_type = attrs.get('resource_type')
        
        if resource_type in [ResourceTypeChoices.DOCUMENT, ResourceTypeChoices.OTHER]:
            if not attrs.get('file'):
                raise serializers.ValidationError({
                    'file': 'File is required for DOCUMENT/OTHER resource types'
                })
        elif resource_type == ResourceTypeChoices.LINK:
            if not attrs.get('link'):
                raise serializers.ValidationError({
                    'link': 'Link is required for LINK resource type'
                })
        elif resource_type == ResourceTypeChoices.IMAGE:
            if not attrs.get('image'):
                raise serializers.ValidationError({
                    'image': 'Image is required for IMAGE resource type'
                })
        
        return attrs


class AccessRuleSerializer(serializers.ModelSerializer):
    """Serializer for AccessRule model.
    
    Note: target_type and target_id are internal fields used for generic relations.
    They are not exposed via API for security and should only be set internally.
    """
    
    added_by_email = serializers.EmailField(source='added_by.email', read_only=True)
    requires_value = serializers.SerializerMethodField()
    # Target fields for internal use only - not exposed in API responses
    target_type = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )
    target_id = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = AccessRule
        fields = (
            'rule_id', 'name', 'description', 'rule_type', 'value', 'active',
            'added_by', 'added_by_email', 'requires_value', 'target_type', 'target_id',
            'created_at', 'updated_at'
        )
        read_only_fields = ('rule_id', 'created_at', 'updated_at', 'added_by')
        extra_kwargs = {
            'name': {'help_text': 'Name of the access rule'},
            'description': {'help_text': 'Optional description of the rule'},
            'rule_type': {'help_text': 'Type of access rule to apply'},
            'value': {'help_text': 'Value for the rule (e.g., age limit, code)'},
            'active': {'help_text': 'Whether the rule is currently active'},
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
        
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_requires_value(self, obj):
        """Check if this rule type requires a value."""
        return obj.rule_type in [
            BaseEventRuleChoices.IS_AGE_LT,
            BaseEventRuleChoices.IS_AGE_GT,
            BaseEventRuleChoices.ORGANISATION_MATCHES,
            BaseEventRuleChoices.VALUE_MATCHES,
            BaseEventRuleChoices.EVENT_STAFF_ROLE_MATCHES,
            BaseEventRuleChoices.NAME_MATCHES,
            BaseEventRuleChoices.LOCATION_MATCHES,
            BaseEventRuleChoices.CODE_MATCHES,
        ]
    
    def validate(self, attrs):
        """Validate that required fields are present based on rule_type."""
        rule_type = attrs.get('rule_type')
        value = attrs.get('value')
        
        requires_value_types = [
            BaseEventRuleChoices.IS_AGE_LT,
            BaseEventRuleChoices.IS_AGE_GT,
            BaseEventRuleChoices.ORGANISATION_MATCHES,
            BaseEventRuleChoices.VALUE_MATCHES,
            BaseEventRuleChoices.EVENT_STAFF_ROLE_MATCHES,
            BaseEventRuleChoices.NAME_MATCHES,
            BaseEventRuleChoices.LOCATION_MATCHES,
            BaseEventRuleChoices.CODE_MATCHES,
        ]
        
        if rule_type in requires_value_types and not value:
            raise serializers.ValidationError({
                'value': f'Rule type {rule_type} requires a value'
            })
        
        # Validate age rules have integer values
        if rule_type in [BaseEventRuleChoices.IS_AGE_GT, BaseEventRuleChoices.IS_AGE_LT]:
            try:
                int(value)
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    'value': 'Age rule types require an integer value'
                })
        
        return attrs


# Mixin serializers for abstract models

class SoftDeleteMixinSerializer(serializers.Serializer):
    """Mixin for models that use SoftDeleteModel."""
    
    deleted_at = serializers.DateTimeField(read_only=True)
    deleted_by = serializers.PrimaryKeyRelatedField(read_only=True)
    is_deleted = serializers.SerializerMethodField()
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_deleted(self, obj):
        """Check if the object is soft deleted."""
        return obj.deleted_at is not None


class VerificationMixinSerializer(serializers.Serializer):
    """Mixin for models that use RequiresVerificationModel."""
    
    verification_status = serializers.ChoiceField(
        choices=VerificationStatus.choices,
        read_only=True
    )
    verified_updated_at = serializers.DateTimeField(read_only=True)
    verified_by = serializers.PrimaryKeyRelatedField(read_only=True)
    verified_by_email = serializers.EmailField(
        source='verified_by.email', 
        read_only=True
    )
    processed_at = serializers.DateTimeField(read_only=True)
    processed_by = serializers.PrimaryKeyRelatedField(read_only=True)
    auto_processed = serializers.BooleanField(read_only=True)
    is_verified = serializers.SerializerMethodField()
    is_pending = serializers.SerializerMethodField()
    is_rejected = serializers.SerializerMethodField()
    is_processed = serializers.SerializerMethodField()
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_verified(self, obj):
        """Check if object is verified."""
        return obj.is_verified
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_pending(self, obj):
        """Check if object is pending verification."""
        return obj.is_pending
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_rejected(self, obj):
        """Check if object is rejected."""
        return obj.is_rejected
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_processed(self, obj):
        """Check if object is processed."""
        return obj.is_processed


class AttendableMixinSerializer(serializers.Serializer):
    """Mixin for models that use Attendable."""
    
    check_in_time = serializers.DateTimeField(read_only=True)
    check_out_time = serializers.DateTimeField(read_only=True)
    check_in_by = serializers.PrimaryKeyRelatedField(read_only=True)
    check_out_by = serializers.PrimaryKeyRelatedField(read_only=True)
    is_checked_in = serializers.SerializerMethodField()
    is_checked_out = serializers.SerializerMethodField()
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_checked_in(self, obj):
        """Check if currently checked in."""
        return obj.is_checked_in
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_checked_out(self, obj):
        """Check if checked out."""
        return obj.is_checked_out
