"""
Production-grade filtersets for the payments app.

Provides comprehensive filtering capabilities for payment models with
advanced querying options including date ranges, amount ranges, full-text search,
and complex field filtering.

FilterSets:
    - PaymentFilterSet: Advanced payment filtering with date ranges, status, amounts
    - PaymentMethodFilterSet: Filter payment methods by type, event, activity
    - DiscountFilterSet: Filter discounts by type, target, activity
    - DiscountRuleFilterSet: Filter discount rules by type and discount
    - RefundRequestFilterSet: Filter refunds by status, dates, amounts
    - RefundPolicyFilterSet: Filter refund policies by event and type
    - DonationFilterSet: Filter donations by status and dates
    - PaymentHistoryActionFilterSet: Filter payment history by action type

Author: AMDG Platform Team
Version: 1.0.0
"""
from django_filters import rest_framework as filters
from django.db.models import Q, F
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from uuid import UUID

from apps.payments.models import (
    Payment, PaymentMethod, PaymentStatusChoices, PaymentMethodTypeChoices,
    Discount, DiscountRule, DiscountType, DiscountApplicationChoices, DiscountRuleTypeChoices,
    RefundRequest, RefundPolicy, RefundPolicyTypeChoices,
    Donation, PaymentHistoryAction,
    CreditExpense, CreditExpenseTypeChoices, BankTransferEvidence
)
from apps.common.models import VerificationStatus


