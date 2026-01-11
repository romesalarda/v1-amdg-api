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
    EventSponsor, EventSponsorPackage,
    Leader
)


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
    
    organisation = filters.NumberFilter(
        field_name='organisation',
        help_text="Filter by organisation ID"
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


class OrganisationControlFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationControl model.
    
    Supports filtering by:
    - Organisation
    - User
    - Added by
    - Date ranges
    """
    
    organisation = filters.NumberFilter(
        field_name='organisation',
        help_text="Filter by organisation ID"
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


class UserOrganisationMembershipFilterSet(filters.FilterSet):
    """
    Filterset for UserOrganisationMembership model.
    
    Supports filtering by:
    - Organisation
    - User
    - Verification status
    - Date ranges
    """
    
    organisation = filters.NumberFilter(
        field_name='organisation',
        help_text="Filter by organisation ID"
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


class OrganisationAcceptanceCodeFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationAcceptanceCode model.
    
    Supports filtering by:
    - Organisation
    - Validity status
    - Active status
    - Usage
    """
    
    organisation = filters.NumberFilter(
        field_name='organisation',
        help_text="Filter by organisation ID"
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


class OrganisationInviteFilterSet(filters.FilterSet):
    """
    Filterset for OrganisationInvite model.
    
    Supports filtering by:
    - Organisation
    - Target user
    - Acceptance status
    - Validity
    """
    
    organisation = filters.NumberFilter(
        field_name='organisation',
        help_text="Filter by organisation ID"
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


class InvolvedEventOrganisationFilterSet(filters.FilterSet):
    """
    Filterset for InvolvedEventOrganisation model.
    
    Supports filtering by:
    - Organisation
    - Event
    - Role
    """
    
    organisation = filters.NumberFilter(
        field_name='organisation',
        help_text="Filter by organisation ID"
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
    
    organisation = filters.NumberFilter(
        field_name='organisation',
        help_text="Filter by organisation ID"
    )
    
    event = filters.NumberFilter(
        field_name='event',
        help_text="Filter by event ID"
    )
    
    added_by = filters.NumberFilter(
        field_name='added_by',
        help_text="Filter by who added the sponsor"
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
        fields = ['organisation', 'event', 'added_by']
    
    def filter_search(self, queryset, name, value):
        """Search in name and description."""
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )


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
    
    sponsor = filters.NumberFilter(
        field_name='sponsor',
        help_text="Filter by sponsor ID"
    )
    
    event = filters.NumberFilter(
        field_name='event',
        help_text="Filter by event ID"
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
        fields = ['sponsor', 'event']
    
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


class LeaderFilterSet(filters.FilterSet):
    """
    Filterset for Leader model (Organisation authority only).
    
    Supports filtering by:
    - User
    - Organisation (via target_id)
    """
    
    user = filters.NumberFilter(
        field_name='user',
        help_text="Filter by user ID"
    )
    
    organisation = filters.NumberFilter(
        method='filter_organisation',
        help_text="Filter by organisation ID"
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
        fields = ['user', 'added_by']
    
    def filter_organisation(self, queryset, name, value):
        """Filter leaders by organisation."""
        from django.contrib.contenttypes.models import ContentType
        
        if not value:
            return queryset
        
        org_ct = ContentType.objects.get_for_model(Organisation)
        return queryset.filter(
            target_type=org_ct,
            target_id=value
        )
