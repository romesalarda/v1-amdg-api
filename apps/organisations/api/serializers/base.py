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
    EventSponsor, EventSponsorPackage, EventSponsorInvite,
    Leader, LeaderLocationType, LocationLeaderInvite,
    LeaderPermission, OrganisationEventPolicy, OrganisationEventTypePolicyRestriction,
)
from apps.locations.models import (
    CountryLocation, ClusterLocation, ChapterLocation, AreaLocation,
)

User = get_user_model()


# ============================================================================
# ORGANISATION SERIALIZERS
# ============================================================================

class OrganisationListSerializer(serializers.ModelSerializer):
    """List serializer for Organisation with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    url_safe_title = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    added_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = Organisation
        fields = (
            'id', 'title', 'url_safe_title', 'description', 'external_website',
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
            'self': request.build_absolute_uri(f"/api/organisations/list/{obj.url_safe_title}/"),
            'contacts': request.build_absolute_uri(f"/api/organisations/list/{obj.url_safe_title}/contacts/"),
            'memberships': request.build_absolute_uri(f"/api/organisations/list/{obj.url_safe_title}/memberships/"),
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
    user_permissions = serializers.SerializerMethodField(
        help_text="Requesting user's permissions for this organisation (controller, member, leader status and codes)"
    )

    class Meta(OrganisationListSerializer.Meta):
        fields = OrganisationListSerializer.Meta.fields + (
            'logo', 'logo_url', 'logo_uploaded_at',
            'landing_image', 'landing_image_url', 'landing_image_uploaded_at',
            'contacts', 'memberships_count', 'controllers_count',
            'user_permissions',
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

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'is_staff': {'type': 'boolean'},
            'is_controller': {'type': 'boolean'},
            'is_member': {'type': 'boolean'},
            'is_leader': {'type': 'boolean'},
            'leader_permissions': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'permission_code': {'type': 'string'},
                        'allow_create': {'type': 'boolean'},
                        'allow_read': {'type': 'boolean'},
                        'allow_update': {'type': 'boolean'},
                        'allow_delete': {'type': 'boolean'},
                    },
                },
            },
        },
    })
    def get_user_permissions(self, obj) -> dict:
        """Return the requesting user's permission summary for this organisation."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return {
                'is_staff': False,
                'is_controller': False,
                'is_member': False,
                'is_leader': False,
                'leader_permissions': [],
            }
        user = request.user
        is_controller = (
            user.is_superuser
            or user.is_staff
            or OrganisationControl.objects.filter(organisation=obj, user=user).exists()
        )
        is_member = UserOrganisationMembership.objects.filter(
            organisation=obj, user=user
        ).exists()
        leader_qs = Leader.objects.filter(organisation=obj, user=user)
        is_leader = leader_qs.exists()
        leader_permissions = []
        if is_leader:
            leader_perms = LeaderPermission.objects.filter(
                leader__organisation=obj, leader__user=user
            ).values(
                'permission_code', 'allow_create', 'allow_read',
                'allow_update', 'allow_delete',
            )
            leader_permissions = list(leader_perms)
        return {
            'is_staff': user.is_superuser or user.is_staff,
            'is_controller': is_controller,
            'is_member': is_member,
            'is_leader': is_leader,
            'leader_permissions': leader_permissions,
        }


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
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
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
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
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
    profile_image = serializers.SerializerMethodField()
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    area_from = serializers.CharField(source='user.profile.area_from.area_name', read_only=True, allow_null=True)
    requires_verification = serializers.BooleanField(read_only=True)
    is_verified = serializers.SerializerMethodField()
    
    class Meta:
        model = UserOrganisationMembership
        fields = (
            'id', 'organisation', 'organisation_name', 'user', 'user_name', 'user_email',
            'profile_image', 'added_by', 'added_by_name', 'verified_at', 'requires_verification', 'area_from',
            'is_verified', 'added_at', 'is_organisation_controller', '_links'
        )
        
        read_only_fields = ('id', 'verified_at', 'added_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'verified_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_verified(self, obj) -> bool:
        return obj.verified_at is not None
    
    def get_profile_image(self, obj) -> Optional[str]:
        if obj.user.profile.profile_picture:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.user.profile.profile_picture.url)
            return obj.user.profile.profile_picture.url
        return None
    
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
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
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
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
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
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
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
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
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
    package_id = serializers.UUIDField(source='package.package_id', read_only=True, allow_null=True)
    package_name = serializers.CharField(source='package.package_name', read_only=True, allow_null=True)
    can_edit = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()
    
    class Meta:
        model = EventSponsor
        fields = (
            'id', 'sponsor_id', 'name', 'description', 'organisation', 'organisation_name',
            'event', 'event_name', 'added_by', 'added_by_name',
            'package', 'package_id', 'package_name',
            'verification_status', 'is_pending', 'is_verified', 'is_rejected', 'is_processed',
            'can_edit', 'can_approve', 'packages_count', 'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'sponsor_id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_packages_count(self, obj) -> int:
        return 1 if obj.package_id else 0

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_edit(self, obj) -> bool:
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True
        if OrganisationControl.objects.filter(organisation=obj.organisation, user=request.user).exists():
            return True

        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        return EventRoleAssignment.objects.filter(
            user=request.user,
            event=obj.event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).exists()

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_approve(self, obj) -> bool:
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True

        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        return EventRoleAssignment.objects.filter(
            user=request.user,
            event=obj.event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).exists()
    
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
            'self': request.build_absolute_uri(f"/api/organisations/sponsors/{obj.sponsor_id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
            'packages': request.build_absolute_uri(f"/api/organisations/sponsors/{obj.sponsor_id}/packages/"),
        }


class EventSponsorDetailSerializer(EventSponsorListSerializer):
    """Detailed serializer for EventSponsor with packages."""
    
    packages = serializers.SerializerMethodField(help_text="Sponsorship packages")
    
    class Meta(EventSponsorListSerializer.Meta):
        fields = EventSponsorListSerializer.Meta.fields + ('packages',)
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_packages(self, obj) -> list:
        """Return selected package summary, if any."""
        if not obj.package:
            return []

        return [{
            'id': obj.package.id,
            'package_id': str(obj.package.package_id),
            'package_name': obj.package.package_name,
            'tier': obj.package.tier,
            'base_amount': str(obj.package.base_amount),
            'modified_amount': str(obj.package.modified_amount),
        }]


class EventSponsorLedgerSerializer(serializers.Serializer):
    """Serializer for inbound/outbound sponsor list rows."""

    sponsor_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True, allow_null=True)
    organisation_id = serializers.IntegerField(source='organisation.id', read_only=True)
    organisation_title = serializers.CharField(source='organisation.title', read_only=True)
    event_id = serializers.UUIDField(source='event.event_id', read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True)
    package_id = serializers.SerializerMethodField()
    package_name = serializers.SerializerMethodField()
    chapter_location = serializers.IntegerField(source='chapter_location_id', read_only=True, allow_null=True)
    added_at = serializers.DateTimeField(read_only=True)
    added_by = serializers.IntegerField(source='added_by_id', read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True)
    payment = serializers.SerializerMethodField()


    @extend_schema_field(OpenApiTypes.STR)
    def get_package_id(self, obj):
        if not obj.package_id:
            return None
        return str(obj.package.package_id)

    @extend_schema_field(OpenApiTypes.STR)
    def get_package_name(self, obj):
        if not obj.package_id:
            return None
        return obj.package.package_name

    @extend_schema_field({
        'type': 'object',
        'nullable': True,
        'properties': {
            'payment_id': {'type': 'string', 'format': 'uuid'},
            'payment_reference': {'type': 'string'},
            'base_amount': {'type': 'string'},
        }
    })
    def get_payment(self, obj):
        payment_map = self.context.get('payment_map', {})
        payment = payment_map.get(obj.id)
        if not payment:
            return None

        base_amount = payment.base_amount
        amount_value = None
        if base_amount is not None:
            amount_value = str(getattr(base_amount, 'amount', base_amount))

        return {
            'payment_id': str(payment.payment_id),
            'payment_reference': payment.payment_reference,
            'base_amount': amount_value,
        }


class EventSponsorCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for EventSponsor."""
    
    class Meta:
        model = EventSponsor
        fields = ('name', 'description', 'organisation', 'event', 'package', 'chapter_location')
    
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

    def validate(self, attrs):
        event = attrs.get('event') or getattr(self.instance, 'event', None)
        package = attrs.get('package') if 'package' in attrs else getattr(self.instance, 'package', None)

        if package and event and package.event_id != event.id:
            raise serializers.ValidationError({
                'package': "Selected package must belong to the same event.",
            })

        return attrs

from apps.events.models import Event
class EventSponsorCheckoutSerializer(serializers.Serializer):
    """Payload serializer for sponsor checkout action."""

    # event_id must be a UUID string (the Event.event_id field) — NOT url_safe_title.
    # Optional when invite_token is provided (event is derived from the invite server-side).
    event_id = serializers.UUIDField(required=False)
    package_id = serializers.UUIDField(required=True)
    payment_method_id = serializers.IntegerField(required=True)
    organisation_id = serializers.IntegerField(required=False)
    # Used to create an Organisation on-the-fly when invite has no pre-linked organisation.
    organisation_name = serializers.CharField(required=False, allow_blank=True)
    invite_token = serializers.UUIDField(required=False)
    chapter_location = serializers.IntegerField(required=False)
    name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get('invite_token') and not attrs.get('organisation_id'):
            raise serializers.ValidationError({
                'organisation_id': 'organisation_id is required when invite_token is not provided.'
            })
        return attrs


class SponsorshipPaymentTimelineItemSerializer(serializers.Serializer):
    """Single sponsorship payment timeline entry."""

    payment_id = serializers.UUIDField(read_only=True)
    payment_reference = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    amount = serializers.CharField(read_only=True)
    currency = serializers.CharField(read_only=True)
    method_type = serializers.CharField(read_only=True, allow_null=True)
    method_title = serializers.CharField(read_only=True, allow_null=True)
    method_provided_details = serializers.JSONField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)#
    bank_transfer_reference = serializers.CharField(read_only=True, allow_null=True)

class SponsorshipPaymentHistorySerializer(serializers.Serializer):
    """Organisation sponsorship payment history grouped by selected event."""

    event_id = serializers.UUIDField(read_only=True)
    event_title = serializers.CharField(read_only=True)
    organisation_id = serializers.IntegerField(read_only=True)
    organisation_title = serializers.CharField(read_only=True)
    summary = serializers.DictField(read_only=True)
    timeline = SponsorshipPaymentTimelineItemSerializer(many=True, read_only=True)


# ============================================================================
# EVENT SPONSOR PACKAGE SERIALIZERS
# ============================================================================

class EventSponsorPackageListSerializer(serializers.ModelSerializer):
    """List serializer for EventSponsorPackage with PayableModel support."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    base_amount = MoneyField(max_digits=14, decimal_places=2, read_only=True)
    modified_amount = serializers.SerializerMethodField(help_text="Amount after percentage modifier")
    has_payment = serializers.SerializerMethodField()
    sponsors_count = serializers.SerializerMethodField()
    
    class Meta:
        model = EventSponsorPackage
        fields = (
            'id', 'package_id', 'event', 'event_name',
            'package_name', 'package_description', 'base_amount', 'base_amount_currency',
            'percentage_modifier', 'modified_amount', 'active', 'tier',
            'has_payment', 'sponsors_count',
            'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'package_id', 'added_at', 'updated_at')
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

    @extend_schema_field(OpenApiTypes.INT)
    def get_sponsors_count(self, obj) -> int:
        return obj.sponsors.count()
    
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
            'self': request.build_absolute_uri(f"/api/organisations/sponsor-packages/{obj.package_id}/"),
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
            'event', 'package_name', 'package_description',
            'base_amount', 'base_amount_currency', 'percentage_modifier', 'active', 'tier'
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
        """Validate package uniqueness constraints with partial updates."""
        event = attrs.get('event')

        if not event and self.instance:
            event = self.instance.event

        tier = attrs.get('tier', getattr(self.instance, 'tier', None))
        package_name = attrs.get('package_name', getattr(self.instance, 'package_name', None))

        if event and tier is not None:
            qs = EventSponsorPackage.objects.filter(event=event, tier=tier)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    'tier': "A package with this tier already exists for the event.",
                })

        if event and package_name:
            qs = EventSponsorPackage.objects.filter(event=event, package_name=package_name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    'package_name': "A package with this name already exists for the event.",
                })
        
        return attrs


