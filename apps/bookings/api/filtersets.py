"""
Production-grade filtersets for the bookings app.

Provides comprehensive filtering capabilities for booking models with
advanced querying options including date ranges, full-text search,
and complex field filtering.

FilterSets:
    - BookingFilterSet: Advanced booking filtering with multiple criteria
    - TicketFilterSet: Filter tickets by status, attendee, type
    - TicketTypeFilterSet: Filter ticket types by event, scope, activity
    - BookingPackageFilterSet: Filter packages by event, ticket type, eligibility
    - EventAlternativeSigninFilterSet: Filter event alternative signins
    - AttendeeAlternativeSigninFilterSet: Filter attendee alternative signins

Author: AMDG Platform Team
Version: 1.0.0
"""
from django_filters import rest_framework as filters
from django.db.models import Q
from django.utils import timezone
import uuid

from apps.bookings.models import (
    Booking, BookingIntent, BookingIntentStatusChoices,
    BookingPackage, BookingPackageRule,
    TicketType, Ticket, TicketScopeChoices, TicketStatusChoices,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
)
from apps.common.models import VerificationStatus


def filter_by_event_reference(queryset, value, base_field='event'):
    """Filter by event PK, event UUID, or URL-safe title for backwards compatibility."""
    if value is None:
        return queryset

    raw_value = str(value).strip()
    if not raw_value:
        return queryset

    if raw_value.isdigit():
        return queryset.filter(**{f'{base_field}__id': int(raw_value)})

    try:
        parsed_uuid = uuid.UUID(raw_value)
    except ValueError:
        return queryset.filter(**{f'{base_field}__url_safe_title': raw_value})

    return queryset.filter(**{f'{base_field}__event_id': parsed_uuid})


class BookingIntentFilterSet(filters.FilterSet):
    """
    Advanced filterset for BookingIntent model.
    
    Supports filtering by:
    - Status (pending, completed, expired, cancelled)
    - Event
    - Made by user
    - Date ranges (created, expires)
    - Active status
    
    Example queries:
        ?status=PENDING
        ?event=123
        ?is_active=true
        ?created_after=2025-01-01
    """
    
    status = filters.ChoiceFilter(
        field_name='status',
        choices=BookingIntentStatusChoices.choices,
        help_text='Filter by intent status'
    )

    event = filters.CharFilter(
        method='filter_event',
        help_text='Filter by event PK, UUID, or URL-safe title'
    )
    
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text='Filter by event UUID'
    )
    
    made_by = filters.NumberFilter(
        field_name='made_by__id',
        help_text='Filter by user ID who made the intent'
    )
    
    created_after = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text='Filter intents created on or after this datetime'
    )
    
    created_before = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text='Filter intents created on or before this datetime'
    )
    
    expires_after = filters.DateTimeFilter(
        field_name='expires_at',
        lookup_expr='gte',
        help_text='Filter intents expiring on or after this datetime'
    )
    
    expires_before = filters.DateTimeFilter(
        field_name='expires_at',
        lookup_expr='lte',
        help_text='Filter intents expiring on or before this datetime'
    )
    
    is_active = filters.BooleanFilter(
        method='filter_is_active',
        help_text='Filter by active status (pending and not expired)'
    )
    
    class Meta:
        model = BookingIntent
        fields = [
            'status', 'event', 'made_by', 'intended_ticket_count',
            'created_after', 'created_before', 'expires_after', 'expires_before',
            'is_active'
        ]
    
    def filter_is_active(self, queryset, name, value):
        """Filter intents by active status."""
        if value:
            # Active: PENDING status and not expired
            return queryset.filter(
                status=BookingIntentStatusChoices.PENDING,
                expires_at__gt=timezone.now()
            )
        else:
            # Inactive: any other status or expired
            return queryset.filter(
                Q(status__in=[
                    BookingIntentStatusChoices.COMPLETED,
                    BookingIntentStatusChoices.EXPIRED,
                    BookingIntentStatusChoices.CANCELLED
                ]) | Q(expires_at__lte=timezone.now())
            )

    def filter_event(self, queryset, name, value):
        """Filter intents by event identifier."""
        return filter_by_event_reference(queryset, value, base_field='event')