class PaymentFilterSet(filters.FilterSet):
    """
    Advanced filterset for Payment model.
    
    Supports filtering by:
    - Status (single or multiple)
    - Date ranges (created, updated)
    - Amount ranges (min/max)
    - User, event, payment method
    - Payment reference search
    - Target type and ID
    
    Example queries:
        ?status=COMPLETED&min_amount=100&max_amount=500
        ?created_after=2025-01-01&event=123
        ?search=PAY123&status__in=COMPLETED,PENDING
    """
    
    # Status filters
    status = filters.MultipleChoiceFilter(
        field_name='status',
        choices=PaymentStatusChoices.choices,
        help_text="Filter by payment status (can specify multiple)"
    )
    status__in = filters.MultipleChoiceFilter(
        field_name='status',
        choices=PaymentStatusChoices.choices,
        help_text="Filter by multiple statuses (comma-separated)"
    )
    
    # Date range filters
    created_after = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text="Filter payments created after this date (ISO 8601 format)"
    )
    created_before = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text="Filter payments created before this date"
    )
    created_date = filters.DateFilter(
        field_name='created_at',
        lookup_expr='date',
        help_text="Filter payments created on specific date (YYYY-MM-DD)"
    )
    
    updated_after = filters.DateTimeFilter(
        field_name='updated_at',
        lookup_expr='gte',
        help_text="Filter payments updated after this date"
    )
    updated_before = filters.DateTimeFilter(
        field_name='updated_at',
        lookup_expr='lte',
        help_text="Filter payments updated before this date"
    )
    
    # Amount range filters (on base_amount)
    min_amount = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='gte',
        help_text="Minimum payment amount (in base currency)"
    )
    max_amount = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='lte',
        help_text="Maximum payment amount"
    )
    amount = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='exact',
        help_text="Exact payment amount"
    )
    
    # Relational filters
    user = filters.NumberFilter(
        field_name='user__id',
        help_text="Filter by user ID"
    )
    user__username = filters.CharFilter(
        field_name='user__username',
        lookup_expr='icontains',
        help_text="Filter by username (case-insensitive partial match)"
    )
    
    event = filters.CharFilter(
        field_name='event__url_safe_title',
        lookup_expr='exact',
        help_text="Filter by event URL-safe title"
    )
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )
    
    method = filters.NumberFilter(
        field_name='method__id',
        help_text="Filter by payment method ID"
    )
    method__method_type = filters.ChoiceFilter(
        field_name='method__method_type',
        choices=PaymentMethodTypeChoices.choices,
        help_text="Filter by payment method type"
    )
    
    # Target filters
    target_type = filters.NumberFilter(
        field_name='target_type__id',
        help_text="Filter by target content type ID"
    )
    target_id = filters.CharFilter(
        field_name='target_id',
        help_text="Filter by target object ID"
    )
    
    # Search filter
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search payment reference, bank reference, or user email"
    )
    
    # Convenience filters
    has_refund = filters.BooleanFilter(
        method='filter_has_refund',
        help_text="Filter payments with/without refund requests"
    )
    
    has_donation = filters.BooleanFilter(
        method='filter_has_donation',
        help_text="Filter payments with/without donations"
    )
    
    is_recent = filters.BooleanFilter(
        method='filter_is_recent',
        help_text="Filter payments created in the last 7 days"
    )

    descriptor = filters.CharFilter(
        method='filter_descriptor',
        help_text="Filter by payment descriptor (e.g., booking, order, ticket, donation, sponsorship)"
    )

    has_bank_transfer_evidence = filters.BooleanFilter(
        method='filter_has_bank_transfer_evidence',
        help_text='Filter bank transfer payments with/without any evidence records',
    )
    has_verified_bank_transfer_evidence = filters.BooleanFilter(
        method='filter_has_verified_bank_transfer_evidence',
        help_text='Filter bank transfer payments with/without verified evidence',
    )
    is_overdue_bank_transfer_evidence = filters.BooleanFilter(
        method='filter_is_overdue_bank_transfer_evidence',
        help_text='Filter bank transfer payments pending evidence beyond overdue_hours (default 72)',
    )
    
    class Meta:
        model = Payment
        fields = []  # All fields defined explicitly above
    
    def filter_search(self, queryset, name, value):
        """Search across payment reference, bank reference, and user email."""
        if not value:
            return queryset
        
        return queryset.filter(
            Q(payment_id__icontains=value) |
            Q(payment_reference__icontains=value) |
            Q(bank_transfer_reference__icontains=value) |
            Q(user__email__icontains=value) |
            Q(user__username__icontains=value)
        )
    
    def filter_descriptor(self, queryset, name, value):
        """Filter by payment descriptor (e.g., booking, order, ticket, donation, sponsorship)."""
        if not value:
            return queryset
        
        value = value.lower()
        if value == "booking":
            return queryset.filter(target_type__model='booking')
        elif value == "order":
            return queryset.filter(target_type__model='order')
        elif value == "ticket":
            return queryset.filter(target_type__model='ticket')
        elif value == "donation":
            return queryset.filter(target_type__model='donation')
        elif value in ["sponsorship", "eventsponsor"]:
            return queryset.filter(target_type__model='eventsponsor')
        
        return queryset.none()
    
    def filter_has_refund(self, queryset, name, value):
        """Filter payments that have refund requests."""
        if value:
            return queryset.filter(refund_requests__isnull=False).distinct()
        else:
            return queryset.filter(refund_requests__isnull=True)
    
    def filter_has_donation(self, queryset, name, value):
        """Filter payments that have donations."""
        if value:
            return queryset.filter(donations__isnull=False).distinct()
        else:
            return queryset.filter(donations__isnull=True)
    
    def filter_is_recent(self, queryset, name, value):
        """Filter payments created in the last 7 days."""
        if value:
            cutoff = timezone.now() - timedelta(days=7)
            return queryset.filter(created_at__gte=cutoff)
        return queryset

    def filter_has_bank_transfer_evidence(self, queryset, name, value):
        bank_transfer_qs = queryset.filter(method__method_type=PaymentMethodTypeChoices.BANK_TRANSFER)
        if value:
            return bank_transfer_qs.filter(bank_transfer_evidence__isnull=False).distinct()
        return bank_transfer_qs.filter(bank_transfer_evidence__isnull=True)

    def filter_has_verified_bank_transfer_evidence(self, queryset, name, value):
        bank_transfer_qs = queryset.filter(method__method_type=PaymentMethodTypeChoices.BANK_TRANSFER)
        if value:
            return bank_transfer_qs.filter(bank_transfer_evidence__verification_status=VerificationStatus.VERIFIED).distinct()
        return bank_transfer_qs.exclude(bank_transfer_evidence__verification_status=VerificationStatus.VERIFIED)

    def filter_is_overdue_bank_transfer_evidence(self, queryset, name, value):
        if not value:
            return queryset

        default_overdue_hours = getattr(settings, 'BANK_TRANSFER_EVIDENCE_OVERDUE_HOURS', 72)
        try:
            overdue_hours = int(self.request.query_params.get('overdue_hours', default_overdue_hours))
        except (TypeError, ValueError):
            overdue_hours = default_overdue_hours

        cutoff = timezone.now() - timedelta(hours=overdue_hours)
        return queryset.filter(
            method__method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            status=PaymentStatusChoices.PENDING,
            created_at__lt=cutoff,
        ).exclude(bank_transfer_evidence__verification_status=VerificationStatus.VERIFIED)