class EventSponsorInviteListSerializer(serializers.ModelSerializer):
    """List serializer for EventSponsorInvite."""

    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True, allow_null=True)
    is_valid = serializers.SerializerMethodField()

    class Meta:
        model = EventSponsorInvite
        fields = (
            'invite_id', 'event', 'event_name', 'email', 'token',
            'organisation', 'organisation_name', 'chapter_location',
            'accepted', 'declined', 'is_valid',
            'sent_at', 'responded_at', '_links'
        )
        read_only_fields = ('invite_id', 'token', 'accepted', 'declined', 'sent_at', 'responded_at')

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_valid(self, obj) -> bool:
        return obj.is_valid

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}

        links = {
            'self': request.build_absolute_uri(f"/api/organisations/sponsor-invites/{obj.invite_id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
        }

        if obj.organisation_id:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/list/{obj.organisation.url_safe_title}/"
            )

        return links


class EventSponsorInviteDetailSerializer(EventSponsorInviteListSerializer):
    """Detail serializer for EventSponsorInvite."""

    class Meta(EventSponsorInviteListSerializer.Meta):
        fields = EventSponsorInviteListSerializer.Meta.fields


class EventSponsorInviteCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/update serializer for EventSponsorInvite."""

    class Meta:
        model = EventSponsorInvite
        fields = ('event', 'email', 'organisation', 'chapter_location', 'accepted', 'declined')
        read_only_fields = ('accepted', 'declined')

    def validate(self, attrs):
        accepted = attrs.get('accepted', getattr(self.instance, 'accepted', False))
        declined = attrs.get('declined', getattr(self.instance, 'declined', False))
        if accepted and declined:
            raise serializers.ValidationError("Invite cannot be both accepted and declined.")

        event = attrs.get('event', getattr(self.instance, 'event', None))
        organisation = attrs.get('organisation', getattr(self.instance, 'organisation', None))
        if organisation and event and organisation.involvements.filter(event=event).exists() is False:
            # A sponsor can still be invited even without event involvement; keep this permissive.
            pass

        return attrs


# ============================================================================
# LEADER SERIALIZERS
# ============================================================================


LOCATION_MODEL_BY_TYPE = {
    LeaderLocationType.COUNTRY: CountryLocation,
    LeaderLocationType.CLUSTER: ClusterLocation,
    LeaderLocationType.CHAPTER: ChapterLocation,
    LeaderLocationType.AREA: AreaLocation,
}


def _resolve_location(location_type: str, location_id: int):
    model = LOCATION_MODEL_BY_TYPE.get(location_type)
    if not model:
        return None
    return model.objects.filter(pk=location_id).first()


def _user_is_eligible_leader_for_org(*, user, organisation) -> bool:
    if OrganisationControl.objects.filter(organisation=organisation, user=user).exists():
        return True
    if not user:
        raise ValueError("User must be provided for eligibility check.")
    
    return UserOrganisationMembership.objects.filter(
        organisation=organisation,
        user=user,
        verified_at__isnull=False,
    ).exists()


class LeaderListSerializer(serializers.ModelSerializer):
    """List serializer for Leader with typed location fields."""

    _links = serializers.SerializerMethodField()
    user_name = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    location_name = serializers.SerializerMethodField(help_text="Name of the assigned location")
    location_type = serializers.SerializerMethodField(help_text="Type of location (country, cluster, chapter, area)")
    location_id = serializers.SerializerMethodField(help_text="ID of the location")

    class Meta:
        model = Leader
        fields = (
            'id', 'user', 'user_name', 'user_email',
            'organisation', 'organisation_name',
            'location_type', 'location_id', 'location_name',
            'notes', 'added_by', 'added_by_name',
            'added_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'added_at', 'updated_at')
        extra_kwargs = {
            'added_at': {'default': None},
            'updated_at': {'default': None},
        }

    @extend_schema_field(OpenApiTypes.STR)
    def get_location_name(self, obj) -> str:
        if obj.location_name:
            return obj.location_name
        return "Unknown"

    @extend_schema_field(OpenApiTypes.STR)
    def get_location_type(self, obj) -> str:
        return obj.location_type or "unknown"

    @extend_schema_field(OpenApiTypes.INT)
    def get_location_id(self, obj) -> Optional[int]:
        return obj.location_id

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'user': {'type': 'string', 'format': 'uri'},
            'organisation': {'type': 'string', 'format': 'uri'},
            'location': {'type': 'string', 'format': 'uri'},
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

        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/list/{obj.organisation.url_safe_title}/"
            )

        if obj.authority_object and obj.target_type:
            if obj.location_type == LeaderLocationType.COUNTRY:
                links['location'] = request.build_absolute_uri(f"/api/locations/countries/{obj.location_id}/")
            elif obj.location_type == LeaderLocationType.CLUSTER:
                links['location'] = request.build_absolute_uri(f"/api/locations/clusters/{obj.location_id}/")
            elif obj.location_type == LeaderLocationType.CHAPTER:
                links['location'] = request.build_absolute_uri(f"/api/locations/chapters/{obj.location_id}/")
            elif obj.location_type == LeaderLocationType.AREA:
                links['location'] = request.build_absolute_uri(f"/api/locations/areas/{obj.location_id}/")

        return links


class LeaderDetailSerializer(LeaderListSerializer):
    """Detailed serializer for Leader."""

    class Meta(LeaderListSerializer.Meta):
        fields = LeaderListSerializer.Meta.fields


class LeaderCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for Leader with typed location fields."""

    organisation = serializers.PrimaryKeyRelatedField(
        queryset=Organisation.objects.all(),
        required=True,
        help_text="The organisation this leader belongs to",
    )
    location_type = serializers.ChoiceField(
        choices=LeaderLocationType.choices,
        required=False,
        help_text="Type of location this leader is assigned to",
    )
    location_id = serializers.IntegerField(
        write_only=True,
        required=False,
        min_value=1,
        help_text="Numeric ID of the location this leader is assigned to",
    )
    target_type = serializers.CharField(write_only=True, required=False, help_text="Deprecated compatibility field")
    target_id = serializers.IntegerField(write_only=True, required=False, help_text="Deprecated compatibility field")

    class Meta:
        model = Leader
        fields = (
            'user', 'organisation', 'location_type', 'location_id',
            'target_type', 'target_id', 'notes',
        )

    def validate(self, attrs):
        user = attrs.get('user')
        organisation = attrs.get('organisation')

        if not organisation:
            raise serializers.ValidationError({
                "organisation": "Organisation is required for all leaders."
            })

        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            if not (request.user.is_superuser or request.user.is_staff):
                if not OrganisationControl.objects.filter(
                    organisation=organisation,
                    user=request.user,
                ).exists():
                    raise serializers.ValidationError({
                        "organisation": "You must control this organisation to assign leaders."
                    })

        if not _user_is_eligible_leader_for_org(user=user, organisation=organisation):
            raise serializers.ValidationError({
                "user": "User must be a verified member or controller of this organisation."
            })

        location_type = attrs.get('location_type')
        location_id = attrs.get('location_id')

        legacy_target_type = attrs.get('target_type')
        legacy_target_id = attrs.get('target_id')
        if (not location_type or not location_id) and legacy_target_type and legacy_target_id:
            mapped = Leader._model_name_to_location_type(str(legacy_target_type).lower())
            if mapped:
                location_type = mapped
                location_id = legacy_target_id
                attrs['location_type'] = location_type
                attrs['location_id'] = location_id

        if not self.instance and (not location_type or not location_id):
            raise serializers.ValidationError({
                "location_type": "location_type is required.",
                "location_id": "location_id is required.",
            })

        if location_type and location_id:
            location_obj = _resolve_location(location_type, location_id)
            if not location_obj:
                raise serializers.ValidationError({
                    "location_id": "Location not found for the provided location_type.",
                })

            existing = Leader.filter_by_location(
                Leader.objects.filter(user=user, organisation=organisation),
                location_type,
                location_id,
            ).exclude(pk=self.instance.pk if self.instance else None)
            if existing.exists():
                raise serializers.ValidationError({
                    "user": "This user is already a leader for this location in this organisation."
                })

        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        location_type = validated_data.pop('location_type', None)
        location_id = validated_data.pop('location_id', None)
        validated_data.pop('target_type', None)
        validated_data.pop('target_id', None)

        if not location_type or not location_id:
            raise serializers.ValidationError("location_type and location_id are required.")

        leader = Leader(**validated_data)
        leader.set_location_target(location_type, location_id)

        if request and request.user.is_authenticated:
            leader.added_by = request.user

        leader.full_clean()
        leader.save()
        return leader

    def update(self, instance, validated_data):
        # Target location cannot be changed after creation.
        validated_data.pop('location_type', None)
        validated_data.pop('location_id', None)
        validated_data.pop('target_type', None)
        validated_data.pop('target_id', None)
        return super().update(instance, validated_data)