class BookingFilterSet(filters.FilterSet):
    """
    Advanced filterset for Booking model with comprehensive search capabilities.
    
    Supports filtering by:
    - Booking reference (exact, contains)
    - Event
    - User who made the booking
    - Date ranges (booked_at)
    - Attendee name, email
    - Ticket status
    - Payment status (through generic relation)
    
    Example queries:
        ?booking_reference=BKG-FAM-001
        ?event=123&made_by=456
        ?search=john&booked_after=2025-01-01
        ?attendee_email=john@example.com
    """
    
    # Booking reference filters
    booking_reference = filters.CharFilter(
        field_name='booking_reference',
        lookup_expr='iexact',
        help_text="Exact booking reference (case-insensitive)"
    )
    booking_reference__contains = filters.CharFilter(
        field_name='booking_reference',
        lookup_expr='icontains',
        help_text="Booking reference contains (case-insensitive)"
    )
    
    # Event filter
    event = filters.CharFilter(
        method='filter_event',
        help_text="Filter by event PK, UUID, or URL-safe title"
    )
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )
    
    # User filter
    made_by = filters.NumberFilter(
        field_name='made_by__id',
        help_text="Filter by user ID who made the booking"
    )
    made_by__username = filters.CharFilter(
        field_name='made_by__username',
        lookup_expr='icontains',
        help_text="Filter by username (case-insensitive)"
    )
    
    # Date range filters
    booked_after = filters.DateTimeFilter(
        field_name='booked_at',
        lookup_expr='gte',
        help_text="Filter bookings made after this date (ISO 8601 format)"
    )
    booked_before = filters.DateTimeFilter(
        field_name='booked_at',
        lookup_expr='lte',
        help_text="Filter bookings made before this date"
    )
    booked_date = filters.DateFilter(
        field_name='booked_at',
        lookup_expr='date',
        help_text="Filter bookings made on specific date (YYYY-MM-DD)"
    )
    
    # Attendee filters
    attendee_name = filters.CharFilter(
        method='filter_attendee_name',
        help_text="Filter by attendee name (first or last, case-insensitive)"
    )
    attendee_email = filters.CharFilter(
        field_name='attendees__email',
        lookup_expr='icontains',
        help_text="Filter by attendee email (case-insensitive)"
    )
    attendee_id = filters.UUIDFilter(
        field_name='attendees__attendee_id',
        help_text="Filter by attendee UUID"
    )
    
    # Ticket status filter
    ticket_status = filters.MultipleChoiceFilter(
        field_name='attendees__tickets__status',
        choices=TicketStatusChoices.choices,
        help_text="Filter by ticket status (can specify multiple)"
    )
    
    # General search across multiple fields
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search across booking reference, attendee names, and emails"
    )
    
    class Meta:
        model = Booking
        fields = []
    
    def filter_attendee_name(self, queryset, name, value):
        """Filter by attendee first name or last name."""
        return queryset.filter(
            Q(attendees__first_name__icontains=value) |
            Q(attendees__last_name__icontains=value)
        ).distinct()
    
    def filter_search(self, queryset, name, value):
        """
        General search across booking reference, attendee names, and emails.
        """
        return queryset.filter(
            Q(booking_reference__icontains=value) |
            Q(attendees__first_name__icontains=value) |
            Q(attendees__last_name__icontains=value) |
            Q(attendees__email__icontains=value) |
            Q(made_by__username__icontains=value) |
            Q(made_by__email__icontains=value)
        ).distinct()

    def filter_event(self, queryset, name, value):
        """Filter bookings by event identifier."""
        return filter_by_event_reference(queryset, value, base_field='event')


class TicketFilterSet(filters.FilterSet):
    """
    Filterset for Ticket model.
    
    Supports filtering by:
    - Status
    - Attendee
    - Ticket type
    - Booking
    - Package
    - Issued date ranges
    
    Example queries:
        ?status=ACTIVE&ticket_type=123
        ?attendee=456&package=789
        ?issued_after=2025-01-01
    """
    
    # Status filters
    status = filters.MultipleChoiceFilter(
        field_name='status',
        choices=TicketStatusChoices.choices,
        help_text="Filter by ticket status (can specify multiple)"
    )
    
    # Attendee filter
    attendee = filters.UUIDFilter(
        field_name='attendee__attendee_id',
        help_text="Filter by attendee UUID"
    )
    attendee__id = filters.NumberFilter(
        field_name='attendee__id',
        help_text="Filter by attendee database ID"
    )

    event_id = filters.UUIDFilter(
        field_name='attendee__booking__event__event_id',
        help_text="Filter by event UUID (through attendee's booking)"
    )
    event = filters.CharFilter(
        field_name='attendee__booking__event__url_safe_title',
        lookup_expr='exact',
        help_text="Filter by event URL-safe title"
    )

    
    # Ticket type filter
    ticket_type = filters.NumberFilter(
        field_name='ticket_type__id',
        help_text="Filter by ticket type ID"
    )
    ticket_type__scope = filters.ChoiceFilter(
        field_name='ticket_type__scope',
        choices=TicketScopeChoices.choices,
        help_text="Filter by ticket type scope"
    )
    
    # Booking filter (through attendee)
    booking = filters.NumberFilter(
        field_name='attendee__booking__id',
        help_text="Filter by booking ID"
    )
    booking__reference = filters.CharFilter(
        field_name='attendee__booking__booking_reference',
        lookup_expr='icontains',
        help_text="Filter by booking reference"
    )
    
    # Package filter
    package = filters.NumberFilter(
        field_name='package__id',
        help_text="Filter by booking package ID"
    )
    
    # Payment filter
    payment = filters.UUIDFilter(
        field_name='payment__payment_id',
        help_text="Filter by payment UUID"
    )
    
    # Date range filters
    issued_after = filters.DateTimeFilter(
        field_name='issued_at',
        lookup_expr='gte',
        help_text="Filter tickets issued after this date"
    )
    issued_before = filters.DateTimeFilter(
        field_name='issued_at',
        lookup_expr='lte',
        help_text="Filter tickets issued before this date"
    )
    
    # Search by ticket code
    ticket_code = filters.CharFilter(
        field_name='ticket_code',
        lookup_expr='icontains',
        help_text="Search by ticket code (case-insensitive)"
    )
    
    class Meta:
        model = Ticket
        fields = []


