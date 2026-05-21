"""
Base serializers for the attendee app.

Provides serializers for core attendee models including Attendee, AttendeeGuardian,
AttendeeAction, FamilyGroup, FamilyAttendee, and AttendeeMessage with HATEOAS support.
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from typing import Dict, Any

from apps.attendee.models import (
    Attendee, AttendeeGuardian, AttendeeAction, AttendeeActionChoices,
    AttendeeRelationship, FamilyGroup, FamilyAttendee,
    AttendeeMessage, AttendeeMessagePriority
)

User = get_user_model()


# ============================================================================
# ATTENDEE SERIALIZERS
# ============================================================================

class AttendeeListSerializer(serializers.ModelSerializer):
    """List serializer for Attendee with minimal fields and HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(read_only=True)
    is_minor = serializers.BooleanField(read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True, allow_null=True)
    relationship_display = serializers.CharField(source='get_relationship_to_user_display', read_only=True)
    area_from_name = serializers.CharField(source='area_from.area_name', read_only=True, allow_null=True)
    is_cancelled = serializers.BooleanField(read_only=True)
    is_registered = serializers.BooleanField(read_only=True)
    is_checked_in = serializers.BooleanField(read_only=True)
    is_refunded = serializers.BooleanField(read_only=True)
    class Meta:
        model = Attendee
        fields = (
            'attendee_id', 'attendee_display_id', 'first_name', 'last_name', 'full_name',
            'email', 'phone_number', 'date_of_birth', 'age', 'is_minor', 'gender',
            'relationship_to_user', 'relationship_display', 'event', 'event_title', 'status',
            'is_cancelled', 'is_registered', 'is_checked_in', 'is_refunded',
            'created_at', '_links', 'area_from_name'
        )
        read_only_fields = ('attendee_id', 'attendee_display_id', 'full_name', 'age', 'is_minor', 'created_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'user': {'type': 'string', 'format': 'uri'},
            'emergency_contacts': {'type': 'string', 'format': 'uri'},
            'dietary_requirements': {'type': 'string', 'format': 'uri'},
            'medical_conditions': {'type': 'string', 'format': 'uri'},
            'accessibility_requirements': {'type': 'string', 'format': 'uri'},
            'consents': {'type': 'string', 'format': 'uri'},
            'messages': {'type': 'string', 'format': 'uri'},
        },
        'required': ['self']
    })
    def get__links(self, obj) -> Dict[str, str]:
        """Generate HATEOAS links for the attendee."""
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/attendee/attendees/{obj.attendee_id}/")
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/")
        
        if obj.user:
            links['user'] = request.build_absolute_uri(f"/api/users/{obj.user.id}/")
            links['profile'] = request.build_absolute_uri(f"/api/users/{obj.user.profile.id}/profile/")
        
        # Nested resource endpoints
        links['emergency_contacts'] = request.build_absolute_uri(
            f"/api/attendee/attendees/{obj.attendee_id}/emergency-contacts/"
        )
        links['dietary_requirements'] = request.build_absolute_uri(
            f"/api/attendee/attendees/{obj.attendee_id}/dietary-requirements/"
        )
        links['medical_conditions'] = request.build_absolute_uri(
            f"/api/attendee/attendees/{obj.attendee_id}/medical-conditions/"
        )
        links['accessibility_requirements'] = request.build_absolute_uri(
            f"/api/attendee/attendees/{obj.attendee_id}/accessibility-requirements/"
        )
        links['consents'] = request.build_absolute_uri(
            f"/api/attendee/attendees/{obj.attendee_id}/consents/"
        )
        links['messages'] = request.build_absolute_uri(
            f"/api/attendee/attendees/{obj.attendee_id}/messages/"
        )
        
        return links

class AttendeeDetailSerializer(AttendeeListSerializer):
    """Detailed serializer for Attendee with extended fields."""
    
    is_event_staff = serializers.BooleanField(read_only=True)
    staff_role_names = serializers.ListField(read_only=True)
    self_registered = serializers.BooleanField(read_only=True)
   
    area_from_name = serializers.CharField(source='area_from.area_name', read_only=True, allow_null=True)
    alternative_signins = serializers.SerializerMethodField()
    class Meta(AttendeeListSerializer.Meta):
        fields = AttendeeListSerializer.Meta.fields + (
            'area_from', 'area_from_name', 'booking',
            'is_event_staff', 'staff_role_names', 'self_registered',
            # 'is_cancelled', 'is_registered', 'is_checked_in',
            'defined_by', 'updated_at', 'deleted_at', 'deleted_by', 'alternative_signins'
        )
        read_only_fields = AttendeeListSerializer.Meta.read_only_fields + (
            'is_event_staff', 'staff_role_names', 'self_registered',
            # 'is_cancelled', 'is_registered', 'is_checked_in', 
            'updated_at', 'deleted_at', 'alternative_signins'
        )

    @extend_schema_field({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'sign_id': {'type': 'string', 'format': 'uuid'},
                'identifier': {'type': 'string'},
                'uses': {'type': 'integer'},
                'ticket': {'type': 'string', 'format': 'uuid', 'nullable': True},
            }
        }
    })
    def get_alternative_signins(self, obj):
        """Get alternative sign-in identifiers for the attendee."""
    
        alternative_signins = obj.alternative_signins.all()

        return [
            {
                "sign_id": str(alt.sign_id),
                "identifier": alt.identifier,
                "uses": alt.uses,
                "ticket": str(alt.ticket.ticket_id) if alt.ticket else None,
            } for alt in alternative_signins
        ] 
    


class AttendeeCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new attendees with validation."""
    
    class Meta:
        model = Attendee
        fields = (
            'attendee_id', 'first_name', 'last_name', 'email', 'phone_number', 'date_of_birth',
            'gender', 'relationship_to_user', 'event', 'user', 'area_from', 'booking'
        )
        # Make user optional since it will be auto-assigned for non-admin users creating SELF attendees
        extra_kwargs = {
            'user': {'required': False}
        }
    
    def validate(self, attrs):
        """Validate attendee data."""
        request = self.context.get('request')
        relationship = attrs.get('relationship_to_user')
        user = attrs.get('user')
        
        # For SELF relationship, user must be provided or will be auto-assigned
        if relationship == AttendeeRelationship.SELF:
            # If user not provided and we have an authenticated user (non-admin flow)
            if not user and request and hasattr(request, 'user'):
                # Will be set in perform_create, so this is valid
                pass
            elif not user:
                # No user in request context and none provided - invalid
                raise serializers.ValidationError({
                    'user': "Attendees with 'self' relationship must be linked to a user account."
                })
        
        # Validate date of birth
        if attrs.get('date_of_birth'):
            from datetime import date
            if attrs['date_of_birth'] > date.today():
                raise serializers.ValidationError({
                    'date_of_birth': "Date of birth cannot be in the future."
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create attendee and set defined_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['defined_by'] = request.user
        
        return super().create(validated_data)


class AttendeeUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating attendees."""
    
    class Meta:
        model = Attendee
        fields = (
            'first_name', 'last_name', 'email', 'phone_number', 'date_of_birth',
            'gender', 'relationship_to_user', 'area_from'
        )
    
    def validate(self, attrs):
        """Validate update data."""
        instance = self.instance
        relationship = attrs.get('relationship_to_user', instance.relationship_to_user)
        
        # Check if relationship is SELF and user exists
        if relationship == AttendeeRelationship.SELF and not instance.user:
            raise serializers.ValidationError({
                'relationship_to_user': "Cannot set relationship to 'self' without a linked user account."
            })
        
        return attrs


# ============================================================================
# ATTENDEE GUARDIAN SERIALIZERS
# ============================================================================

class AttendeeGuardianSerializer(serializers.ModelSerializer):
    """Serializer for AttendeeGuardian with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    user_email = serializers.EmailField(source='user.email', read_only=True, allow_null=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True, allow_null=True)
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    relationship_display = serializers.CharField(source='get_relationship_display', read_only=True)
    attendee = serializers.SlugRelatedField(slug_field='attendee_id', queryset=Attendee.objects.all(), write_only=True)
    
    class Meta:
        model = AttendeeGuardian
        fields = (
            'id', 'user', 'user_email', 'user_name', 'attendee', 'attendee_name',
            'relationship', 'relationship_display', 'added_at', '_links'
        )
        read_only_fields = ('id', 'added_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'user': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/attendee/guardians/{obj.id}/")
        }
        
        if obj.user:
            links['user'] = request.build_absolute_uri(f"/api/users/{obj.user.id}/")
        
        if obj.attendee:
            links['attendee'] = request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            )
        
        return links


# ============================================================================
# ATTENDEE ACTION SERIALIZERS
# ============================================================================

class AttendeeActionSerializer(serializers.ModelSerializer):
    """Serializer for AttendeeAction with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    performed_by_name = serializers.CharField(
        source='performed_by.full_name', read_only=True, allow_null=True
    )
    
    class Meta:
        model = AttendeeAction
        fields = (
            'id', 'action', 'action_display', 'attendee', 'attendee_name',
            'performed_by', 'performed_by_name', 'performed_at', 'notes', '_links'
        )
        read_only_fields = ('id', 'performed_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'performed_by': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/attendee/actions/{obj.id}/"),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            )
        }
        
        if obj.performed_by:
            links['performed_by'] = request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.performed_by}/"
            )
        
        return links


# ============================================================================
# FAMILY GROUP SERIALIZERS
# ============================================================================

def get_family_group_qs():
    from apps.events.models import Event
    return Event.objects.all()