# ============================================================================
# LOCATION LEADER INVITE SERIALIZERS
# ============================================================================


class LocationLeaderInviteListSerializer(serializers.ModelSerializer):
    """List serializer for location leader invites."""

    _links = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    target_user_name = serializers.CharField(source='target_user.username', read_only=True, allow_null=True)
    target_user_email = serializers.EmailField(source='target_user.email', read_only=True, allow_null=True)
    invited_by_name = serializers.CharField(source='invited_by.username', read_only=True, allow_null=True)
    is_valid = serializers.BooleanField(read_only=True)
    location_name = serializers.SerializerMethodField(help_text="Name of location")

    class Meta:
        model = LocationLeaderInvite
        fields = (
            'id', 'organisation', 'organisation_name',
            'target_user', 'target_user_name', 'target_user_email',
            'invited_by', 'invited_by_name',
            'location_type', 'location_id', 'location_name',
            'notes', 'accepted', 'accepted_at', 'is_active', 'is_valid',
            'expires_at', 'added_at', '_links'
        )
        read_only_fields = ('id', 'accepted', 'accepted_at', 'added_at')

    @extend_schema_field(OpenApiTypes.STR)
    def get_location_name(self, obj) -> str:
        location = _resolve_location(obj.location_type, obj.location_id)
        if not location:
            return "Unknown"
        return str(location)

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
            'self': request.build_absolute_uri(f"/api/organisations/leader-invites/{obj.id}/"),
            'organisation': request.build_absolute_uri(f"/api/organisations/list/{obj.organisation.url_safe_title}/"),
        }

        if obj.target_user:
            links['target_user'] = request.build_absolute_uri(f"/api/users/{obj.target_user.id}/")

        if obj.is_valid and not obj.accepted:
            links['accept'] = request.build_absolute_uri(
                f"/api/organisations/leader-invites/{obj.id}/accept/"
            )

        return links