class PaymentMethodFilterSet(filters.FilterSet):
    """
    Filterset for PaymentMethod model.
    
    Supports filtering by:
    - Method type
    - Active status
    - Event
    - Creation date
    - Search by title/code
    """
    
    method_type = filters.MultipleChoiceFilter(
        field_name='method_type',
        choices=PaymentMethodTypeChoices.choices,
        help_text="Filter by payment method type"
    )
    
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter active/inactive payment methods"
    )

    bank_transfer_required_immediately = filters.BooleanFilter(
        field_name='bank_transfer_required_immediately',
        help_text='Filter payment methods that require evidence immediately at checkout',
    )
    
    event = filters.CharFilter(
        field_name='event__url_safe_title',
        lookup_expr='exact',
        help_text="Filter by event URL-safe title"
    )
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )

    created_after = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text="Filter methods created after this date"
    )
    created_before = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text="Filter methods created before this date"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search by title, code, or description"
    )
    
    class Meta:
        model = PaymentMethod
        fields = []
    
    def filter_search(self, queryset, name, value):
        """Search across title, code, and description."""
        if not value:
            return queryset
        
        return queryset.filter(
            Q(title__icontains=value) |
            Q(code__icontains=value) |
            Q(description__icontains=value)
        )


class DiscountFilterSet(filters.FilterSet):
    """
    Filterset for Discount model.
    
    Supports filtering by:
    - Discount type (PERCENTAGE/FIXED)
    - Active status
    - Target type and ID
    - Event (filters by target objects within the event)
    - Creation date
    - Amount/percentage ranges
    """
    
    discount_type = filters.ChoiceFilter(
        field_name='discount_type',
        choices=DiscountType.choices,
        help_text="Filter by discount type"
    )
    
    active = filters.BooleanFilter(
        field_name='active',
        help_text="Filter active/inactive discounts"
    )
    
    target_type = filters.NumberFilter(
        field_name='target_type__id',
        help_text="Filter by target content type ID"
    )
    target_id = filters.NumberFilter(
        field_name='target_id',
        help_text="Filter by target object ID"
    )
    
    # Event filtering - filters discounts by target objects within the event
    event = filters.CharFilter(
        method='filter_by_event',
        help_text="Filter discounts by event URL-safe title (filters target objects within the event)"
    )
    event_id = filters.UUIDFilter(
        method='filter_by_event_uuid',
        help_text="Filter discounts by event UUID"
    )
    
    min_percentage = filters.NumberFilter(
        field_name='percentage',
        lookup_expr='gte',
        help_text="Minimum percentage value"
    )
    max_percentage = filters.NumberFilter(
        field_name='percentage',
        lookup_expr='lte',
        help_text="Maximum percentage value"
    )
    
    min_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='gte',
        help_text="Minimum fixed amount"
    )
    max_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='lte',
        help_text="Maximum fixed amount"
    )
    
    created_after = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text="Filter discounts created after this date"
    )
    created_before = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text="Filter discounts created before this date"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search by name or description"
    )
    
    class Meta:
        model = Discount
        fields = []
    
    def filter_search(self, queryset, name, value):
        """Search across name and description."""
        if not value:
            return queryset
        
        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value)
        )
    
    def filter_by_event(self, queryset, name, value):
        """
        Filter discounts by event URL-safe title.
        Currently supports BookingPackage as the main target type.
        Uses Subquery for optimized database performance.
        """
        if not value:
            return queryset
        
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage
        from django.db.models import OuterRef, Exists
        
        # Get BookingPackages for this event using Subquery pattern
        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        package_subquery = BookingPackage.objects.filter(
            event__url_safe_title=value,
            id=OuterRef('target_id')
        )
        
        # Filter discounts targeting these packages using EXISTS
        return queryset.filter(
            target_type=booking_package_ct
        ).annotate(
            has_matching_package=Exists(package_subquery)
        ).filter(has_matching_package=True)
    
    def filter_by_event_uuid(self, queryset, name, value):
        """
        Filter discounts by event UUID.
        Currently supports BookingPackage as the main target type.
        Uses Subquery for optimized database performance.
        """
        if not value:
            return queryset
        
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage
        from apps.events.models import Event
        from django.db.models import OuterRef, Exists
        
        try:
            event = Event.objects.get(event_id=value)
        except Event.DoesNotExist:
            return queryset.none()
        
        # Get BookingPackages for this event using Subquery pattern
        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        package_subquery = BookingPackage.objects.filter(
            event=event,
            id=OuterRef('target_id')
        )
        
        # Filter discounts targeting these packages using EXISTS
        return queryset.filter(
            target_type=booking_package_ct
        ).annotate(
            has_matching_package=Exists(package_subquery)
        ).filter(has_matching_package=True)