class FamilyGroupListSerializer(serializers.ModelSerializer):
    """List serializer for FamilyGroup."""
    
    _links = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, allow_null=True
    )
    member_count = serializers.SerializerMethodField()
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=get_family_group_qs())

    class Meta:
        model = FamilyGroup
        fields = (
            'id', 'family_name', 'organisation', 'event', 'created_by', 'created_by_name',
            'member_count', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_member_count(self, obj) -> int:
        """Get the number of family members."""
        return obj.family_attendees.count()
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'created_by': {'type': 'string', 'format': 'uri'},
            'members': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/family-groups/{obj.id}/"),
            'members': request.build_absolute_uri(f"/api/family-groups/{obj.id}/members/")
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(f"/api/users/{obj.created_by.id}/")
        
        return links



class FamilyGroupDetailSerializer(FamilyGroupListSerializer):
    """Detailed serializer for FamilyGroup with member details."""
    
    from apps.attendee.api.serializers.personal import FamilyAttendeeSerializer
    members = serializers.SerializerMethodField()

    class Meta(FamilyGroupListSerializer.Meta):
        fields = FamilyGroupListSerializer.Meta.fields + ('members',)
    
    @extend_schema_field({
        'type': 'array',
        'items': {'type': 'object'}
    })
    def get_members(self, obj):
        """Get family members with minimal info to avoid circular imports."""
        from apps.attendee.api.serializers.personal import FamilyAttendeeSerializer
        members = obj.family_attendees.all()
        return FamilyAttendeeSerializer(members, many=True, context=self.context).data

class FamilyGroupCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating FamilyGroup."""
    
    class Meta:
        model = FamilyGroup
        fields = ('family_name', 'organisation', 'event')

    def validate(self, attrs):
        event = attrs.get('event', self.instance.event if self.instance else None)
        organisation = attrs.get('organisation', self.instance.organisation if self.instance else None)

        if event and not organisation:
            organisation = event.organisation
            attrs['organisation'] = organisation

        if not event:
            raise serializers.ValidationError({'event': 'Family group event is required.'})

        if not organisation:
            raise serializers.ValidationError({'organisation': 'Family group organisation is required.'})

        if event.organisation_id != organisation.id:
            raise serializers.ValidationError({
                'organisation': 'Organisation must match the event organisation.'
            })

        if self.instance and 'event' in attrs and attrs['event'].id != self.instance.event_id:
            raise serializers.ValidationError({'event': 'Event cannot be changed once the family group is created.'})

        if self.instance and 'organisation' in attrs and attrs['organisation'].id != self.instance.organisation_id:
            raise serializers.ValidationError({'organisation': 'Organisation cannot be changed once the family group is created.'})

        return attrs
    
    def create(self, validated_data):
        """Create family group and set created_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        
        return super().create(validated_data)


# ============================================================================
# ATTENDEE MESSAGE SERIALIZERS
# ============================================================================

class AttendeeMessageListSerializer(serializers.ModelSerializer):
    """List serializer for AttendeeMessage."""
    
    _links = serializers.SerializerMethodField()
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True, allow_null=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    responsed_by_name = serializers.CharField(
        source='responsed_by.get_full_name', read_only=True, allow_null=True
    )
    is_responded = serializers.SerializerMethodField()
    
    class Meta:
        model = AttendeeMessage
        fields = (
            'id', 'attendee', 'attendee_name', 'subject', 'priority', 'priority_display',
            'submitted_at', 'responsed_at', 'responsed_by', 'responsed_by_name',
            'is_responded', '_links'
        )
        read_only_fields = ('id', 'submitted_at', 'sent_at', 'responsed_at')
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_responded(self, obj) -> bool:
        """Check if message has been responded to."""
        return obj.responsed_at is not None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'responsed_by': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/attendee/messages/{obj.id}/")
        }
        
        if obj.attendee:
            links['attendee'] = request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            )
        
        if obj.responsed_by:
            links['responsed_by'] = request.build_absolute_uri(f"/api/users/{obj.responsed_by.id}/")
        
        return links


class AttendeeMessageDetailSerializer(AttendeeMessageListSerializer):
    """Detailed serializer for AttendeeMessage with full content."""
    
    class Meta(AttendeeMessageListSerializer.Meta):
        fields = AttendeeMessageListSerializer.Meta.fields + ('message', 'response', 'admin_notes')


class AttendeeMessageCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating AttendeeMessage."""
    
    class Meta:
        model = AttendeeMessage
        fields = ('attendee', 'subject', 'message', 'priority')
    
    def validate(self, attrs):
        """Validate message creation."""
        if not attrs.get('subject') or not attrs.get('subject').strip():
            raise serializers.ValidationError({'subject': 'Subject cannot be empty.'})
        
        if not attrs.get('message') or not attrs.get('message').strip():
            raise serializers.ValidationError({'message': 'Message content cannot be empty.'})
        
        return attrs


class AttendeeMessageUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating AttendeeMessage (primarily for staff responses)."""
    
    class Meta:
        model = AttendeeMessage
        fields = ('response', 'admin_notes', 'priority')
    
    def update(self, instance, validated_data):
        """Update message and set response timestamp."""
        if 'response' in validated_data and validated_data['response']:
            request = self.context.get('request')
            instance.responsed_at = timezone.now()
            if request and hasattr(request, 'user'):
                instance.responsed_by = request.user
        
        return super().update(instance, validated_data)