class LocationLeaderInviteDetailSerializer(LocationLeaderInviteListSerializer):
    """Detailed serializer for location leader invites."""

    class Meta(LocationLeaderInviteListSerializer.Meta):
        fields = LocationLeaderInviteListSerializer.Meta.fields


class LocationLeaderInviteCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/update serializer for location leader invites."""

    class Meta:
        model = LocationLeaderInvite
        fields = (
            'organisation', 'target_user', 'location_type',
            'location_id', 'notes', 'expires_at', 'is_active',
        )

    def validate_expires_at(self, value):
        if value and value < timezone.now():
            raise serializers.ValidationError("Expiry date must be in the future.")
        return value

    def validate(self, attrs):
        organisation = attrs.get('organisation')
        target_user = attrs.get('target_user')
        location_type = attrs.get('location_type')
        location_id = attrs.get('location_id')

        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            if not (request.user.is_superuser or request.user.is_staff):
                if not OrganisationControl.objects.filter(
                    organisation=organisation,
                    user=request.user,
                ).exists():
                    raise serializers.ValidationError({
                        "organisation": "You must control this organisation to invite leaders."
                    })

        if not _resolve_location(location_type, location_id):
            raise serializers.ValidationError({
                "location_id": "Location not found for the provided location_type."
            })

        if not _user_is_eligible_leader_for_org(user=target_user, organisation=organisation):
            raise serializers.ValidationError({
                "target_user": "User must be a verified member or controller of this organisation."
            })

        existing_leader = Leader.filter_by_location(
            Leader.objects.filter(user=target_user, organisation=organisation),
            location_type,
            location_id,
        )
        if existing_leader.exists():
            raise serializers.ValidationError({
                "target_user": "This user is already a leader for this location in this organisation."
            })

        existing_invite = LocationLeaderInvite.objects.filter(
            organisation=organisation,
            target_user=target_user,
            location_type=location_type,
            location_id=location_id,
            is_active=True,
            accepted=False,
        )
        if self.instance:
            existing_invite = existing_invite.exclude(pk=self.instance.pk)
        if existing_invite.exists():
            raise serializers.ValidationError({
                "target_user": "An active invite already exists for this user and location."
            })

        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['invited_by'] = request.user
        return super().create(validated_data)


# ============================================================================
# LEADER PERMISSION SERIALIZERS
# ============================================================================


class LeaderPermissionSerializer(serializers.ModelSerializer):
    """Read serializer for LeaderPermission with nested leader context."""

    leader_user = serializers.CharField(source='leader.user.username', read_only=True)
    leader_user_id = serializers.IntegerField(source='leader.user.id', read_only=True)
    organisation = serializers.CharField(source='leader.organisation.title', read_only=True, allow_null=True)
    organisation_url_safe_title = serializers.CharField(
        source='leader.organisation.url_safe_title', read_only=True, allow_null=True
    )

    class Meta:
        model = LeaderPermission
        fields = (
            'id',
            'leader',
            'leader_user',
            'leader_user_id',
            'organisation',
            'organisation_url_safe_title',
            'permission_code',
            'description',
            'allow_create',
            'allow_read',
            'allow_update',
            'allow_delete',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class LeaderPermissionCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/update serializer for LeaderPermission."""

    class Meta:
        model = LeaderPermission
        fields = (
            'leader',
            'permission_code',
            'description',
            'allow_create',
            'allow_read',
            'allow_update',
            'allow_delete',
        )

    def validate(self, attrs):
        leader = attrs.get('leader', getattr(self.instance, 'leader', None))
        permission_code = attrs.get('permission_code', getattr(self.instance, 'permission_code', None))
        qs = LeaderPermission.objects.filter(leader=leader, permission_code=permission_code)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'permission_code': 'This permission code is already assigned to this leader.'}
            )
        return attrs


