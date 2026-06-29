"""
Production-grade filtersets for the organisations app.

Provides comprehensive filtering capabilities for organisation models with
advanced querying options including full-text search, date ranges,
and complex field filtering.

FilterSets:
    - OrganisationFilterSet: Advanced organisation filtering with search
    - OrganisationContactFilterSet: Filter contacts by organisation
    - OrganisationControlFilterSet: Filter controls by organisation/user
    - UserOrganisationMembershipFilterSet: Filter memberships with verification status
    - OrganisationAcceptanceCodeFilterSet: Filter codes by validity and usage
    - OrganisationInviteFilterSet: Filter invites by status
    - InvolvedEventOrganisationFilterSet: Filter by role and event
    - EventSponsorFilterSet: Filter sponsors by organisation/event
    - EventSponsorPackageFilterSet: Filter packages by sponsor/event
    - LeaderFilterSet: Filter leaders by organisation

Author: AMDG Platform Team
Version: 1.0.0
"""
from django_filters import rest_framework as filters
from django.db.models import Q, F
from django.utils import timezone
from django.db import models

from apps.organisations.models import (
    Organisation, OrganisationContact, OrganisationControl,
    UserOrganisationMembership, OrganisationAcceptanceCode, OrganisationInvite,
    InvolvedEventOrganisation, InvolvedOrganisationRoleChoices,
    EventSponsor, EventSponsorPackage, EventSponsorInvite,
    Leader, LeaderLocationType, LocationLeaderInvite,
    LeaderPermission, OrganisationEventTypePolicyRestriction,
)

from apps.common.models.verification import VerificationStatus as OrganisationSponsorVerificationStatus


def _resolve_organisation_identifier(value):
    if not value:
        return None

    try:
        organisation_id = int(value)
    except (TypeError, ValueError):
        organisation_id = None

    if organisation_id is not None:
        return Organisation.objects.filter(pk=organisation_id).first()

    return Organisation.objects.filter(url_safe_title=value).first()


def _filter_by_organisation_identifier(queryset, relation_name, value):
    organisation = _resolve_organisation_identifier(value)
    if not organisation:
        return queryset.none()
    return queryset.filter(**{relation_name: organisation})


class OrganisationFilterSet(filters.FilterSet):
    """
    Advanced filterset for Organisation model.
    
    Supports filtering by:
    - Title and description search
    - Verification requirements
    - Date ranges (created, updated)
    - Event involvement
    - Member/controller lookup
    
    Example queries:
        ?search=community&required_acceptance_code=true
        ?created_after=2025-01-01
        ?has_event=123
    """
    
    # Search filter
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search in title and description"
    )
    
    # Verification filters
    required_acceptance_code = filters.BooleanFilter(
        field_name='required_acceptance_code',
        help_text="Filter by whether acceptance code is required"
    )
    requires_manual_verification = filters.BooleanFilter(
        field_name='requires_manual_verification',
        help_text="Filter by whether manual verification is required"
    )
    
    # Date range filters
    created_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter organisations created after this date (ISO 8601 format)"
    )
    created_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter organisations created before this date"
    )
    
    updated_after = filters.DateTimeFilter(
        field_name='updated_at',
        lookup_expr='gte',
        help_text="Filter organisations updated after this date"
    )
    updated_before = filters.DateTimeFilter(
        field_name='updated_at',
        lookup_expr='lte',
        help_text="Filter organisations updated before this date"
    )
    
    # Relationship filters
    has_event = filters.NumberFilter(
        method='filter_has_event',
        help_text="Filter organisations involved in specific event (by event ID)"
    )
    
    has_member = filters.NumberFilter(
        method='filter_has_member',
        help_text="Filter organisations with specific member (by user ID)"
    )
    
    has_controller = filters.NumberFilter(
        method='filter_has_controller',
        help_text="Filter organisations with specific controller (by user ID)"
    )
    
    class Meta:
        model = Organisation
        fields = [
            'required_acceptance_code', 'requires_manual_verification',
            'created_by'
        ]
    
    def filter_search(self, queryset, name, value):
        """Search in title and description."""
        if not value:
            return queryset
        return queryset.filter(
            Q(title__icontains=value) | Q(description__icontains=value)
        )
    
    def filter_has_event(self, queryset, name, value):
        """Filter organisations involved in specific event."""
        if not value:
            return queryset
        return queryset.filter(involvements__event__id=value).distinct()
    
    def filter_has_member(self, queryset, name, value):
        """Filter organisations with specific member."""
        if not value:
            return queryset
        return queryset.filter(memberships__user__id=value).distinct()
    
    def filter_has_controller(self, queryset, name, value):
        """Filter organisations with specific controller."""
        if not value:
            return queryset
        return queryset.filter(controllers__user__id=value).distinct()


class OrganisationContactFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationContact model.
    
    Supports filtering by:
    - Organisation
    - Email/name search
    - Label
    """
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search in name, email, and label"
    )
    
    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )
    
    label = filters.CharFilter(
        field_name='label',
        lookup_expr='icontains',
        help_text="Filter by contact label"
    )
    
    class Meta:
        model = OrganisationContact
        fields = ['organisation', 'label']
    
    def filter_search(self, queryset, name, value):
        """Search in name, email, and label."""
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) |
            Q(email__icontains=value) |
            Q(label__icontains=value)
        )

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class OrganisationControlFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationControl model.
    
    Supports filtering by:
    - Organisation
    - User
    - Added by
    - Date ranges
    """
    
    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )
    
    user = filters.NumberFilter(
        field_name='user',
        help_text="Filter by user ID"
    )
    
    added_by = filters.NumberFilter(
        field_name='added_by',
        help_text="Filter by who added the control"
    )
    
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter controls added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter controls added before this date"
    )
    
    class Meta:
        model = OrganisationControl
        fields = ['organisation', 'user', 'added_by']

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class UserOrganisationMembershipFilterSet(filters.FilterSet):
    """
    Filterset for UserOrganisationMembership model.
    
    Supports filtering by:
    - Organisation
    - User
    - Verification status
    - Date ranges
    """
    
    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )
    
    user = filters.NumberFilter(
        field_name='user',
        help_text="Filter by user ID"
    )
    
    is_verified = filters.BooleanFilter(
        method='filter_is_verified',
        help_text="Filter by verification status"
    )
    
    requires_verification = filters.BooleanFilter(
        method='filter_requires_verification',
        help_text="Filter by whether verification is required"
    )
    
    verified_after = filters.DateTimeFilter(
        field_name='verified_at',
        lookup_expr='gte',
        help_text="Filter memberships verified after this date"
    )
    verified_before = filters.DateTimeFilter(
        field_name='verified_at',
        lookup_expr='lte',
        help_text="Filter memberships verified before this date"
    )
    
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter memberships added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter memberships added before this date"
    )
    
    class Meta:
        model = UserOrganisationMembership
        fields = ['organisation', 'user', 'added_by']
    
    def filter_is_verified(self, queryset, name, value):
        """Filter by verification status."""
        if value:
            return queryset.filter(verified_at__isnull=False)
        return queryset.filter(verified_at__isnull=True)
    
    def filter_requires_verification(self, queryset, name, value):
        """Filter by whether organisation requires verification."""
        if value:
            return queryset.filter(organisation__requires_manual_verification=True)
        return queryset.filter(organisation__requires_manual_verification=False)

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class OrganisationAcceptanceCodeFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationAcceptanceCode model.
    
    Supports filtering by:
    - Organisation
    - Validity status
    - Active status
    - Usage
    """
    
    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )
    
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )
    
    is_valid = filters.BooleanFilter(
        method='filter_is_valid',
        help_text="Filter by validity (active, not expired, not max uses)"
    )
    
    is_single_use = filters.BooleanFilter(
        method='filter_is_single_use',
        help_text="Filter single-use codes"
    )
    
    has_remaining_uses = filters.BooleanFilter(
        method='filter_has_remaining_uses',
        help_text="Filter codes with remaining uses"
    )
    
    expires_after = filters.DateTimeFilter(
        field_name='expires_at',
        lookup_expr='gte',
        help_text="Filter codes expiring after this date"
    )
    expires_before = filters.DateTimeFilter(
        field_name='expires_at',
        lookup_expr='lte',
        help_text="Filter codes expiring before this date"
    )
    
    class Meta:
        model = OrganisationAcceptanceCode
        fields = ['organisation', 'is_active', 'added_by']
    
    def filter_is_valid(self, queryset, name, value):
        """Filter by validity status."""
        now = timezone.now()
        if value:
            return queryset.filter(
                is_active=True,
                uses__lt=models.F('max_uses')
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gte=now)
            )
        return queryset.exclude(
            is_active=True,
            uses__lt=models.F('max_uses')
        ).exclude(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        )
    
    def filter_is_single_use(self, queryset, name, value):
        """Filter single-use codes."""
        if value:
            return queryset.filter(max_uses=1)
        return queryset.exclude(max_uses=1)
    
    def filter_has_remaining_uses(self, queryset, name, value):
        """Filter codes with remaining uses."""
        from django.db.models import F
        if value:
            return queryset.filter(uses__lt=F('max_uses'))
        return queryset.filter(uses__gte=F('max_uses'))

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class OrganisationInviteFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationInvite model.
    
    Supports filtering by:
    - Organisation
    - Target user
    - Acceptance status
    - Validity
    """
    
    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )
    
    target_user = filters.NumberFilter(
        field_name='target_user',
        help_text="Filter by target user ID"
    )
    
    invited_by = filters.NumberFilter(
        field_name='invited_by',
        help_text="Filter by who sent the invite"
    )
    
    accepted = filters.BooleanFilter(
        field_name='accepted',
        help_text="Filter by acceptance status"
    )
    
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )
    
    is_valid = filters.BooleanFilter(
        method='filter_is_valid',
        help_text="Filter by validity (active, not accepted, not expired)"
    )
    
    expires_after = filters.DateTimeFilter(
        field_name='expires_at',
        lookup_expr='gte',
        help_text="Filter invites expiring after this date"
    )
    expires_before = filters.DateTimeFilter(
        field_name='expires_at',
        lookup_expr='lte',
        help_text="Filter invites expiring before this date"
    )
    
    class Meta:
        model = OrganisationInvite
        fields = ['organisation', 'target_user', 'invited_by', 'accepted', 'is_active']
    
    def filter_is_valid(self, queryset, name, value):
        """Filter by validity status."""
        now = timezone.now()
        if value:
            return queryset.filter(
                is_active=True,
                accepted=False
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gte=now)
            )
        return queryset.exclude(
            is_active=True,
            accepted=False
        ).exclude(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        )

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class InvolvedEventOrganisationFilterSet(filters.FilterSet):
    """
    Filterset for InvolvedEventOrganisation model.
    
    Supports filtering by:
    - Organisation
    - Event
    - Role
    """
    
    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )
    
    event = filters.NumberFilter(
        field_name='event',
        help_text="Filter by event ID"
    )
    
    role = filters.MultipleChoiceFilter(
        field_name='role',
        choices=InvolvedOrganisationRoleChoices.choices,
        help_text="Filter by role (can specify multiple)"
    )
    
    added_by = filters.NumberFilter(
        field_name='added_by',
        help_text="Filter by who added the involvement"
    )
    
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter involvements added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter involvements added before this date"
    )
    
    class Meta:
        model = InvolvedEventOrganisation
        fields = ['organisation', 'event', 'role', 'added_by']

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class EventSponsorFilterSet(filters.FilterSet):
    """
    Filterset for EventSponsor model.
    
    Supports filtering by:
    - Organisation
    - Event
    - Name search
    """
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search in sponsor name and description"
    )

    organisation_id = filters.CharFilter(
        method='filter_organisation_id',
        help_text="Filter by organisation id or url_safe_title"
    )

    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )

    event = filters.CharFilter(
        field_name='event__url_safe_title',
        help_text="Filter by event URL-safe title"
    )

    package_id = filters.UUIDFilter(
        field_name='package__package_id',
        help_text="Filter by selected package UUID"
    )


    chapter_location_id = filters.NumberFilter(
        field_name='chapter_location__id',
        help_text="Filter by chapter location ID"
    )
    
    added_by = filters.NumberFilter(
        field_name='added_by',
        help_text="Filter by who added the sponsor"
    )

    verification_status = filters.ChoiceFilter(
        field_name='verification_status',
        choices=OrganisationSponsorVerificationStatus.choices,
        help_text="Filter by verification status"
    )

    processed = filters.BooleanFilter(
        method='filter_processed',
        help_text="Filter by whether sponsorship has been processed"
    )
    
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter sponsors added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter sponsors added before this date"
    )
    
    class Meta:
        model = EventSponsor
        fields = ['organisation_id', 'event_id', 'event', 'package_id', 'added_by']
    
    def filter_search(self, queryset, name, value):
        """Search in name and description."""
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )
    
    def filter_processed(self, queryset, name, value):
        """Filter by whether sponsorship has been processed."""
        if value:
            return queryset.filter(processed_at__isnull=False)
        return queryset.filter(processed_at__isnull=True)

    def filter_organisation_id(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)



