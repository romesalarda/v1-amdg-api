from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from apps.events.models import (
    Event, EventType, EventSettings, EventStatusChoices,
    EventAuthorization, EventAuthorizationStatusChoices,
    EventPermission, EventPermissionAssignment, EventPermissionCategoryChoices,
    EventRole, EventRoleAssignment, EventRoleCategoryChoices,
    EventStaff, EventStaffAvailability,
    EventReview,
    EventQuestion, EventQuestionTypeChoices, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice
)
from apps.common.models import AvailabilityWindow, Resource
from apps.common.api.serializers import (
    AvailabilityWindowSerializer, 
    ResourceSerializer
)

User = get_user_model()


class EventTypeSerializer(serializers.ModelSerializer):
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventType
        fields = ('id', 'title', 'code', 'description', 'created_at', 'created_by', 'updated_at', '_links')
        read_only_fields = ('id', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event type'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event type'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/types/{obj.id}/"
            )
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )
        
        return links


class EventSettingsSerializer(serializers.ModelSerializer):
    default_timezone = serializers.CharField()
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventSettings
        fields = (
            'id', 'event', 'payment_enabled', 'product_publication_requires_verification',
            'product_selling_enabled', 'donation_enabled', 'refunds_enabled',
            'accepting_sponsorships_enabled', 'participants_registration_require_verification',
            'default_timezone', '_links'
        )
        read_only_fields = ('id',)
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to these event settings'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/settings/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.event_id}/"
            )
        
        return links


class EventListSerializer(serializers.ModelSerializer):
    event_type_name = serializers.CharField(source='event_type.title', read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    timezone = serializers.CharField()
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = (
            'event_id', 'display_code', 'display_identifier', 'title', 'url_safe_title',
            'status', 'status_display', 'event_type', 'event_type_name', 'organisation', 
            'organisation_name', 'short_description', 'start_datetime', 'end_datetime',
            'timezone', 'created_at', 'created_by', '_links'
        )
        read_only_fields = ('event_id', 'url_safe_title', 'created_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event'},
            'event_type': {'type': 'string', 'format': 'uri', 'description': 'Link to the event type'},
            'organisation': {'type': 'string', 'format': 'uri', 'description': 'Link to the organisation'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event'},
            'settings': {'type': 'string', 'format': 'uri', 'description': 'Link to event settings'}
        },
        'required': ['self', 'settings']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/"
            )
        }
        
        if obj.event_type:
            links['event_type'] = request.build_absolute_uri(
                f"/api/event/types/{obj.event_type.id}/"
            )
        
        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/{obj.organisation.id}/"
            )
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )
        
        links['settings'] = request.build_absolute_uri(
            f"/api/event/list/{obj.event_id}/settings/"
        )
        
        return links


class EventDetailSerializer(serializers.ModelSerializer):
    event_type_details = EventTypeSerializer(source='event_type', read_only=True)
    settings = EventSettingsSerializer(read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    timezone = serializers.CharField()
    duration_days = serializers.IntegerField(read_only=True)
    is_ongoing = serializers.BooleanField(read_only=True)
    is_approved = serializers.BooleanField(read_only=True)
    can_participants_register = serializers.BooleanField(read_only=True)
    number_of_attendees = serializers.IntegerField(read_only=True)
    
    # New fields for availability, resources, and landing images
    availability_windows = AvailabilityWindowSerializer(many=True, read_only=True)
    resources = ResourceSerializer(many=True, read_only=True)
    landing_images = ResourceSerializer(many=True, read_only=True)
    main_landing_image = ResourceSerializer(read_only=True)
    is_deleted = serializers.SerializerMethodField()
    
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = (
            'event_id', 'display_code', 'display_identifier', 'title', 'url_safe_title',
            'status', 'status_display', 'event_type', 'event_type_details', 'timezone',
            'short_description', 'long_description', 'what_to_bring', 'important_information',
            'theme', 'anchor_verse', 'expected_attendance', 'maximum_attendance',
            'start_datetime', 'end_datetime', 'organisation', 'organisation_name',
            'created_by', 'created_by_email', 'created_at', 'updated_at',
            'settings', 'duration_days', 'is_ongoing', 'is_approved', 
            'can_participants_register', 'number_of_attendees',
            'availability_windows', 'resources', 'landing_images', 'main_landing_image',
            'deleted_at', 'deleted_by', 'is_deleted',
            '_links'
        )
        read_only_fields = (
            'event_id', 'display_identifier', 'url_safe_title', 'created_at', 
            'updated_at', 'duration_days', 'is_ongoing', 'is_approved', 
            'can_participants_register', 'number_of_attendees', 'deleted_at', 'deleted_by'
        )
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_deleted(self, obj):
        """Check if the event is soft-deleted."""
        return obj.deleted_at is not None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event'},
            'settings': {'type': 'string', 'format': 'uri', 'description': 'Link to event settings'},
            'staff': {'type': 'string', 'format': 'uri', 'description': 'Link to event staff list'},
            'availability_windows': {'type': 'string', 'format': 'uri', 'description': 'Link to manage availability windows'},
            'resources': {'type': 'string', 'format': 'uri', 'description': 'Link to manage resources'},
            'event_type': {'type': 'string', 'format': 'uri', 'description': 'Link to the event type'},
            'organisation': {'type': 'string', 'format': 'uri', 'description': 'Link to the organisation'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event'}
        },
        'required': ['self', 'settings', 'staff']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/"
            ),
            'settings': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/settings/"
            ),
            'staff': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/staff-list/"
            ),
            'availability_windows': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/availability-windows/"
            ),
            'resources': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/resources/"
            )
        }
        
        if obj.event_type:
            links['event_type'] = request.build_absolute_uri(
                f"/api/event/types/{obj.event_type.id}/"
            )
        
        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/{obj.organisation.id}/"
            )
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )
        
        return links