class DiscountRuleFilterSet(filters.FilterSet):
    """
    Filterset for DiscountRule model.
    
    Supports filtering by:
    - Rule type
    - Discount
    - Event (filters by discount's target event)
    - Active status
    - Value matching
    """
    
    rule_type = filters.MultipleChoiceFilter(
        field_name='rule_type',
        choices=DiscountRuleTypeChoices.choices,
        help_text="Filter by rule type"
    )
    
    discount = filters.NumberFilter(
        field_name='discount__id',
        help_text="Filter by discount ID"
    )
    discount__discount_id = filters.UUIDFilter(
        field_name='discount__discount_id',
        help_text="Filter by discount UUID"
    )
    
    # Event filtering - filters rules by discount's target event
    event = filters.NumberFilter(
        method='filter_by_event',
        help_text="Filter rules by event ID"
    )
    event_id = filters.UUIDFilter(
        method='filter_by_event_uuid',
        help_text="Filter rules by event UUID"
    )
    
    active = filters.BooleanFilter(
        field_name='active',
        help_text="Filter active/inactive rules"
    )
    
    value = filters.CharFilter(
        field_name='value',
        lookup_expr='icontains',
        help_text="Filter by rule value (partial match)"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search by name or description"
    )
    
    class Meta:
        model = DiscountRule
        fields = []
    
    def filter_search(self, queryset, name, value):
        """Search across name and description."""
        if not value:
            return queryset
        
        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value)
        )
    
    def filter_by_event(self, queryset, name, value):
        """
        Filter discount rules by event ID.
        Filters based on the event of the discount's target object.
        Uses Subquery for optimized database performance.
        """
        if not value:
            return queryset
        
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage
        from django.db.models import OuterRef, Exists
        
        # Get BookingPackages for this event using Subquery pattern
        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        package_subquery = BookingPackage.objects.filter(
            event_id=value,
            id=OuterRef('discount__target_id')
        )
        
        # Filter rules for discounts targeting these packages using EXISTS
        return queryset.filter(
            discount__target_type=booking_package_ct
        ).annotate(
            has_matching_package=Exists(package_subquery)
        ).filter(has_matching_package=True)
    
    def filter_by_event_uuid(self, queryset, name, value):
        """
        Filter discount rules by event UUID.
        Filters based on the event of the discount's target object.
        Uses Subquery for optimized database performance.
        """
        if not value:
            return queryset
        
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage
        from apps.events.models import Event
        from django.db.models import OuterRef, Exists
        
        try:
            event = Event.objects.get(event_id=value)
        except Event.DoesNotExist:
            return queryset.none()
        
        # Get BookingPackages for this event using Subquery pattern
        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        package_subquery = BookingPackage.objects.filter(
            event=event,
            id=OuterRef('discount__target_id')
        )
        
        # Filter rules for discounts targeting these packages using EXISTS
        return queryset.filter(
            discount__target_type=booking_package_ct
        ).annotate(
            has_matching_package=Exists(package_subquery)
        ).filter(has_matching_package=True)