# ============================================================================
# ORGANISATION EVENT POLICY SERIALIZERS
# ============================================================================


class OrganisationEventPolicySerializer(serializers.ModelSerializer):
    """Serializer for OrganisationEventPolicy — used for both read and update."""

    organisation_title = serializers.CharField(source='organisation.title', read_only=True)
    organisation_url_safe_title = serializers.CharField(
        source='organisation.url_safe_title', read_only=True
    )

    class Meta:
        model = OrganisationEventPolicy
        fields = (
            'id',
            'organisation',
            'organisation_title',
            'organisation_url_safe_title',
            'allow_external_events',
            'allow_attendee_deletions',
            'allow_workshops',
            'allow_product_releases',
            'allow_sponsors',
            'require_long_description',
            'require_short_description',
            'require_landing_image',
            'product_release_must_be_approved_by_organisation',
            'must_be_approved_by_organisation',
            'max_attendees_per_event',
            'max_events_per_organiser',
            'card_payments_are_allowed',
            'bank_transfers_are_allowed',
            'max_package_price',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'organisation', 'organisation_title', 'organisation_url_safe_title', 'created_at', 'updated_at')


# ============================================================================
# ORGANISATION EVENT TYPE POLICY RESTRICTION SERIALIZERS
# ============================================================================