class EventSponsorPackageFilterSet(filters.FilterSet):
    """
    Filterset for EventSponsorPackage model.
    
    Supports filtering by:
    - Sponsor
    - Event
    - Amount ranges
    - Payment status
    """
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search in package name and description"
    )

    event_id = filters.CharFilter(
        field_name='event__url_safe_title',
        help_text="Filter by event URL-safe title"
    )
    
    tier = filters.NumberFilter(
        field_name='tier',
        help_text="Filter by package tier"
    )

    active = filters.BooleanFilter(
        field_name='active',
        help_text="Filter active/inactive sponsorship packages"
    )

    min_amount = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='gte',
        help_text="Minimum package amount"
    )
    max_amount = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='lte',
        help_text="Maximum package amount"
    )
    
    has_payment = filters.BooleanFilter(
        method='filter_has_payment',
        help_text="Filter packages with/without payment"
    )
    
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter packages added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter packages added before this date"
    )
    
    class Meta:
        model = EventSponsorPackage
        fields = ['event_id', 'tier', 'active']
    
    def filter_search(self, queryset, name, value):
        """Search in package name and description."""
        if not value:
            return queryset
        return queryset.filter(
            Q(package_name__icontains=value) |
            Q(package_description__icontains=value)
        )
    
    def filter_has_payment(self, queryset, name, value):
        """Filter packages with/without payment."""
        from django.contrib.contenttypes.models import ContentType
        from apps.payments.models import Payment
        
        ct = ContentType.objects.get_for_model(EventSponsorPackage)
        package_ids_with_payment = Payment.objects.filter(
            target_type=ct
        ).values_list('target_id', flat=True)
        
        if value:
            return queryset.filter(id__in=package_ids_with_payment)
        return queryset.exclude(id__in=package_ids_with_payment)