class RefundRequestFilterSet(filters.FilterSet):
    """
    Filterset for RefundRequest model.
    
    Supports filtering by:
    - Verification status
    - Payment
    - Date ranges
    - Amount ranges
    - Active status
    - Requested by user
    """
    
    verification_status = filters.MultipleChoiceFilter(
        field_name='verification_status',
        choices=VerificationStatus.choices,
        help_text="Filter by verification status"
    )
    
    payment = filters.NumberFilter(
        field_name='payment__id',
        help_text="Filter by payment ID"
    )
    payment__payment_id = filters.UUIDFilter(
        field_name='payment__payment_id',
        help_text="Filter by payment UUID"
    )

    payment_id = filters.UUIDFilter(
        field_name='payment__event__event_id',
        help_text="Filter by event UUID (filters refunds for payments associated with the event)"
    )
    event_id = filters.UUIDFilter(
        field_name='payment__event__event_id',
        help_text="Filter by event UUID (filters refunds for payments associated with the event)"
    )

    event = filters.CharFilter(
        field_name='payment__event__url_safe_title',
        lookup_expr='exact',
        help_text="Filter by event URL-safe title (filters refunds for payments associated with the event)"
    )
    
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter active/inactive refund requests"
    )
    
    requested_after = filters.DateTimeFilter(
        field_name='requested_at',
        lookup_expr='gte',
        help_text="Filter refunds requested after this date"
    )
    requested_before = filters.DateTimeFilter(
        field_name='requested_at',
        lookup_expr='lte',
        help_text="Filter refunds requested before this date"
    )
    
    processed_after = filters.DateTimeFilter(
        field_name='processed_at',
        lookup_expr='gte',
        help_text="Filter refunds processed after this date"
    )
    processed_before = filters.DateTimeFilter(
        field_name='processed_at',
        lookup_expr='lte',
        help_text="Filter refunds processed before this date"
    )
    
    min_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='gte',
        help_text="Minimum refund amount"
    )
    max_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='lte',
        help_text="Maximum refund amount"
    )
    
    requested_by = filters.NumberFilter(
        field_name='requested_by__id',
        help_text="Filter by requesting user ID"
    )
    requested_by__username = filters.CharFilter(
        field_name='requested_by__username',
        lookup_expr='icontains',
        help_text="Filter by requesting username"
    )
    
    verified_by = filters.NumberFilter(
        field_name='verified_by__id',
        help_text="Filter by verifying user ID"
    )
    
    processed_by = filters.NumberFilter(
        field_name='processed_by__id',
        help_text="Filter by processing user ID"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search by tracking reference or reason"
    )
    
    is_pending = filters.BooleanFilter(
        method='filter_is_pending',
        help_text="Filter pending refund requests"
    )
    
    is_full_refund = filters.BooleanFilter(
        method='filter_is_full_refund',
        help_text="Filter full/partial refunds"
    )
    
    class Meta:
        model = RefundRequest
        fields = []
    
    def filter_search(self, queryset, name, value):
        """Search across tracking reference and reason."""
        if not value:
            return queryset
        
        return queryset.filter(
            Q(tracking_reference__icontains=value) |
            Q(reason__icontains=value)
        )
    
    def filter_is_pending(self, queryset, name, value):
        """Filter pending refund requests."""
        if value:
            return queryset.filter(verification_status=VerificationStatus.PENDING)
        return queryset
    
    def filter_is_full_refund(self, queryset, name, value):
        """Filter full vs partial refunds."""
        if value:
            # Full refund: amount equals payment base_amount
            return queryset.filter(amount=F('payment__base_amount'))
        else:
            # Partial refund: amount less than payment base_amount
            return queryset.filter(amount__lt=F('payment__base_amount'))


