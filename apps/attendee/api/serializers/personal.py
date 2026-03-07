"""
Personal information serializers for the attendee app.

Provides serializers for personal attendee data including accessibility requirements,
dietary requirements, medical conditions, emergency contacts, consents, attendance, and organisations.
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from typing import Dict, Any

from apps.attendee.models import (
    Attendee,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    EmergencyContact, Consent, AttendeeConsent,
    EventAttendance, AttendeeOrganisation,
    FamilyAttendee, HumanRelationshipChoices
)
from apps.common.models import VerificationStatus

User = get_user_model()


# ============================================================================
# ACCESSIBILITY REQUIREMENT SERIALIZERS
# ============================================================================

class AccessibilityRequirementSerializer(serializers.ModelSerializer):
    """Serializer for AccessibilityRequirement."""
    
    _links = serializers.SerializerMethodField()
    verification_status_display = serializers.CharField(
        source='get_verification_status_display', read_only=True
    )
    
    class Meta:
        model = AccessibilityRequirement
        fields = (
            'id', 'code', 'label', 'description', 'active',
            'verification_status', 'verification_status_display',
            'verified_by', 'verified_updated_at', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at', 'verified_updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/attendee/accessibility-requirements/{obj.id}/"
            )
        }


class AttendeeAccessibilityRequirementSerializer(serializers.ModelSerializer):
    """Serializer for AttendeeAccessibilityRequirement with nested requirement details."""
    
    _links = serializers.SerializerMethodField()
    requirement_details = AccessibilityRequirementSerializer(
        source='accessibility_requirement', read_only=True
    )
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    verification_status_display = serializers.CharField(
        source='get_verification_status_display', read_only=True
    )
    
    class Meta:
        model = AttendeeAccessibilityRequirement
        fields = (
            'id', 'attendee', 'attendee_name', 'accessibility_requirement',
            'requirement_details', 'details', 'notes',
            'verification_status', 'verification_status_display',
            'verified_by', 'verified_updated_at', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'attendee', 'attendee_name', 'added_at', 'updated_at', 'verified_updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'accessibility_requirement': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/attendee/attendee-accessibility-requirements/{obj.id}/"
            ),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            ),
            'accessibility_requirement': request.build_absolute_uri(
                f"/api/attendee/accessibility-requirements/{obj.accessibility_requirement.id}/"
            )
        }
    
    def validate(self, attrs):
        """Validate that the same requirement isn't added twice."""
        attendee = attrs.get('attendee', self.instance.attendee if self.instance else None)
        requirement = attrs.get('accessibility_requirement')
        
        if attendee and requirement:
            # Check for duplicates (exclude current instance in updates)
            queryset = AttendeeAccessibilityRequirement.objects.filter(
                attendee=attendee,
                accessibility_requirement=requirement
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise serializers.ValidationError(
                    "This accessibility requirement is already assigned to this attendee."
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create and set added_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['added_by'] = request.user
        
        return super().create(validated_data)


# ============================================================================
# DIETARY REQUIREMENT SERIALIZERS
# ============================================================================

class DietaryRequirementSerializer(serializers.ModelSerializer):
    """Serializer for DietaryRequirement."""
    
    _links = serializers.SerializerMethodField()
    verification_status_display = serializers.CharField(
        source='get_verification_status_display', read_only=True
    )
    
    class Meta:
        model = DietaryRequirement
        fields = (
            'id', 'code', 'label', 'description', 'active',
            'verification_status', 'verification_status_display',
            'verified_by', 'verified_updated_at', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at', 'verified_updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/attendee/dietary-requirements/{obj.id}/")
        }


class AttendeeDietaryRequirementSerializer(serializers.ModelSerializer):
    """Serializer for AttendeeDietaryRequirement with nested requirement details."""
    
    _links = serializers.SerializerMethodField()
    requirement_details = DietaryRequirementSerializer(
        source='dietary_requirement', read_only=True
    )
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    verification_status_display = serializers.CharField(
        source='get_verification_status_display', read_only=True
    )
    
    class Meta:
        model = AttendeeDietaryRequirement
        fields = (
            'id', 'attendee', 'attendee_name', 'dietary_requirement',
            'requirement_details', 'details', 'notes',
            'verification_status', 'verification_status_display',
            'verified_by', 'verified_updated_at', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'attendee', 'attendee_name', 'added_at', 'updated_at', 'verified_updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'dietary_requirement': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/attendee/attendee-dietary-requirements/{obj.id}/"
            ),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            ),
            'dietary_requirement': request.build_absolute_uri(
                f"/api/attendee/dietary-requirements/{obj.dietary_requirement.id}/"
            )
        }
    
    def validate(self, attrs):
        """Validate that the same requirement isn't added twice."""
        attendee = attrs.get('attendee', self.instance.attendee if self.instance else None)
        requirement = attrs.get('dietary_requirement')
        
        if attendee and requirement:
            queryset = AttendeeDietaryRequirement.objects.filter(
                attendee=attendee,
                dietary_requirement=requirement
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise serializers.ValidationError(
                    "This dietary requirement is already assigned to this attendee."
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create and set added_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['added_by'] = request.user
        
        return super().create(validated_data)


# ============================================================================
# MEDICAL CONDITION SERIALIZERS
# ============================================================================

class MedicalConditionSerializer(serializers.ModelSerializer):
    """Serializer for MedicalCondition."""
    
    _links = serializers.SerializerMethodField()
    verification_status_display = serializers.CharField(
        source='get_verification_status_display', read_only=True
    )
    
    class Meta:
        model = MedicalCondition
        fields = (
            'id', 'code', 'label', 'description', 'active',
            'verification_status', 'verification_status_display',
            'verified_by', 'verified_updated_at', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at', 'verified_updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/attendee/medical-conditions/{obj.id}/")
        }


class AttendeeMedicalConditionSerializer(serializers.ModelSerializer):
    """Serializer for AttendeeMedicalCondition with nested condition details."""
    
    _links = serializers.SerializerMethodField()
    condition_details = MedicalConditionSerializer(
        source='medical_condition', read_only=True
    )
    attendee = serializers.SlugRelatedField(
        slug_field='attendee_id',
        queryset=Attendee.objects.all()
    )
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    verification_status_display = serializers.CharField(
        source='get_verification_status_display', read_only=True
    )

    
    class Meta:
        model = AttendeeMedicalCondition
        fields = (
            'id', 'attendee', 'attendee_name', 'medical_condition',
            'condition_details', 'details', 'notes', 'severity',
            'verification_status', 'verification_status_display',
            'verified_by', 'verified_updated_at', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at', 'verified_updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'medical_condition': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/attendee/attendee-medical-conditions/{obj.id}/"
            ),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            ),
            'medical_condition': request.build_absolute_uri(
                f"/api/attendee/medical-conditions/{obj.medical_condition.id}/"
            )
        }
    
    def validate(self, attrs):
        """Validate that the same condition isn't added twice."""
        attendee = attrs.get('attendee', self.instance.attendee if self.instance else None)
        condition = attrs.get('medical_condition')
        
        if attendee and condition:
            queryset = AttendeeMedicalCondition.objects.filter(
                attendee=attendee,
                medical_condition=condition
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise serializers.ValidationError(
                    "This medical condition is already assigned to this attendee."
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create and set added_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['added_by'] = request.user
        
        return super().create(validated_data)


# ============================================================================
# EMERGENCY CONTACT SERIALIZERS
# ============================================================================

class EmergencyContactSerializer(serializers.ModelSerializer):
    """Serializer for EmergencyContact."""
    
    _links = serializers.SerializerMethodField()
    full_name = serializers.CharField(read_only=True)
    relationship_display = serializers.CharField(source='get_relationship_display', read_only=True)
    verification_status_display = serializers.CharField(
        source='get_verification_status_display', read_only=True
    )
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    
    class Meta:
        model = EmergencyContact
        fields = (
            'id', 'attendee', 'attendee_name', 'first_name', 'last_name', 'full_name',
            'relationship', 'relationship_display', 'phone_number', 'email',
            'primary_contact', 'verification_status', 'verification_status_display',
            'verified_by', 'verified_updated_at', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'attendee', 'attendee_name', 'full_name', 'added_at', 'updated_at', 'verified_updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/attendee/emergency-contacts/{obj.id}/"),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            )
        }
    
    def validate(self, attrs):
        """Validate emergency contact data."""
        # Ensure phone number is provided
        if not attrs.get('phone_number') and not (self.instance and self.instance.phone_number):
            raise serializers.ValidationError({
                'phone_number': 'Phone number is required for emergency contacts.'
            })
        
        # Validate names are not empty
        first_name = attrs.get('first_name', self.instance.first_name if self.instance else None)
        last_name = attrs.get('last_name', self.instance.last_name if self.instance else None)
        
        if first_name and not first_name.strip():
            raise serializers.ValidationError({'first_name': 'First name cannot be empty.'})
        
        if last_name and not last_name.strip():
            raise serializers.ValidationError({'last_name': 'Last name cannot be empty.'})
        
        return attrs
    
    def create(self, validated_data):
        """Create and set added_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['added_by'] = request.user
        
        return super().create(validated_data)


# ============================================================================
# CONSENT SERIALIZERS
# ============================================================================

class ConsentSerializer(serializers.ModelSerializer):
    """Serializer for Consent."""
    
    _links = serializers.SerializerMethodField()
    event_title = serializers.CharField(source='event.title', read_only=True)
    
    class Meta:
        model = Consent
        fields = (
            'id', 'event', 'event_title', 'code', 'title', 'description',
            'external_link', 'version', 'required', 'active',
            'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/attendee/consents/{obj.id}/")
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/")
        
        return links
    
    def create(self, validated_data):
        """Create consent and set defined_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['defined_by'] = request.user
        
        return super().create(validated_data)


class AttendeeConsentSerializer(serializers.ModelSerializer):
    """Serializer for AttendeeConsent."""
    
    _links = serializers.SerializerMethodField()
    consent_details = ConsentSerializer(source='consent', read_only=True)
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    given_by_name = serializers.CharField(
        source='given_by.get_full_name', read_only=True, allow_null=True
    )
    recorded_by_name = serializers.CharField(
        source='recorded_by.get_full_name', read_only=True, allow_null=True
    )
    
    class Meta:
        model = AttendeeConsent
        fields = (
            'id', 'attendee', 'attendee_name', 'consent', 'consent_details',
            'consent_given', 'given_at', 'given_by', 'given_by_name',
            'recorded_at', 'recorded_by', 'recorded_by_name', '_links'
        )
        read_only_fields = ('id', 'attendee', 'attendee_name', 'recorded_at', 'given_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'consent': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/attendee/attendee-consents/{obj.id}/"),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            ),
            'consent': request.build_absolute_uri(f"/api/attendee/consents/{obj.consent.id}/")
        }
    
    def validate(self, attrs):
        """Validate that the same consent isn't recorded twice."""        
        attendee = attrs.get('attendee', self.instance.attendee if self.instance else None)

        if not attendee:
            request = self.context.get('request')
            if request and hasattr(request, 'user'):
                # Try to get attendee from URL kwargs if not provided in data
                attendee_id = self.context['view'].kwargs.get('attendee_id')
                if attendee_id:
                    try:
                        attendee = Attendee.objects.get(attendee_id=attendee_id, deleted_at__isnull=True)
                    except Attendee.DoesNotExist:
                        pass


        consent = attrs.get('consent')
        if attendee and consent:
            queryset = AttendeeConsent.objects.filter(
                attendee=attendee,
                consent=consent
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise serializers.ValidationError(
                    "This consent is already recorded for this attendee."
                )
        
        return attrs
        
    def create(self, validated_data):
        request = self.context.get('request')

        if request and hasattr(request, 'user'):
            validated_data['recorded_by'] = request.user
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):

        if 'consent_given' in validated_data and validated_data['consent_given'] and not instance.consent_given:
            request = self.context.get('request')
            instance.given_at = timezone.now()
            if request and hasattr(request, 'user'):
                instance.given_by = request.user
        
        return super().update(instance, validated_data)


# ============================================================================
# EVENT ATTENDANCE SERIALIZERS
# ============================================================================

class EventAttendanceSerializer(serializers.ModelSerializer):
    """Serializer for EventAttendance."""
    
    _links = serializers.SerializerMethodField()
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True)
    is_checked_in = serializers.BooleanField(read_only=True)
    is_checked_out = serializers.BooleanField(read_only=True)
    check_in_by_name = serializers.CharField(
        source='check_in_by.get_full_name', read_only=True, allow_null=True
    )
    check_out_by_name = serializers.CharField(
        source='check_out_by.get_full_name', read_only=True, allow_null=True
    )
    
    class Meta:
        model = EventAttendance
        fields = (
            'id', 'event', 'event_title', 'attendee', 'attendee_name',
            'check_in_time', 'check_out_time', 'check_in_by', 'check_in_by_name',
            'check_out_by', 'check_out_by_name', 'is_checked_in', 'is_checked_out', '_links'
        )
        read_only_fields = ('id', 'check_in_time', 'check_out_time', 'is_checked_in', 'is_checked_out')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/attendee/event-attendances/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            )
        }