class OrganisationEventTypePolicyRestrictionListSerializer(serializers.ModelSerializer):
    """List serializer for OrganisationEventTypePolicyRestriction."""

    organisation_title = serializers.CharField(source='organisation.title', read_only=True)
    organisation_url_safe_title = serializers.CharField(
        source='organisation.url_safe_title', read_only=True
    )
    event_type_name = serializers.CharField(source='event_type.name', read_only=True)

    class Meta:
        model = OrganisationEventTypePolicyRestriction
        fields = (
            'id',
            'organisation',
            'organisation_title',
            'organisation_url_safe_title',
            'event_type',
            'event_type_name',
            'is_allowed',
            'requires_approval',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class OrganisationEventTypePolicyRestrictionDetailSerializer(
    OrganisationEventTypePolicyRestrictionListSerializer
):
    """Detail serializer for OrganisationEventTypePolicyRestriction — identical to list."""

    class Meta(OrganisationEventTypePolicyRestrictionListSerializer.Meta):
        pass


class OrganisationEventTypePolicyRestrictionCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/update serializer for OrganisationEventTypePolicyRestriction."""

    class Meta:
        model = OrganisationEventTypePolicyRestriction
        fields = (
            'organisation',
            'event_type',
            'is_allowed',
            'requires_approval',
        )

    def validate(self, attrs):
        organisation = attrs.get('organisation', getattr(self.instance, 'organisation', None))
        event_type = attrs.get('event_type', getattr(self.instance, 'event_type', None))
        qs = OrganisationEventTypePolicyRestriction.objects.filter(
            organisation=organisation, event_type=event_type
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'event_type': 'A restriction for this event type already exists for this organisation.'}
            )
        return attrs