class RefundPolicyFilterSet(filters.FilterSet):
    """
    Filterset for RefundPolicy model.
    
    Supports filtering by:
    - Policy type
    - Event
    - Refundable days range
    """
    
    policy_type = filters.ChoiceFilter(
        field_name='policy_type',
        choices=RefundPolicyTypeChoices.choices,
        help_text="Filter by refund policy type"
    )
    
    event = filters.NumberFilter(
        field_name='event__id',
        help_text="Filter by event ID"
    )
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )

    min_refundable_days = filters.NumberFilter(
        field_name='refundable_within_days',
        lookup_expr='gte',
        help_text="Minimum refundable days"
    )
    max_refundable_days = filters.NumberFilter(
        field_name='refundable_within_days',
        lookup_expr='lte',
        help_text="Maximum refundable days"
    )
    
    search = filters.CharFilter(
        field_name='notes',
        lookup_expr='icontains',
        help_text="Search policy notes"
    )
    
    class Meta:
        model = RefundPolicy
        fields = []


class DonationFilterSet(filters.FilterSet):
    """
    Filterset for Donation model.
    
    Supports filtering by:
    - Verification status
    - Payment
    - Date ranges
    - Amount ranges
    - Donated by user
    """
    
    verification_status = filters.MultipleChoiceFilter(
        field_name='verification_status',
        choices=VerificationStatus.choices,
        help_text="Filter by verification status"
    )
    
    payment = filters.NumberFilter(
        field_name='payment__id',
        help_text="Filter by payment ID"
    )
    payment__payment_id = filters.UUIDFilter(
        field_name='payment__payment_id',
        help_text="Filter by payment UUID"
    )
    
    donated_after = filters.DateTimeFilter(
        field_name='donated_at',
        lookup_expr='gte',
        help_text="Filter donations after this date"
    )
    donated_before = filters.DateTimeFilter(
        field_name='donated_at',
        lookup_expr='lte',
        help_text="Filter donations before this date"
    )
    
    min_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='gte',
        help_text="Minimum donation amount"
    )
    max_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='lte',
        help_text="Maximum donation amount"
    )
    
    donated_by = filters.NumberFilter(
        field_name='donated_by__id',
        help_text="Filter by donating user ID"
    )
    donated_by__username = filters.CharFilter(
        field_name='donated_by__username',
        lookup_expr='icontains',
        help_text="Filter by donating username"
    )
    
    search = filters.CharFilter(
        field_name='tracking_reference',
        lookup_expr='icontains',
        help_text="Search by tracking reference"
    )
    
    is_pending = filters.BooleanFilter(
        method='filter_is_pending',
        help_text="Filter pending donations"
    )
    
    class Meta:
        model = Donation
        fields = []
    
    def filter_is_pending(self, queryset, name, value):
        """Filter pending donations."""
        if value:
            return queryset.filter(verification_status=VerificationStatus.PENDING)
        return queryset


class CreditExpenseFilterSet(filters.FilterSet):
    """
    Filterset for CreditExpense model.

    Supports filtering by:
    - Verification status
    - Event
    - Expense type
    - Settlement state
    - Creator
    - Amount ranges
    - Search by description and credit reference
    """

    verification_status = filters.MultipleChoiceFilter(
        field_name='verification_status',
        choices=VerificationStatus.choices,
        help_text="Filter by verification status",
    )

    expense_type = filters.MultipleChoiceFilter(
        field_name='expense_type',
        choices=CreditExpenseTypeChoices.choices,
        help_text="Filter by expense type",
    )

    event = filters.NumberFilter(
        field_name='event__id',
        help_text="Filter by event ID",
    )
    event__event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID",
    )

    created_by = filters.NumberFilter(
        field_name='created_by__id',
        help_text="Filter by creator user ID",
    )
    created_by__username = filters.CharFilter(
        field_name='created_by__username',
        lookup_expr='icontains',
        help_text="Filter by creator username",
    )

    is_settled = filters.BooleanFilter(
        field_name='is_settled',
        help_text="Filter by settlement state",
    )

    created_after = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text="Filter credits created after this timestamp",
    )
    created_before = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text="Filter credits created before this timestamp",
    )

    paid_after = filters.DateFilter(
        field_name='paid_date',
        lookup_expr='gte',
        help_text="Filter by paid date on or after this value",
    )
    paid_before = filters.DateFilter(
        field_name='paid_date',
        lookup_expr='lte',
        help_text="Filter by paid date on or before this value",
    )

    min_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='gte',
        help_text="Minimum credit amount",
    )
    max_amount = filters.NumberFilter(
        field_name='amount',
        lookup_expr='lte',
        help_text="Maximum credit amount",
    )

    search = filters.CharFilter(
        method='filter_search',
        help_text="Search description or credit ID",
    )

    class Meta:
        model = CreditExpense
        fields = []

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset

        query = Q(description__icontains=value)

        try:
            query |= Q(credit_id=UUID(value))
        except (ValueError, TypeError):
            pass

        return queryset.filter(query)