# ============================================================================
# ATTENDEE ORGANISATION SERIALIZERS
# ============================================================================

class AttendeeOrganisationSerializer(serializers.ModelSerializer):
    """Serializer for AttendeeOrganisation."""
    
    _links = serializers.SerializerMethodField()
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    organisation_title = serializers.CharField(source='organisation.title', read_only=True)
    added_by_name = serializers.CharField(
        source='added_by.get_full_name', read_only=True, allow_null=True
    )
    
    class Meta:
        model = AttendeeOrganisation
        fields = (
            'id', 'attendee', 'attendee_name', 'organisation', 'organisation_title',
            'added_at', 'added_by', 'added_by_name', '_links'
        )
        read_only_fields = ('id', 'attendee', 'attendee_name', 'added_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/attendee/attendee-organisations/{obj.id}/"),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            ),
            'organisation': request.build_absolute_uri(
                f"/api/organisations/{obj.organisation.id}/"
            )
        }
    
    def validate(self, attrs):
        """Validate that the same organisation isn't linked twice."""
        attendee = attrs.get('attendee', self.instance.attendee if self.instance else None)
        organisation = attrs.get('organisation')
        
        if attendee and organisation:
            queryset = AttendeeOrganisation.objects.filter(
                attendee=attendee,
                organisation=organisation
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise serializers.ValidationError(
                    "This organisation is already linked to this attendee."
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create and set added_by from request user."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['added_by'] = request.user
        
        return super().create(validated_data)


# ============================================================================
# FAMILY ATTENDEE SERIALIZERS
# ============================================================================

class FamilyAttendeeSerializer(serializers.ModelSerializer):
    """Serializer for FamilyAttendee."""
    
    _links = serializers.SerializerMethodField()
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    family_name = serializers.CharField(source='family_group.family_name', read_only=True)
    relationship_display = serializers.CharField(source='get_relationship_display', read_only=True)
    
    class Meta:
        model = FamilyAttendee
        fields = (
            'id', 'family_group', 'family_name', 'attendee', 'attendee_name',
            'relationship', 'relationship_display', 'is_primary_guardian',
            'added_at', '_links'
        )
        read_only_fields = ('id', 'added_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'family_group': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/attendee/family-attendees/{obj.id}/"),
            'family_group': request.build_absolute_uri(
                f"/api/attendee/family-groups/{obj.family_group.id}/"
            ),
            'attendee': request.build_absolute_uri(
                f"/api/attendee/attendees/{obj.attendee.attendee_id}/"
            )
        }
    
    def validate(self, attrs):
        """Validate family attendee assignment."""
        family_group = attrs.get('family_group', self.instance.family_group if self.instance else None)
        attendee = attrs.get('attendee', self.instance.attendee if self.instance else None)
        
        if family_group and attendee:
            queryset = FamilyAttendee.objects.filter(
                family_group=family_group,
                attendee=attendee
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise serializers.ValidationError(
                    "This attendee is already a member of this family group."
                )
        
        return attrs
