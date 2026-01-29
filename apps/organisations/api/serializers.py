"""
Production-grade serializers for the organisations app.

Provides comprehensive serializers for organisation management with HATEOAS support,
extensive validation, and separation of concerns (list/detail/create/update).

Serializers:
    Organisation: OrganisationListSerializer, OrganisationDetailSerializer, OrganisationCreateUpdateSerializer
    OrganisationContact: OrganisationContactSerializer, OrganisationContactCreateUpdateSerializer
    OrganisationControl: OrganisationControlSerializer, OrganisationControlCreateUpdateSerializer
    UserOrganisationMembership: UserOrganisationMembershipListSerializer, UserOrganisationMembershipDetailSerializer, UserOrganisationMembershipCreateUpdateSerializer
    OrganisationAcceptanceCode: OrganisationAcceptanceCodeSerializer, OrganisationAcceptanceCodeCreateUpdateSerializer
    OrganisationInvite: OrganisationInviteListSerializer, OrganisationInviteDetailSerializer, OrganisationInviteCreateUpdateSerializer
    InvolvedEventOrganisation: InvolvedEventOrganisationSerializer, InvolvedEventOrganisationCreateUpdateSerializer
    EventSponsor: EventSponsorListSerializer, EventSponsorDetailSerializer, EventSponsorCreateUpdateSerializer
    EventSponsorPackage: EventSponsorPackageListSerializer, EventSponsorPackageDetailSerializer, EventSponsorPackageCreateUpdateSerializer
    Leader: LeaderListSerializer, LeaderDetailSerializer, LeaderCreateUpdateSerializer

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from djmoney.contrib.django_rest_framework import MoneyField
from decimal import Decimal
from typing import Dict, Any, Optional

from apps.organisations.models import (
    Organisation, OrganisationContact, OrganisationControl,
    UserOrganisationMembership, OrganisationAcceptanceCode, OrganisationInvite,
    InvolvedEventOrganisation, InvolvedOrganisationRoleChoices,
    EventSponsor, EventSponsorPackage,
    Leader
)

User = get_user_model()


# ============================================================================
# ORGANISATION SERIALIZERS
# ============================================================================

class OrganisationListSerializer(serializers.ModelSerializer):
    """List serializer for Organisation with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    added_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = Organisation
        fields = (
            'id', 'title', 'description', 'external_website',
            'required_acceptance_code', 'requires_manual_verification',
            'created_by', 'created_by_name', 'added_at', 'updated_at', 
            'landing_image', 'logo',
            '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None, 'source': 'added_at'},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'created_by': {'type': 'string', 'format': 'uri'},
            'contacts': {'type': 'string', 'format': 'uri'},
            'memberships': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/organisations/list/{obj.id}/"),
            'contacts': request.build_absolute_uri(f"/api/organisations/list/{obj.id}/contacts/"),
            'memberships': request.build_absolute_uri(f"/api/organisations/list/{obj.id}/memberships/"),
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(f"/api/users/{obj.created_by.id}/")
        
        return links


class OrganisationDetailSerializer(OrganisationListSerializer):
    """Detailed serializer for Organisation with full information."""
    
    contacts = serializers.SerializerMethodField(help_text="Organisation contacts")
    memberships_count = serializers.SerializerMethodField(help_text="Number of members")
    controllers_count = serializers.SerializerMethodField(help_text="Number of controllers")
    logo_url = serializers.SerializerMethodField(help_text="Logo image URL")
    landing_image_url = serializers.SerializerMethodField(help_text="Landing image URL")
    
    class Meta(OrganisationListSerializer.Meta):
        fields = OrganisationListSerializer.Meta.fields + (
            'logo', 'logo_url', 'logo_uploaded_at',
            'landing_image', 'landing_image_url', 'landing_image_uploaded_at',
            'contacts', 'memberships_count', 'controllers_count'
        )
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_logo_url(self, obj) -> Optional[str]:
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_landing_image_url(self, obj) -> Optional[str]:
        if obj.landing_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.landing_image.url)
            return obj.landing_image.url
        return None
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_contacts(self, obj) -> list:
        """Return summary of organisation contacts."""
        contacts = obj.contacts.all()[:5]
        return [{
            'id': contact.id,
            'name': contact.name,
            'email': contact.email,
            'phone': contact.phone,
            'label': contact.label,
        } for contact in contacts]
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_memberships_count(self, obj) -> int:
        return obj.memberships.count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_controllers_count(self, obj) -> int:
        return obj.controllers.count()


class OrganisationCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for Organisation with validation."""
    
    class Meta:
        model = Organisation
        fields = (
            'title', 'description', 'external_website', 'logo', 'landing_image',
            'required_acceptance_code', 'requires_manual_verification'
        )
    
    def validate_title(self, value):
        """Ensure title is unique."""
        instance = self.instance
        if Organisation.objects.filter(title=value).exclude(pk=instance.pk if instance else None).exists():
            raise serializers.ValidationError("An organisation with this title already exists.")
        return value
    
    def validate_external_website(self, value):
        """Validate external website URL format."""
        if value and not (value.startswith('http://') or value.startswith('https://')):
            raise serializers.ValidationError("Website URL must start with http:// or https://")
        return value
    
    def create(self, validated_data):
        """Create organisation with current user as creator."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# ORGANISATION CONTACT SERIALIZERS
# ============================================================================

class OrganisationContactSerializer(serializers.ModelSerializer):
    """Serializer for OrganisationContact."""
    
    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    
    class Meta:
        model = OrganisationContact
        fields = (
            'id', 'organisation', 'organisation_name', 'name', 'email',
            'phone', 'label', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/organisations/contacts/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.id}/"),
        }


class OrganisationContactCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for OrganisationContact with validation."""
    
    class Meta:
        model = OrganisationContact
        fields = ('organisation', 'name', 'email', 'phone', 'label')
    
    def validate_email(self, value):
        """Validate email format."""
        if value and '@' not in value:
            raise serializers.ValidationError("Enter a valid email address.")
        return value


# ============================================================================
# ORGANISATION CONTROL SERIALIZERS
# ============================================================================

class OrganisationControlSerializer(serializers.ModelSerializer):
    """Serializer for OrganisationControl."""
    
    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = OrganisationControl
        fields = (
            'id', 'organisation', 'organisation_name', 'user', 'user_name',
            'added_by', 'added_by_name', 'added_at', '_links'
        )
        read_only_fields = ('id', 'added_at')
        extra_kwargs = {
            'added_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
            'user': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/organisations/controls/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.id}/"),
            'user': request.build_absolute_uri(f"/api/users/{obj.user.id}/"),
        }


class OrganisationControlCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for OrganisationControl with validation."""
    
    class Meta:
        model = OrganisationControl
        fields = ('organisation', 'user')
    
    def validate(self, attrs):
        """Prevent duplicate control assignments."""
        organisation = attrs.get('organisation')
        user = attrs.get('user')
        
        if OrganisationControl.objects.filter(organisation=organisation, user=user).exists():
            raise serializers.ValidationError(
                "This user already has control over this organisation."
            )
        
        return attrs
    
    def create(self, validated_data):
        """Create control with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# USER ORGANISATION MEMBERSHIP SERIALIZERS
# ============================================================================

class UserOrganisationMembershipListSerializer(serializers.ModelSerializer):
    """List serializer for UserOrganisationMembership."""
    
    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    requires_verification = serializers.BooleanField(read_only=True)
    is_verified = serializers.SerializerMethodField()
    
    class Meta:
        model = UserOrganisationMembership
        fields = (
            'id', 'organisation', 'organisation_name', 'user', 'user_name', 'user_email',
            'added_by', 'added_by_name', 'verified_at', 'requires_verification',
            'is_verified', 'added_at', '_links'
        )
        read_only_fields = ('id', 'verified_at', 'added_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'verified_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_verified(self, obj) -> bool:
        return obj.verified_at is not None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
            'user': {'type': 'string', 'format': 'uri'},
            'verify_with_code': {'type': 'string', 'format': 'uri'},
            'verify_manually': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/organisations/memberships/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.id}/"),
            'user': request.build_absolute_uri(f"/api/users/{obj.user.id}/"),
        }
        
        if not obj.verified_at:
            if obj.organisation.required_acceptance_code:
                links['verify_with_code'] = request.build_absolute_uri(
                    f"/api/organisations/memberships/{obj.id}/verify-with-code/"
                )
            if obj.organisation.requires_manual_verification:
                links['verify_manually'] = request.build_absolute_uri(
                    f"/api/organisations/memberships/{obj.id}/verify-manually/"
                )
        
        return links


class UserOrganisationMembershipDetailSerializer(UserOrganisationMembershipListSerializer):
    """Detailed serializer for UserOrganisationMembership."""
    
    class Meta(UserOrganisationMembershipListSerializer.Meta):
        fields = UserOrganisationMembershipListSerializer.Meta.fields


class UserOrganisationMembershipCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for UserOrganisationMembership."""
    access_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    class Meta:
        model = UserOrganisationMembership
        fields = ('id','organisation', 'user', 'access_code')
    
    def validate(self, attrs):
        """Prevent duplicate membership."""
        organisation = attrs.get('organisation')
        user = attrs.get('user')
        
        if UserOrganisationMembership.objects.filter(
            organisation=organisation, user=user
        ).exists():
            raise serializers.ValidationError(
                "This user is already a member of this organisation."
            )
        
        if organisation.required_acceptance_code:
            access_code = attrs.pop('access_code', '').strip()
            if not access_code:
                raise serializers.ValidationError(
                    "An acceptance code is required to join this organisation."
                )
            try:
                code_obj = OrganisationAcceptanceCode.objects.get(
                    organisation=organisation,
                    code=access_code,
                    is_active=True
                )
                if not code_obj.is_valid:
                    raise serializers.ValidationError("The provided acceptance code is not valid.")
            except OrganisationAcceptanceCode.DoesNotExist:
                raise serializers.ValidationError("The provided acceptance code is not valid.")
        
        return attrs
    
    def create(self, validated_data):
        """Create membership with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user

        organisation = validated_data['organisation']
        if organisation.required_acceptance_code:
            validated_data["verified_at"] = timezone.now()

        return super().create(validated_data)


# ============================================================================
# ORGANISATION ACCEPTANCE CODE SERIALIZERS
# ============================================================================

class OrganisationAcceptanceCodeSerializer(serializers.ModelSerializer):
    """Serializer for OrganisationAcceptanceCode."""
    
    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    is_valid = serializers.BooleanField(read_only=True)
    is_single_use = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = OrganisationAcceptanceCode
        fields = (
            'id', 'organisation', 'organisation_name', 'code', 'uses', 'max_uses',
            'is_active', 'is_valid', 'is_single_use', 'expires_at',
            'added_by', 'added_by_name', 'added_at', '_links'
        )
        read_only_fields = ('id', 'code', 'uses', 'added_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'expires_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/organisations/acceptance-codes/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.id}/"),
        }


class OrganisationAcceptanceCodeCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for OrganisationAcceptanceCode."""
    
    class Meta:
        model = OrganisationAcceptanceCode
        fields = ('organisation', 'code', 'max_uses', 'expires_at', 'is_active')
    
    def validate_expires_at(self, value):
        """Ensure expiry date is in the future."""
        if value and value < timezone.now():
            raise serializers.ValidationError("Expiry date must be in the future.")
        return value
    
    def validate_max_uses(self, value):
        """Ensure max_uses is positive."""
        if value < 1:
            raise serializers.ValidationError("Maximum uses must be at least 1.")
        return value
    
    def create(self, validated_data):
        """Create acceptance code with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# ORGANISATION INVITE SERIALIZERS
# ============================================================================

class OrganisationInviteListSerializer(serializers.ModelSerializer):
    """List serializer for OrganisationInvite."""
    
    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    target_user_name = serializers.CharField(source='target_user.username', read_only=True, allow_null=True)
    target_user_email = serializers.EmailField(source='target_user.email', read_only=True, allow_null=True)
    invited_by_name = serializers.CharField(source='invited_by.username', read_only=True, allow_null=True)
    is_valid = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = OrganisationInvite
        fields = (
            'id', 'organisation', 'organisation_name', 'target_user',
            'target_user_name', 'target_user_email', 'invited_by', 'invited_by_name',
            'accepted', 'accepted_at', 'is_active', 'is_valid',
            'expires_at', 'added_at', '_links'
        )
        read_only_fields = ('id', 'accepted', 'accepted_at', 'added_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'accepted_at': {'default': None},
            'expires_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
            'target_user': {'type': 'string', 'format': 'uri'},
            'accept': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/organisations/invites/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.id}/"),
        }
        
        if obj.target_user:
            links['target_user'] = request.build_absolute_uri(f"/api/users/{obj.target_user.id}/")
        
        if obj.is_valid and not obj.accepted:
            links['accept'] = request.build_absolute_uri(f"/api/organisations/invites/{obj.id}/accept/")
        
        return links


class OrganisationInviteDetailSerializer(OrganisationInviteListSerializer):
    """Detailed serializer for OrganisationInvite."""
    
    class Meta(OrganisationInviteListSerializer.Meta):
        fields = OrganisationInviteListSerializer.Meta.fields


class OrganisationInviteCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for OrganisationInvite."""
    
    class Meta:
        model = OrganisationInvite
        fields = ('organisation', 'target_user', 'expires_at', 'is_active')
    
    def validate(self, attrs):
        """Prevent duplicate invites and validate."""
        organisation = attrs.get('organisation')
        target_user = attrs.get('target_user')
        
        # Check for existing active invite
        existing = OrganisationInvite.objects.filter(
            organisation=organisation,
            target_user=target_user,
            is_active=True,
            accepted=False
        )
        if existing.exists():
            raise serializers.ValidationError(
                "An active invite already exists for this user and organisation."
            )
        
        # Check if user is already a member
        if UserOrganisationMembership.objects.filter(
            organisation=organisation,
            user=target_user
        ).exists():
            raise serializers.ValidationError(
                "This user is already a member of this organisation."
            )
        
        return attrs
    
    def validate_expires_at(self, value):
        """Ensure expiry date is in the future."""
        if value and value < timezone.now():
            raise serializers.ValidationError("Expiry date must be in the future.")
        return value
    
    def create(self, validated_data):
        """Create invite with current user as invited_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['invited_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# INVOLVED EVENT ORGANISATION SERIALIZERS
# ============================================================================

class InvolvedEventOrganisationSerializer(serializers.ModelSerializer):
    """Serializer for InvolvedEventOrganisation."""
    
    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    event_name = serializers.CharField(source='event.title', read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = InvolvedEventOrganisation
        fields = (
            'id', 'organisation', 'organisation_name', 'event', 'event_name',
            'role', 'role_display', 'added_by', 'added_by_name', 'added_at', '_links'
        )
        read_only_fields = ('id', 'added_at')
        extra_kwargs = {
            'added_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/organisations/involved-events/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
        }


class InvolvedEventOrganisationCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for InvolvedEventOrganisation."""
    
    class Meta:
        model = InvolvedEventOrganisation
        fields = ('organisation', 'event', 'role')
    
    def validate(self, attrs):
        """Prevent duplicate involvement with same role."""
        organisation = attrs.get('organisation')
        event = attrs.get('event')
        role = attrs.get('role')
        
        if InvolvedEventOrganisation.objects.filter(
            organisation=organisation, event=event, role=role
        ).exists():
            raise serializers.ValidationError(
                "This organisation already has this role for this event."
            )
        
        return attrs
    
    def create(self, validated_data):
        """Create involvement with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# EVENT SPONSOR SERIALIZERS
# ============================================================================

class EventSponsorListSerializer(serializers.ModelSerializer):
    """List serializer for EventSponsor."""
    
    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    event_name = serializers.CharField(source='event.title', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    packages_count = serializers.SerializerMethodField()
    
    class Meta:
        model = EventSponsor
        fields = (
            'id', 'name', 'description', 'organisation', 'organisation_name',
            'event', 'event_name', 'added_by', 'added_by_name',
            'packages_count', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_packages_count(self, obj) -> int:
        return obj.sponsorship_packages.count()
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'packages': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/organisations/sponsors/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
            'packages': request.build_absolute_uri(f"/api/organisations/sponsors/{obj.id}/packages/"),
        }


class EventSponsorDetailSerializer(EventSponsorListSerializer):
    """Detailed serializer for EventSponsor with packages."""
    
    packages = serializers.SerializerMethodField(help_text="Sponsorship packages")
    
    class Meta(EventSponsorListSerializer.Meta):
        fields = EventSponsorListSerializer.Meta.fields + ('packages',)
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_packages(self, obj) -> list:
        """Return summary of sponsorship packages."""
        packages = obj.sponsorship_packages.all()[:10]
        return [{
            'id': pkg.id,
            'package_name': pkg.package_name,
            'base_amount': str(pkg.base_amount),
            'modified_amount': str(pkg.modified_amount),
        } for pkg in packages]


class EventSponsorCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for EventSponsor."""
    
    class Meta:
        model = EventSponsor
        fields = ('name', 'description', 'organisation', 'event')
    
    def validate_name(self, value):
        """Validate name is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("Sponsor name cannot be empty.")
        return value
    
    def create(self, validated_data):
        """Create sponsor with current user as added_by."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# EVENT SPONSOR PACKAGE SERIALIZERS