class EventSponsorInviteFilterSet(filters.FilterSet):
    """Filterset for EventSponsorInvite model."""

    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )

    event = filters.CharFilter(
        field_name='event__url_safe_title',
        help_text="Filter by event URL-safe title"
    )

    organisation_id = filters.CharFilter(
        method='filter_organisation_id',
        help_text="Filter by organisation id or url_safe_title"
    )

    email = filters.CharFilter(
        field_name='email',
        lookup_expr='icontains',
        help_text="Filter by invitee email"
    )

    accepted = filters.BooleanFilter(
        field_name='accepted',
        help_text="Filter accepted invites"
    )

    declined = filters.BooleanFilter(
        field_name='declined',
        help_text="Filter declined invites"
    )

    chapter_location_id = filters.NumberFilter(
        field_name='chapter_location__id',
        help_text="Filter by chapter location ID"
    )

    sent_after = filters.DateTimeFilter(
        field_name='sent_at',
        lookup_expr='gte',
        help_text="Filter invites sent after this date"
    )

    sent_before = filters.DateTimeFilter(
        field_name='sent_at',
        lookup_expr='lte',
        help_text="Filter invites sent before this date"
    )

    class Meta:
        model = EventSponsorInvite
        fields = ['event_id', 'event', 'organisation_id', 'email', 'accepted', 'declined']

    def filter_organisation_id(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class LeaderFilterSet(filters.FilterSet):
    """Filterset for typed location leaders."""

    user = filters.NumberFilter(
        field_name='user',
        help_text="Filter by user ID"
    )

    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )

    location_type = filters.ChoiceFilter(
        choices=LeaderLocationType.choices,
        method='filter_location_type',
        help_text="Filter by location type"
    )

    location_id = filters.NumberFilter(
        method='filter_location_id',
        help_text="Filter by location ID"
    )

    added_by = filters.NumberFilter(
        field_name='added_by',
        help_text="Filter by who added the leader"
    )

    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter leaders added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter leaders added before this date"
    )

    class Meta:
        model = Leader
        fields = ['user', 'organisation', 'added_by']

    def filter_location_type(self, queryset, name, value):
        if not value:
            return queryset

        model_name = Leader._location_type_to_model_name(value)
        if not model_name:
            return queryset.none()

        from django.contrib.contenttypes.models import ContentType

        try:
            ct = ContentType.objects.get(model=model_name)
        except ContentType.DoesNotExist:
            return queryset.none()
        return queryset.filter(target_type=ct)

    def filter_location_id(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(target_id=value)

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


class LocationLeaderInviteFilterSet(filters.FilterSet):
    """Filterset for location leader invites."""

    organisation = filters.CharFilter(
        method='filter_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )

    target_user = filters.NumberFilter(
        field_name='target_user',
        help_text="Filter by target user ID"
    )

    location_type = filters.ChoiceFilter(
        choices=LeaderLocationType.choices,
        field_name='location_type',
        help_text="Filter by location type"
    )

    location_id = filters.NumberFilter(
        field_name='location_id',
        help_text="Filter by location ID"
    )

    accepted = filters.BooleanFilter(
        field_name='accepted',
        help_text="Filter by accepted status"
    )

    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )

    is_valid = filters.BooleanFilter(
        method='filter_is_valid',
        help_text="Filter by current invite validity"
    )

    class Meta:
        model = LocationLeaderInvite
        fields = ['organisation', 'target_user', 'location_type', 'location_id', 'accepted', 'is_active']

    def filter_is_valid(self, queryset, name, value):
        now = timezone.now()
        valid_filter = models.Q(is_active=True, accepted=False) & (
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

        if value:
            return queryset.filter(valid_filter)
        return queryset.exclude(valid_filter)

    def filter_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)


# ============================================================================
# LEADER PERMISSION FILTERSET
# ============================================================================


class LeaderPermissionFilterSet(filters.FilterSet):
    """
    Filterset for LeaderPermission.

    Filter params (no double-underscore in param names):
        - leader        : integer PK of the Leader record
        - user          : integer PK of the user the leader belongs to
        - organisation  : integer PK, or url_safe_title of the organisation the leader belongs to
        - permission_code: exact match on permission_code
    """

    leader = filters.NumberFilter(
        field_name='leader_id',
        help_text="Filter by leader ID (integer PK)"
    )

    user = filters.NumberFilter(
        method='filter_by_user',
        help_text="Filter by the user ID that the leader record belongs to"
    )

    organisation = filters.CharFilter(
        method='filter_by_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )

    permission_code = filters.CharFilter(
        field_name='permission_code',
        lookup_expr='exact',
        help_text="Filter by exact permission code"
    )

    class Meta:
        model = LeaderPermission
        fields = ['leader', 'user', 'organisation', 'permission_code']

    def filter_by_user(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(leader__user__id=value)

    def filter_by_organisation(self, queryset, name, value):
        organisation = _resolve_organisation_identifier(value)
        if not organisation:
            return queryset.none()
        return queryset.filter(leader__organisation=organisation)


# ============================================================================
# ORGANISATION EVENT TYPE POLICY RESTRICTION FILTERSET
# ============================================================================


class OrganisationEventTypePolicyRestrictionFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationEventTypePolicyRestriction.

    Filter params (no double-underscore in param names):
        - organisation    : integer PK, or url_safe_title
        - event_type      : integer PK of the EventType (EventType has no UUID field)
        - is_allowed      : boolean
        - requires_approval: boolean
    """

    organisation = filters.CharFilter(
        method='filter_by_organisation',
        help_text="Filter by organisation id or url_safe_title"
    )

    event_type = filters.NumberFilter(
        field_name='event_type_id',
        help_text="Filter by EventType ID (integer PK)"
    )

    is_allowed = filters.BooleanFilter(
        field_name='is_allowed',
        help_text="Filter by whether the event type is allowed"
    )

    requires_approval = filters.BooleanFilter(
        field_name='requires_approval',
        help_text="Filter by whether approval is required"
    )

    class Meta:
        model = OrganisationEventTypePolicyRestriction
        fields = ['organisation', 'event_type', 'is_allowed', 'requires_approval']

    def filter_by_organisation(self, queryset, name, value):
        return _filter_by_organisation_identifier(queryset, 'organisation', value)
