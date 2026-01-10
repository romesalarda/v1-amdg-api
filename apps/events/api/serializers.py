from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
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

User = get_user_model()


class EventTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventType
        fields = ('id', 'title', 'code', 'description', 'created_at', 'created_by', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class EventSettingsSerializer(serializers.ModelSerializer):
    default_timezone = serializers.CharField()
    
    class Meta:
        model = EventSettings
        fields = (
            'id', 'event', 'payment_enabled', 'product_publication_requires_verification',
            'product_selling_enabled', 'donation_enabled', 'refunds_enabled',
            'accepting_sponsorships_enabled', 'participants_registration_require_verification',
            'default_timezone'
        )
        read_only_fields = ('id',)


class EventListSerializer(serializers.ModelSerializer):
    event_type_name = serializers.CharField(source='event_type.title', read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    timezone = serializers.CharField()
    
    class Meta:
        model = Event
        fields = (
            'id', 'event_id', 'display_code', 'display_identifier', 'title', 'url_safe_title',
            'status', 'status_display', 'event_type', 'event_type_name', 'organisation', 
            'organisation_name', 'short_description', 'start_datetime', 'end_datetime',
            'timezone', 'created_at', 'created_by'
        )
        read_only_fields = ('id', 'event_id', 'url_safe_title', 'created_at')


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
    
    class Meta:
        model = Event
        fields = (
            'id', 'event_id', 'display_code', 'display_identifier', 'title', 'url_safe_title',
            'status', 'status_display', 'event_type', 'event_type_details', 'timezone',
            'short_description', 'long_description', 'what_to_bring', 'important_information',
            'theme', 'anchor_verse', 'expected_attendance', 'maximum_attendance',
            'start_datetime', 'end_datetime', 'organisation', 'organisation_name',
            'created_by', 'created_by_email', 'created_at', 'updated_at',
            'settings', 'duration_days', 'is_ongoing', 'is_approved', 
            'can_participants_register', 'number_of_attendees'
        )
        read_only_fields = (
            'id', 'event_id', 'display_identifier', 'url_safe_title', 'created_at', 
            'updated_at', 'duration_days', 'is_ongoing', 'is_approved', 
            'can_participants_register', 'number_of_attendees'
        )


class EventCreateUpdateSerializer(serializers.ModelSerializer):
    timezone = serializers.CharField()
    
    class Meta:
        model = Event
        fields = (
            'id', 'display_code', 'title', 'status', 'event_type', 'timezone',
            'short_description', 'long_description', 'what_to_bring', 'important_information',
            'theme', 'anchor_verse', 'expected_attendance', 'maximum_attendance',
            'start_datetime', 'end_datetime', 'organisation', 'created_by'
        )
        read_only_fields = ('id',)
    
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
    reviewed_by = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = EventAuthorization
        fields = (
            'id', 'review_id', 'review_code', 'event', 'event_title', 'reviewed_by',
            'reviewed_by_email', 'reviewed_at', 'status', 'status_display', 'reason', 'notes'
        )
        read_only_fields = ('id', 'review_id', 'review_code', 'reviewed_by', 'reviewed_at')
    
    def validate(self, data):
        if self.instance is None:
            event = data.get('event')
            user = self.context['request'].user
            if EventAuthorization.objects.filter(event=event, reviewed_by=user).exists():
                raise serializers.ValidationError("You have already created an authorization for this event.")
        return data


class EventPermissionSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    
    class Meta:
        model = EventPermission
        fields = (
            'id', 'permission_id', 'name', 'code', 'description', 'category',
            'category_display', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'permission_id', 'created_at', 'updated_at')


class EventPermissionAssignmentSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    permission_name = serializers.CharField(source='permission.name', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    
    class Meta:
        model = EventPermissionAssignment
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'permission',
            'permission_name', 'assigned_at', 'assigned_by', 'assigned_by_email'
        )
        read_only_fields = ('id', 'assigned_at', 'assigned_by')
    
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
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = EventReview
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'user_full_name',
            'rating', 'comment', 'approved', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'user', 'approved', 'created_at', 'updated_at')
    
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
    
    class Meta:
        model = EventRole
        fields = (
            'id', 'name', 'description', 'code', 'category', 'category_display',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class EventRoleAssignmentSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    
    class Meta:
        model = EventRoleAssignment
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'role', 'role_name',
            'assigned_at', 'assigned_by', 'assigned_by_email'
        )
        read_only_fields = ('id', 'assigned_at', 'assigned_by')
    
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
    class Meta:
        model = EventStaffAvailability
        fields = (
            'id', 'staff', 'available_from', 'available_to', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
    
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
    
    class Meta:
        model = EventStaff
        fields = (
            'staff_id', 'event', 'event_title', 'user', 'user_email',
            'assigned_at', 'assigned_by', 'assigned_by_email', 'notes', 'availabilities'
        )
        read_only_fields = ('staff_id', 'assigned_at', 'assigned_by')
    
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
    class Meta:
        model = EventQuestionOption
        fields = ('id', 'question', 'option_text', 'order', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')
    
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
    
    class Meta:
        model = EventQuestion
        fields = (
            'id', 'event', 'event_title', 'question_title', 'question_body',
            'question_type', 'question_type_display', 'required', 'public', 'order',
            'max_value', 'min_value', 'options', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
    
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
    
    class Meta:
        model = EventQuestionAnswerChoice
        fields = ('id', 'answer', 'option', 'option_text', 'selected_at')
        read_only_fields = ('id', 'selected_at')


class EventQuestionAnswerSerializer(serializers.ModelSerializer):
    question_title = serializers.CharField(source='question.question_title', read_only=True)
    attendee_name = serializers.SerializerMethodField()
    selected_options = EventQuestionAnswerChoiceSerializer(many=True, read_only=True)
    
    class Meta:
        model = EventQuestionAnswer
        fields = (
            'id', 'question', 'question_title', 'attendee', 'attendee_name',
            'answer_text', 'selected_options', 'submitted_at', 'updated_at'
        )
        read_only_fields = ('id', 'submitted_at', 'updated_at')
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_attendee_name(self, obj):
        return obj.attendee.full_name