class TicketTypeFilterSet(filters.FilterSet):
    """
    Filterset for TicketType model.
    
    Supports filtering by:
    - Event
    - Scope
    - Active status
    - Validity date ranges
    
    Example queries:
        ?event=123&scope=FULL_EVENT
        ?is_active=true&valid_from__gte=2025-01-01
    """
    
    # Event filter
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event ID"
    )

    event = filters.CharFilter(
        method='filter_event',
        help_text="Filter by event PK, UUID, or URL-safe title"
    )
    
    # Scope filter
    scope = filters.MultipleChoiceFilter(
        field_name='scope',
        choices=TicketScopeChoices.choices,
        help_text="Filter by ticket scope (can specify multiple)"
    )
    
    # Active status filter
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )
    
    # Validity date filters
    valid_from__gte = filters.DateTimeFilter(
        field_name='valid_from',
        lookup_expr='gte',
        help_text="Filter by valid from date (greater than or equal)"
    )
    valid_from__lte = filters.DateTimeFilter(
        field_name='valid_from',
        lookup_expr='lte',
        help_text="Filter by valid from date (less than or equal)"
    )
    valid_until__gte = filters.DateTimeFilter(
        field_name='valid_until',
        lookup_expr='gte',
        help_text="Filter by valid until date (greater than or equal)"
    )
    valid_until__lte = filters.DateTimeFilter(
        field_name='valid_until',
        lookup_expr='lte',
        help_text="Filter by valid until date (less than or equal)"
    )
    
    # Currently valid filter
    currently_valid = filters.BooleanFilter(
        method='filter_currently_valid',
        help_text="Filter ticket types that are currently valid"
    )
    
    # Search by title or code
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search by title or code"
    )
    
    class Meta:
        model = TicketType
        fields = []
    
    def filter_currently_valid(self, queryset, name, value):
        """Filter ticket types that are currently valid."""
        if value:
            now = timezone.now()
            return queryset.filter(
                is_active=True,
                valid_from__lte=now,
                valid_until__gte=now
            )
        return queryset
    
    def filter_search(self, queryset, name, value):
        """Search by title or code."""
        return queryset.filter(
            Q(title__icontains=value) |
            Q(code__icontains=value)
        )

    def filter_event(self, queryset, name, value):
        """Filter ticket types by event identifier."""
        return filter_by_event_reference(queryset, value, base_field='event')