# ============================================================================

class EventSponsorPackageListSerializer(serializers.ModelSerializer):
    """List serializer for EventSponsorPackage with PayableModel support."""
    
    _links = serializers.SerializerMethodField()
    sponsor_name = serializers.CharField(source='sponsor.name', read_only=True)
    event_name = serializers.CharField(source='event.title', read_only=True)
    base_amount = MoneyField(max_digits=14, decimal_places=2, read_only=True)
    modified_amount = serializers.SerializerMethodField(help_text="Amount after percentage modifier")
    has_payment = serializers.SerializerMethodField()
    
    class Meta:
        model = EventSponsorPackage
        fields = (
            'id', 'sponsor', 'sponsor_name', 'event', 'event_name',
            'package_name', 'package_description', 'base_amount',
            'percentage_modifier', 'modified_amount', 'has_payment',
            'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_modified_amount(self, obj) -> str:
        return str(obj.modified_amount)
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_has_payment(self, obj) -> bool:
        """Check if package has associated payment."""
        return obj.payment is not None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'sponsor': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'payment': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/organisations/sponsor-packages/{obj.id}/"),
            'sponsor': request.build_absolute_uri(f"/api/organisations/sponsors/{obj.sponsor.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
        }
        
        # Add payment link if exists
        payment = obj.payment
        if payment:
            links['payment'] = request.build_absolute_uri(f"/api/payments/list/{payment.payment_id}/")
        
        return links


class EventSponsorPackageDetailSerializer(EventSponsorPackageListSerializer):
    """Detailed serializer for EventSponsorPackage with payment info."""
    
    payment_info = serializers.SerializerMethodField(help_text="Associated payment information")
    discounts_count = serializers.SerializerMethodField(help_text="Number of active discounts")
    
    class Meta(EventSponsorPackageListSerializer.Meta):
        fields = EventSponsorPackageListSerializer.Meta.fields + (
            'payment_info', 'discounts_count'
        )
    
    @extend_schema_field({'type': 'object', 'nullable': True})
    def get_payment_info(self, obj) -> Optional[Dict[str, Any]]:
        """Return payment information if exists and user has permission."""
        payment = obj.payment
        if not payment:
            return None
        
        return {
            'payment_id': str(payment.payment_id),
            'status': payment.status,
            'amount': str(payment.modified_amount),
            'created_at': payment.created_at.isoformat(),
        }
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_discounts_count(self, obj) -> int:
        """Return count of active discounts."""
        return obj.discounts.filter(active=True).count()


class EventSponsorPackageCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for EventSponsorPackage with validation."""
    
    base_amount = MoneyField(max_digits=14, decimal_places=2)
    
    class Meta:
        model = EventSponsorPackage
        fields = (
            'sponsor', 'event', 'package_name', 'package_description',
            'base_amount', 'percentage_modifier'
        )
    
    def validate_base_amount(self, value):
        """Ensure amount is non-negative."""
        if value.amount < 0:
            raise serializers.ValidationError("Base amount cannot be negative.")
        return value
    
    def validate_percentage_modifier(self, value):
        """Ensure percentage modifier is within valid range."""
        if not Decimal('-100.00') <= value <= Decimal('100.00'):
            raise serializers.ValidationError(
                "Percentage modifier must be between -100 and 100."
            )
        return value
    
    def validate(self, attrs):
        """Ensure sponsor and event match."""
        sponsor = attrs.get('sponsor')
        event = attrs.get('event')
        
        if sponsor and event and sponsor.event != event:
            raise serializers.ValidationError({
                'event': "Event must match the sponsor's event."
            })
        
        return attrs


# ============================================================================
# LEADER SERIALIZERS (Generic FK handling for locations and organisations)
# ============================================================================

class LeaderListSerializer(serializers.ModelSerializer):
    """List serializer for Leader with organisation grouping."""
    
    _links = serializers.SerializerMethodField()
    user_name = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    authority_object_name = serializers.SerializerMethodField(help_text="Name of the authority object (country, cluster, chapter, area, or organisation)")
    authority_type = serializers.SerializerMethodField(help_text="Type of authority")
    
    class Meta:
        model = Leader
        fields = (
            'id', 'user', 'user_name', 'user_email', 
            'organisation', 'organisation_name',
            'authority_type', 'authority_object_name', 
            'notes', 'added_by', 'added_by_name',
            'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_authority_object_name(self, obj) -> str:
        """Return the name of the authority object."""
        if obj.authority_object:
            return str(obj.authority_object)
        return "Unknown"
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_authority_type(self, obj) -> str:
        """Return the type of authority (country, cluster, chapter, area, organisation)."""
        if obj.target_type:
            return obj.target_type.model
        return "unknown"
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'user': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
            'authority_object': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/organisations/leaders/{obj.id}/"),
            'user': request.build_absolute_uri(f"/api/users/{obj.user.id}/"),
        }
        
        # Add link to organisation
        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/list/{obj.organisation.id}/"
            )
        
        # Add link to authority object based on type
        if obj.authority_object and obj.target_type:
            model_name = obj.target_type.model
            if model_name == 'organisation':
                links['authority_object'] = request.build_absolute_uri(
                    f"/api/organisations/list/{obj.target_id}/"
                )
            elif model_name == 'countrylocation':
                links['authority_object'] = request.build_absolute_uri(
                    f"/api/locations/countries/{obj.target_id}/"
                )
            elif model_name == 'clusterlocation':
                links['authority_object'] = request.build_absolute_uri(
                    f"/api/locations/clusters/{obj.target_id}/"
                )
            elif model_name == 'chapterlocation':
                links['authority_object'] = request.build_absolute_uri(
                    f"/api/locations/chapters/{obj.target_id}/"
                )
            elif model_name == 'arealocation':
                links['authority_object'] = request.build_absolute_uri(
                    f"/api/locations/areas/{obj.target_id}/"
                )
        
        return links


class LeaderDetailSerializer(LeaderListSerializer):
    """Detailed serializer for Leader."""
    
    class Meta(LeaderListSerializer.Meta):
        fields = LeaderListSerializer.Meta.fields


class LeaderCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for Leader with organisation required."""
    
    organisation = serializers.PrimaryKeyRelatedField(
        queryset=Organisation.objects.all(),
        required=True,
        help_text="The organisation this leader belongs to (required for grouping)"
    )
    target_type = serializers.CharField(write_only=True, required=False, help_text="Internal use only - do not set manually")
    target_id = serializers.IntegerField(write_only=True, required=False, help_text="Internal use only - do not set manually")
    
    class Meta:
        model = Leader
        fields = ('user', 'organisation', 'target_type', 'target_id', 'notes')
    
    def validate(self, attrs):
        """Validate leader assignment and require organisation."""
        user = attrs.get('user')
        organisation = attrs.get('organisation')
        
        if not organisation:
            raise serializers.ValidationError({
                "organisation": "Organisation is required for all leaders."
            })
        
        # If target_type and target_id are provided, validate the generic FK
        target_type = attrs.get('target_type')
        target_id = attrs.get('target_id')
        
        if target_type and target_id:
            # Check for existing leadership
            if Leader.objects.filter(
                user=user,
                target_type=target_type,
                target_id=target_id
            ).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise serializers.ValidationError({
                    "user": "This user is already a leader of this location/organisation."
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create leader with organisation."""
        request = self.context.get('request')
        
        if request and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Update leader (target cannot be changed after creation)."""
        # Remove target fields to prevent changes
        validated_data.pop('target_type', None)
        validated_data.pop('target_id', None)
        
        return super().update(instance, validated_data)