class BankTransferEvidenceFilterSet(filters.FilterSet):
    """
    Filterset for BankTransferEvidence model.

    Supports filtering by:
    - Verification status
    - Payment linkage
    - Transfer reference
    - Upload date ranges
    - Expiry date ranges
    - Search by payer or transfer id
    """

    verification_status = filters.MultipleChoiceFilter(
        field_name='verification_status',
        choices=VerificationStatus.choices,
        help_text="Filter by verification status",
    )

    payment = filters.NumberFilter(
        field_name='payment__id',
        help_text="Filter by linked payment ID",
    )
    payment__payment_id = filters.UUIDFilter(
        field_name='payment__payment_id',
        help_text="Filter by linked payment UUID",
    )

    uploaded_after = filters.DateTimeFilter(
        field_name='uploaded_at',
        lookup_expr='gte',
        help_text="Filter evidence uploaded after this timestamp",
    )
    uploaded_before = filters.DateTimeFilter(
        field_name='uploaded_at',
        lookup_expr='lte',
        help_text="Filter evidence uploaded before this timestamp",
    )

    expiry_after = filters.DateFilter(
        field_name='auto_expiry_date',
        lookup_expr='gte',
        help_text="Filter evidence expiring on or after this date",
    )
    expiry_before = filters.DateFilter(
        field_name='auto_expiry_date',
        lookup_expr='lte',
        help_text="Filter evidence expiring on or before this date",
    )

    search = filters.CharFilter(
        method='filter_search',
        help_text="Search transfer ID, payer name, or payment reference",
    )

    class Meta:
        model = BankTransferEvidence
        fields = []

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(
            Q(transfer_id__icontains=value) |
            Q(payer_name__icontains=value) |
            Q(payment__payment_reference__icontains=value)
        )


class PaymentHistoryActionFilterSet(filters.FilterSet):
    """
    Filterset for PaymentHistoryAction model.
    
    Supports filtering by:
    - Payment
    - Action type
    - Performed by user
    - Date ranges
    """
    
    payment = filters.NumberFilter(
        field_name='payment__id',
        help_text="Filter by payment ID"
    )
    payment__payment_id = filters.UUIDFilter(
        field_name='payment__payment_id',
        help_text="Filter by payment UUID"
    )
    
    action = filters.CharFilter(
        field_name='action',
        lookup_expr='icontains',
        help_text="Filter by action type (partial match)"
    )
    
    performed_by = filters.NumberFilter(
        field_name='performed_by__id',
        help_text="Filter by user ID who performed action"
    )
    performed_by__username = filters.CharFilter(
        field_name='performed_by__username',
        lookup_expr='icontains',
        help_text="Filter by username who performed action"
    )
    
    timestamp_after = filters.DateTimeFilter(
        field_name='timestamp',
        lookup_expr='gte',
        help_text="Filter actions after this timestamp"
    )
    timestamp_before = filters.DateTimeFilter(
        field_name='timestamp',
        lookup_expr='lte',
        help_text="Filter actions before this timestamp"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search description or notes"
    )
    
    class Meta:
        model = PaymentHistoryAction
        fields = []
    
    def filter_search(self, queryset, name, value):
        """Search across description and notes."""
        if not value:
            return queryset
        
        return queryset.filter(
            Q(description__icontains=value) |
            Q(notes__icontains=value)
        )