class BookingPackageFilterSet(filters.FilterSet):
    """
    Filterset for BookingPackage model.
    
    Supports filtering by:
    - Event
    - Ticket type
    - Active status
    - Price ranges
    - Eligibility for specific attendee
    
    Example queries:
        ?event=123&is_active=true
        ?ticket_type=456&min_price=10&max_price=50
        ?eligible_for_attendee=789
    """
    
    # Event filter
    event = filters.CharFilter(
        method='filter_event',
        help_text="Filter by event PK, UUID, or URL-safe title"
    )
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )
    
    # Ticket type filter
    ticket_type = filters.NumberFilter(
        field_name='ticket_type__id',
        help_text="Filter by ticket type ID"
    )
    ticket_type__scope = filters.ChoiceFilter(
        field_name='ticket_type__scope',
        choices=TicketScopeChoices.choices,
        help_text="Filter by ticket type scope"
    )
    
    # Active status filter
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )
    
    # Price range filters (on base_amount)
    min_price = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='gte',
        help_text="Minimum package price"
    )
    max_price = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='lte',
        help_text="Maximum package price"
    )
    
    # Eligibility filter - checks if package rules apply to specific attendee
    eligible_for_attendee = filters.UUIDFilter(
        method='filter_eligible_for_attendee',
        help_text="Filter packages eligible for specific attendee UUID"
    )
    
    # Search by name
    search = filters.CharFilter(
        field_name='name',
        lookup_expr='icontains',
        help_text="Search by package name (case-insensitive)"
    )
    
    class Meta:
        model = BookingPackage
        fields = []

    def filter_event(self, queryset, name, value):
        """Filter booking packages by event identifier."""
        return filter_by_event_reference(queryset, value, base_field='event')
    
    def filter_eligible_for_attendee(self, queryset, name, value):
        """
        Filter packages that are eligible for a specific attendee.
        This checks package rules against the attendee's context.
        """
        from apps.attendee.models import Attendee
        
        try:
            attendee = Attendee.objects.get(attendee_id=value)
        except Attendee.DoesNotExist:
            return queryset.none()
        
        # Get the request user for package evaluation
        request = self.request
        user = request.user if request else None
        
        # Filter packages that the attendee can use
        eligible_packages = []
        for package in queryset:
            if package.can_use_package(user, attendee):
                eligible_packages.append(package.id)
        
        return queryset.filter(id__in=eligible_packages)


class EventAlternativeSigninFilterSet(filters.FilterSet):
    """
    Filterset for EventAlternativeSigninIdentifier model.
    
    Supports filtering by:
    - Event
    - Active status
    - Verification status
    
    Example queries:
        ?event=123&is_active=true
        ?verification_status=VERIFIED
    """
    
    # Event filter
    event = filters.CharFilter(
        field_name='event__url_safe_title',
        lookup_expr='exact',
        help_text="Filter by event URL-safe title"
    )
    event_id = filters.UUIDFilter(
        field_name='event__event_id',
        help_text="Filter by event UUID"
    )
    
    # Active status filter
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )
    
    # Verification status filter
    verification_status = filters.MultipleChoiceFilter(
        field_name='verification_status',
        choices=VerificationStatus.choices,
        help_text="Filter by verification status (can specify multiple)"
    )
    
    # Search by title
    search = filters.CharFilter(
        field_name='title',
        lookup_expr='icontains',
        help_text="Search by title (case-insensitive)"
    )
    
    class Meta:
        model = EventAlternativeSigninIdentifier
        fields = []


class AttendeeAlternativeSigninFilterSet(filters.FilterSet):
    """
    Filterset for AttendeeAlternativeSigninIdentifier model.
    
    Supports filtering by:
    - Attendee
    - Ticket
    - Event alternative signin
    - Identifier
    
    Example queries:
        ?attendee=123
        ?event_alternative_signin=456
        ?identifier=ABC123
    """
    
    # Attendee filter
    attendee = filters.UUIDFilter(
        field_name='attendee__attendee_id',
        help_text="Filter by attendee UUID"
    )
    attendee__id = filters.NumberFilter(
        field_name='attendee__id',
        help_text="Filter by attendee database ID"
    )
    
    # Ticket filter
    ticket = filters.UUIDFilter(
        field_name='ticket__ticket_id',
        help_text="Filter by ticket UUID"
    )
    
    # Event alternative signin filter
    event_alternative_signin = filters.UUIDFilter(
        field_name='event_alternative_signin__id',
        help_text="Filter by event alternative signin UUID"
    )
    event_alternative_signin__event = filters.NumberFilter(
        field_name='event_alternative_signin__event__id',
        help_text="Filter by event ID"
    )
    
    # Identifier filter
    identifier = filters.CharFilter(
        field_name='identifier',
        lookup_expr='iexact',
        help_text="Filter by exact identifier (case-insensitive)"
    )
    identifier__contains = filters.CharFilter(
        field_name='identifier',
        lookup_expr='icontains',
        help_text="Filter by identifier contains (case-insensitive)"
    )
    
    # Has ticket filter
    has_ticket = filters.BooleanFilter(
        method='filter_has_ticket',
        help_text="Filter by whether identifier is linked to a ticket"
    )
    
    class Meta:
        model = AttendeeAlternativeSigninIdentifier
        fields = []
    
    def filter_has_ticket(self, queryset, name, value):
        """Filter by whether identifier is linked to a ticket."""
        if value:
            return queryset.exclude(ticket__isnull=True)
        else:
            return queryset.filter(ticket__isnull=True)