class EventCreateUpdateSerializer(serializers.ModelSerializer):
    timezone = serializers.CharField()
    _links = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Event
        fields = (
            'event_id', 'display_code', 'title', 'status', 'event_type', 'timezone',
            'short_description', 'long_description', 'what_to_bring', 'important_information',
            'theme', 'anchor_verse', 'expected_attendance', 'maximum_attendance',
            'start_datetime', 'end_datetime', 'organisation', 'created_by', '_links'
        )
        read_only_fields = ('event_id', 'created_by', '_links')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event'},
            'organisation': {'type': 'string', 'format': 'uri', 'description': 'Link to the organisation'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request or not obj.pk:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/"
            )
        }
        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/{obj.organisation.id}/"
            )

        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )

        return links
    
    def validate_title(self, value):
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError("Title must be at least 3 characters long")
        if len(value) > 255:
            raise serializers.ValidationError("Title must not exceed 255 characters")
        return value.strip()
    
    def validate_expected_attendance(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Expected attendance cannot be negative")
        return value
    
    def validate_maximum_attendance(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Maximum attendance cannot be negative")
        return value
    
    def validate(self, data):
        # Validate datetime ranges
        if 'start_datetime' in data and 'end_datetime' in data:
            if data['start_datetime'] >= data['end_datetime']:
                raise serializers.ValidationError({
                    "end_datetime": "End datetime must be after start datetime"
                })
        
        # Validate attendance limits
        expected = data.get('expected_attendance') or (self.instance.expected_attendance if self.instance else None)
        maximum = data.get('maximum_attendance') or (self.instance.maximum_attendance if self.instance else None)
        
        if expected and maximum and expected > maximum:
            raise serializers.ValidationError({
                "expected_attendance": "Expected attendance cannot exceed maximum attendance"
            })
        
        # Validate timezone
        timezone_str = data.get('timezone')
        if timezone_str:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(timezone_str)
            except Exception:
                raise serializers.ValidationError({
                    "timezone": f"Invalid timezone: {timezone_str}"
                })
        
        return data
    
    def create(self, validated_data):
        timezone_str = validated_data.pop('timezone', None)
        try:
            instance = Event.objects.create(**validated_data)
            if timezone_str:
                instance.timezone = timezone_str
                instance.save(update_fields=['timezone'])
            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error creating event: {str(e)}")
    
    def update(self, instance, validated_data):
        timezone_str = validated_data.pop('timezone', None)
        try:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            if timezone_str:
                instance.timezone = timezone_str
            instance.save()
            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error updating event: {str(e)}")


class EventAuthorizationSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    reviewed_by_email = serializers.EmailField(source='reviewed_by.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventAuthorization
        fields = (
            'id', 'review_id', 'review_code', 'event', 'event_title', 'reviewed_by',
            'reviewed_by_email', 'reviewed_at', 'status', 'status_display', 'reason', 'notes', '_links'
        )
        read_only_fields = ('id', 'review_id', 'review_code', 'reviewed_by', 'reviewed_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this authorization'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'reviewed_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who reviewed'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/authorizations/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.event_id}/"
            )
        
        if obj.reviewed_by:
            links['reviewed_by'] = request.build_absolute_uri(
                f"/api/users/{obj.reviewed_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        if self.instance is None:
            event = data.get('event')
            user = self.context['request'].user
            if EventAuthorization.objects.filter(event=event, reviewed_by=user).exists():
                raise serializers.ValidationError("You have already created an authorization for this event.")
        return data


class EventPermissionSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventPermission
        fields = (
            'id', 'permission_id', 'name', 'code', 'description', 'category',
            'category_display', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'permission_id', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this permission'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/event/permissions/{obj.id}/"
            )
        }


class EventPermissionAssignmentSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    permission_name = serializers.CharField(source='permission.name', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventPermissionAssignment
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'permission',
            'permission_name', 'assigned_at', 'assigned_by', 'assigned_by_email', '_links'
        )
        read_only_fields = ('id', 'assigned_at', 'assigned_by')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this permission assignment'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the user'},
            'permission': {'type': 'string', 'format': 'uri', 'description': 'Link to the permission'},
            'assigned_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who assigned'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/permission-assignments/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.event_id}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        if obj.permission:
            links['permission'] = request.build_absolute_uri(
                f"/api/event/permissions/{obj.permission.id}/"
            )
        
        if obj.assigned_by:
            links['assigned_by'] = request.build_absolute_uri(
                f"/api/users/{obj.assigned_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        if self.instance is None:
            if EventPermissionAssignment.objects.filter(
                event=data.get('event'),
                user=data.get('user'),
                permission=data.get('permission')
            ).exists():
                raise serializers.ValidationError("This permission is already assigned to this user for this event.")
        return data


class EventReviewSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.SerializerMethodField()
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventReview
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'user_full_name',
            'rating', 'comment', 'approved', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'user', 'approved', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this review'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the reviewing user'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/reviews/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.event_id}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        return links
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_user_full_name(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.full_name
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
    
    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def validate_comment(self, value):
        if value and len(value) < 10:
            raise serializers.ValidationError("Comment must be at least 10 characters long")
        if value and len(value) > 2000:
            raise serializers.ValidationError("Comment must not exceed 2000 characters")
        return value
    
    def validate_event(self, value):
        if not value:
            raise serializers.ValidationError("Event is required")
        
        # Check if event exists and is in appropriate status for reviews
        if value.status not in [EventStatusChoices.COMPLETED, EventStatusChoices.PUBLISHED, 
                                EventStatusChoices.OPEN, EventStatusChoices.IN_PROGRESS]:
            raise serializers.ValidationError("Reviews can only be submitted for active or completed events")
        
        return value
    
    def validate(self, data):
        # Prevent duplicate reviews
        if self.instance is None:
            event = data.get('event')
            user = self.context['request'].user
            
            if EventReview.objects.filter(event=event, user=user).exists():
                raise serializers.ValidationError("You have already submitted a review for this event")
        
        return data


class EventRoleSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventRole
        fields = (
            'id', 'name', 'description', 'code', 'category', 'category_display',
            'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this role'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/event/roles/{obj.id}/"
            )
        }


class EventRoleAssignmentSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventRoleAssignment
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'role', 'role_name',
            'assigned_at', 'assigned_by', 'assigned_by_email', '_links'
        )
        read_only_fields = ('id', 'assigned_at', 'assigned_by')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this role assignment'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the user'},
            'role': {'type': 'string', 'format': 'uri', 'description': 'Link to the role'},
            'assigned_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who assigned'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/role-assignments/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.event_id}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        if obj.role:
            links['role'] = request.build_absolute_uri(
                f"/api/event/roles/{obj.role.id}/"
            )
        
        if obj.assigned_by:
            links['assigned_by'] = request.build_absolute_uri(
                f"/api/users/{obj.assigned_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        if self.instance is None:
            if EventRoleAssignment.objects.filter(
                event=data.get('event'),
                user=data.get('user'),
                role=data.get('role')
            ).exists():
                raise serializers.ValidationError("This role is already assigned to this user for this event.")
        return data


class EventStaffAvailabilitySerializer(serializers.ModelSerializer):
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventStaffAvailability
        fields = (
            'id', 'staff', 'available_from', 'available_to', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this availability record'},
            'staff': {'type': 'string', 'format': 'uri', 'description': 'Link to the staff member'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/staff-availability/{obj.id}/"
            )
        }
        
        if obj.staff:
            links['staff'] = request.build_absolute_uri(
                f"/api/event/staff/{obj.staff.staff_id}/"
            )
        
        return links
    
    def validate(self, data):
        if 'available_from' in data and 'available_to' in data:
            if data['available_from'] >= data['available_to']:
                raise serializers.ValidationError("available_from must be before available_to")
        return data


class EventStaffSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    availabilities = EventStaffAvailabilitySerializer(many=True, read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventStaff
        fields = (
            'staff_id', 'event', 'event_title', 'user', 'user_email',
            'assigned_at', 'assigned_by', 'assigned_by_email', 'notes', 'availabilities', '_links'
        )
        read_only_fields = ('staff_id', 'assigned_at', 'assigned_by')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this staff member'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the user'},
            'assigned_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who assigned'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/staff/{obj.staff_id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.event_id}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        if obj.assigned_by:
            links['assigned_by'] = request.build_absolute_uri(
                f"/api/users/{obj.assigned_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        if self.instance is None:
            event = data.get('event')
            user = data.get('user')
            
            if not event:
                raise serializers.ValidationError({"event": "Event is required"})
            
            if not user:
                raise serializers.ValidationError({"user": "User is required"})
            
            if EventStaff.objects.filter(event=event, user=user).exists():
                raise serializers.ValidationError(
                    "This user is already assigned as staff for this event"
                )
        
        return data


class EventQuestionOptionSerializer(serializers.ModelSerializer):
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestionOption
        fields = ('id', 'question', 'option_text', 'order', 'created_at', 'updated_at', '_links')
        read_only_fields = ('id', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this question option'},
            'question': {'type': 'string', 'format': 'uri', 'description': 'Link to the question'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/question-options/{obj.id}/"
            )
        }
        
        if obj.question:
            links['question'] = request.build_absolute_uri(
                f"/api/event/questions/{obj.question.id}/"
            )
        
        return links
    
    def validate_option_text(self, value):
        if not value or len(value.strip()) < 1:
            raise serializers.ValidationError("Option text cannot be empty")
        if len(value) > 255:
            raise serializers.ValidationError("Option text must not exceed 255 characters")
        return value.strip()


class EventQuestionSerializer(serializers.ModelSerializer):
    question_type_display = serializers.CharField(source='get_question_type_display', read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True)
    options = EventQuestionOptionSerializer(many=True, read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestion
        fields = (
            'id', 'event', 'event_title', 'question_title', 'question_body',
            'question_type', 'question_type_display', 'required', 'public', 'order',
            'max_value', 'min_value', 'options', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this question'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/questions/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.event_id}/"
            )
        
        return links
    
    def validate_question_title(self, value):
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError("Question title must be at least 3 characters long")
        if len(value) > 255:
            raise serializers.ValidationError("Question title must not exceed 255 characters")
        return value.strip()
    
    def validate(self, data):
        question_type = data.get('question_type', self.instance.question_type if self.instance else None)
        min_value = data.get('min_value')
        max_value = data.get('max_value')
        
        # Validate slider questions
        if question_type == EventQuestionTypeChoices.SLIDER:
            if min_value is None or max_value is None:
                raise serializers.ValidationError({
                    "min_value": "Slider questions require both min_value and max_value"
                })
            if min_value >= max_value:
                raise serializers.ValidationError({
                    "max_value": "max_value must be greater than min_value"
                })
        
        # Ensure non-slider questions don't have min/max values
        if question_type in [EventQuestionTypeChoices.SHORT_ANSWER, EventQuestionTypeChoices.LONG_ANSWER,
                             EventQuestionTypeChoices.UPLOAD]:
            if min_value is not None or max_value is not None:
                raise serializers.ValidationError(
                    "This question type does not support min_value or max_value"
                )
        
        return data


class EventQuestionAnswerChoiceSerializer(serializers.ModelSerializer):
    option_text = serializers.CharField(source='option.option_text', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestionAnswerChoice
        fields = ('id', 'answer', 'option', 'option_text', 'selected_at', '_links')
        read_only_fields = ('id', 'selected_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this answer choice'},
            'answer': {'type': 'string', 'format': 'uri', 'description': 'Link to the answer'},
            'option': {'type': 'string', 'format': 'uri', 'description': 'Link to the option'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/answer-choices/{obj.id}/"
            )
        }
        
        if obj.answer:
            links['answer'] = request.build_absolute_uri(
                f"/api/event/question-answers/{obj.answer.id}/"
            )
        
        if obj.option:
            links['option'] = request.build_absolute_uri(
                f"/api/event/question-options/{obj.option.id}/"
            )
        
        return links


class EventQuestionAnswerSerializer(serializers.ModelSerializer):
    question_title = serializers.CharField(source='question.question_title', read_only=True)
    attendee_name = serializers.SerializerMethodField()
    selected_options = EventQuestionAnswerChoiceSerializer(many=True, read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestionAnswer
        fields = (
            'id', 'question', 'question_title', 'attendee', 'attendee_name',
            'answer_text', 'selected_options', 'submitted_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'submitted_at', 'updated_at')
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_attendee_name(self, obj):
        return obj.attendee.full_name
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this answer'},
            'question': {'type': 'string', 'format': 'uri', 'description': 'Link to the question'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/question-answers/{obj.id}/"
            )
        }
        
        if obj.question:
            links['question'] = request.build_absolute_uri(
                f"/api/event/questions/{obj.question.id}/"
            )
        
        return links
