from django_filters import rest_framework as filters
from django.db.models import Q
from django.db import connection, DatabaseError
from django.contrib.contenttypes.models import ContentType

try:
    from django.contrib.postgres.search import TrigramSimilarity
except Exception:  # pragma: no cover - optional postgres feature
    TrigramSimilarity = None
from apps.events.models import (
    Event, EventType, EventAuthorization, EventPermission,
    EventPermissionAssignment, EventRole, EventRoleAssignment,
    EventStaff, EventStaffInvite, EventReview, EventQuestion, EventVenue,
    EventQuestionAnswer
)
from django.utils import timezone
from datetime import timedelta
from apps.bookings.models import Booking
from apps.payments.models import Payment, PaymentStatusChoices


class EventMyBookingFilterSet(filters.FilterSet):
    """
    Filterset for user's own bookings within an event.

    Supports filtering by:
    - Outstanding payments status
    - Booking date range (absolute and relative)
    - Attendee name search
    - Booking reference

    Uses OR logic for combining filters.

    Example queries:
        ?has_outstanding_payments=true
        ?booked_after=2025-01-01
        ?booked_in_days=7
        ?attendee_name=John
        ?booking_reference=BKG-FAM-001
    """

    # Payment status filter
    has_outstanding_payments = filters.BooleanFilter(
        method='filter_has_outstanding_payments',
        help_text="Filter by outstanding payment status (true/false)"
    )

    # Date filters
    booked_after = filters.DateTimeFilter(
        field_name='booked_at',
        lookup_expr='gte',
        help_text="Filter bookings made after this date (ISO 8601 format)"
    )
    booked_before = filters.DateTimeFilter(
        field_name='booked_at',
        lookup_expr='lte',
        help_text="Filter bookings made before this date (ISO 8601 format)"
    )
    booked_in_days = filters.CharFilter(
        method='filter_booked_in_days',
        help_text="Filter bookings from last N days (e.g., 7, 30, 90)"
    )

    # Attendee filter
    attendee_name = filters.CharFilter(
        method='filter_attendee_name',
        help_text="Filter by attendee name (first or last, case-insensitive)"
    )

    # Booking reference filter
    booking_reference = filters.CharFilter(
        field_name='booking_reference',
        lookup_expr='icontains',
        help_text="Filter by booking reference (contains, case-insensitive)"
    )

    class Meta:
        model = Booking
        fields = []

    def _get_booking_target_ids_with_statuses(self, statuses):
        booking_type = ContentType.objects.get_for_model(Booking)
        return list(
            Payment.objects.filter(
                target_type=booking_type,
                status__in=statuses,
            ).values_list('target_id', flat=True)
        )

    def _is_filter_applied(self, field_name):
        value = self.form.cleaned_data.get(field_name)
        return value not in (None, '', [])

    def filter_has_outstanding_payments(self, queryset, name, value):
        """Filter bookings that have outstanding (non-completed) payments."""
        outstanding_target_ids = self._get_booking_target_ids_with_statuses([
            PaymentStatusChoices.PENDING,
            PaymentStatusChoices.DRAFTING,
        ])

        if value:
            return queryset.filter(id__in=outstanding_target_ids).distinct()

        # All payments completed or booking has no payments
        return queryset.exclude(id__in=outstanding_target_ids).distinct()

    def filter_booked_in_days(self, queryset, name, value):
        """Filter bookings from the last N days."""
        try:
            days = int(value)
            if days < 0:
                return queryset
            cutoff_date = timezone.now() - timedelta(days=days)
            return queryset.filter(booked_at__gte=cutoff_date).distinct()
        except (ValueError, TypeError):
            return queryset

    def filter_attendee_name(self, queryset, name, value):
        """Filter by attendee first name or last name."""
        return queryset.filter(
            Q(attendees__first_name__icontains=value) |
            Q(attendees__last_name__icontains=value)
        ).distinct()

    def filter_queryset(self, queryset):
        """
        Override filter_queryset to apply OR logic across all active filters.

        Default behavior combines filters with AND. This override combines all
        applied filters with OR to get broader results.
        """
        # Get the parent filtered queryset first
        filterset = super().filter_queryset(queryset)

        # Check if any filters are actually applied
        filters_applied = any(self._is_filter_applied(f) for f in self.filters.keys())

        if not filters_applied:
            return filterset

        # Build OR query manually
        q_objects = Q()

        # has_outstanding_payments filter
        if self._is_filter_applied('has_outstanding_payments'):
            outstanding_target_ids = self._get_booking_target_ids_with_statuses([
                PaymentStatusChoices.PENDING,
                PaymentStatusChoices.DRAFTING,
            ])
            if self.form.cleaned_data.get('has_outstanding_payments') is True:
                q_objects |= Q(id__in=outstanding_target_ids)
            else:
                q_objects |= ~Q(id__in=outstanding_target_ids)

        # booked_after filter
        if self.form.cleaned_data.get('booked_after'):
            q_objects |= Q(booked_at__gte=self.form.cleaned_data['booked_after'])

        # booked_before filter
        if self.form.cleaned_data.get('booked_before'):
            q_objects |= Q(booked_at__lte=self.form.cleaned_data['booked_before'])

        # booked_in_days filter
        if self.form.cleaned_data.get('booked_in_days'):
            try:
                days = int(self.form.cleaned_data['booked_in_days'])
                if days >= 0:
                    cutoff_date = timezone.now() - timedelta(days=days)
                    q_objects |= Q(booked_at__gte=cutoff_date)
            except (ValueError, TypeError):
                pass

        # attendee_name filter
        if self.form.cleaned_data.get('attendee_name'):
            q_objects |= Q(
                Q(attendees__first_name__icontains=self.form.cleaned_data['attendee_name']) |
                Q(attendees__last_name__icontains=self.form.cleaned_data['attendee_name'])
            )

        # booking_reference filter
        if self.form.cleaned_data.get('booking_reference'):
            q_objects |= Q(booking_reference__icontains=self.form.cleaned_data['booking_reference'])

        # Apply the OR query and return distinct results
        return queryset.filter(q_objects).distinct()


class EventMyOutstandingPaymentsFilterSet(filters.FilterSet):
    """
    Filterset for user's outstanding (unpaid) payments within an event.

    Filters payments that are:
    - Status: PENDING or DRAFTING
    - Linked to a Booking OR have a pending checkout intent

    Supports filtering by:
    - Payment status
    - Booking date range (absolute and relative)
    - Attendee name search
    - Payment method

    Uses OR logic for combining filters.

    Example queries:
        ?payment_status=PENDING
        ?booked_after=2025-01-01
        ?booked_in_days=7
        ?attendee_name=John
        ?payment_method=stripe
    """

    # Payment status filter
    payment_status = filters.MultipleChoiceFilter(
        field_name='status',
        choices=PaymentStatusChoices.choices,
        help_text="Filter by payment status (PENDING, DRAFTING, etc.)"
    )

    # Date filters (for booking date or payment creation date)
    booked_after = filters.DateTimeFilter(
        method='filter_booked_after',
        help_text="Filter payments for bookings made after this date (ISO 8601 format)"
    )
    booked_before = filters.DateTimeFilter(
        method='filter_booked_before',
        help_text="Filter payments for bookings made before this date (ISO 8601 format)"
    )
    booked_in_days = filters.CharFilter(
        method='filter_booked_in_days',
        help_text="Filter payments for bookings from last N days (e.g., 7, 30, 90)"
    )

    # Attendee filter (for associated bookings)
    attendee_name = filters.CharFilter(
        method='filter_attendee_name',
        help_text="Filter by attendee name in associated booking (first or last, case-insensitive)"
    )

    class Meta:
        model = Payment
        fields = []

    def _booking_target_q(self):
        booking_type = ContentType.objects.get_for_model(Booking)
        return Q(target_type=booking_type, target_id__isnull=False)

    def _booking_target_ids_by(self, **booking_filters):
        ids = Booking.objects.filter(**booking_filters).values_list('id', flat=True)
        return [str(v) for v in ids]

    def _is_filter_applied(self, field_name):
        value = self.form.cleaned_data.get(field_name)
        return value not in (None, '', [])

    def filter_booked_after(self, queryset, name, value):
        """Filter payments for bookings made after this date."""
        booking_target_ids = self._booking_target_ids_by(booked_at__gte=value)
        return queryset.filter(
            (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
            Q(target_type__isnull=True, created_at__gte=value)
        ).distinct()

    def filter_booked_before(self, queryset, name, value):
        """Filter payments for bookings made before this date."""
        booking_target_ids = self._booking_target_ids_by(booked_at__lte=value)
        return queryset.filter(
            (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
            Q(target_type__isnull=True, created_at__lte=value)
        ).distinct()

    def filter_booked_in_days(self, queryset, name, value):
        """Filter payments for bookings from the last N days."""
        try:
            days = int(value)
            if days < 0:
                return queryset
            cutoff_date = timezone.now() - timedelta(days=days)
            booking_target_ids = self._booking_target_ids_by(booked_at__gte=cutoff_date)
            return queryset.filter(
                (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
                Q(target_type__isnull=True, created_at__gte=cutoff_date)
            ).distinct()
        except (ValueError, TypeError):
            return queryset

    def filter_attendee_name(self, queryset, name, value):
        """Filter payments by attendee name in booking or checkout metadata."""
        booking_target_ids = [
            str(v) for v in Booking.objects.filter(
                Q(attendees__first_name__icontains=value) |
                Q(attendees__last_name__icontains=value)
            ).distinct().values_list('id', flat=True)
        ]

        return queryset.filter(
            (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
            Q(target_type__isnull=True, metadata__icontains=value)
        ).distinct()

    def filter_queryset(self, queryset):
        """
        Override filter_queryset to apply OR logic across all active filters.

        Default behavior combines filters with AND. This override combines all
        applied filters with OR to get broader results.
        """
        # Get the parent filtered queryset first
        filterset = super().filter_queryset(queryset)

        # Check if any filters are actually applied
        filters_applied = any(self._is_filter_applied(f) for f in self.filters.keys())

        if not filters_applied:
            return filterset

        # Build OR query manually
        q_objects = Q()

        # payment_status filter
        if self._is_filter_applied('payment_status'):
            q_objects |= Q(status__in=self.form.cleaned_data['payment_status'])

        # booked_after filter
        if self._is_filter_applied('booked_after'):
            booking_target_ids = self._booking_target_ids_by(
                booked_at__gte=self.form.cleaned_data['booked_after']
            )
            q_objects |= Q(
                (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
                Q(target_type__isnull=True, created_at__gte=self.form.cleaned_data['booked_after'])
            )

        # booked_before filter
        if self._is_filter_applied('booked_before'):
            booking_target_ids = self._booking_target_ids_by(
                booked_at__lte=self.form.cleaned_data['booked_before']
            )
            q_objects |= Q(
                (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
                Q(target_type__isnull=True, created_at__lte=self.form.cleaned_data['booked_before'])
            )

        # booked_in_days filter
        if self._is_filter_applied('booked_in_days'):
            try:
                days = int(self.form.cleaned_data['booked_in_days'])
                if days >= 0:
                    cutoff_date = timezone.now() - timedelta(days=days)
                    booking_target_ids = self._booking_target_ids_by(booked_at__gte=cutoff_date)
                    q_objects |= Q(
                        (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
                        Q(target_type__isnull=True, created_at__gte=cutoff_date)
                    )
            except (ValueError, TypeError):
                pass

        # attendee_name filter
        if self._is_filter_applied('attendee_name'):
            attendee_name = self.form.cleaned_data['attendee_name']
            booking_target_ids = [
                str(v) for v in Booking.objects.filter(
                    Q(attendees__first_name__icontains=attendee_name) |
                    Q(attendees__last_name__icontains=attendee_name)
                ).distinct().values_list('id', flat=True)
            ]
            q_objects |= Q(
                (self._booking_target_q() & Q(target_id__in=booking_target_ids)) |
                Q(target_type__isnull=True, metadata__icontains=attendee_name)
            )

        # Apply the OR query and return distinct results
        return queryset.filter(q_objects).distinct()


class EventTypeFilterSet(filters.FilterSet):
    title = filters.CharFilter(lookup_expr='icontains')
    code = filters.CharFilter(lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventType
        fields = ['title', 'code', 'created_by']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(title__icontains=value) |
            Q(code__icontains=value) |
            Q(description__icontains=value)
        )


class EventFilterSet(filters.FilterSet):
    """
    Fine-grained event filtering with clean URL parameters.

    Query examples:
        ?status=OPEN&status=PUBLISHED
        ?organisation_name=amdg
        ?area=12&chapter=3
        ?venue_name=cathedral&venue_city=london
        ?search=summer retreat
        ?fuzzy_search=broghton conf&fuzzy_threshold=0.2
    """

    title = filters.CharFilter(field_name='title', lookup_expr='iexact')
    display_code = filters.CharFilter(field_name='display_code', lookup_expr='iexact')
    display_identifier = filters.CharFilter(field_name='display_identifier', lookup_expr='icontains')
    status = filters.MultipleChoiceFilter(choices=Event._meta.get_field('status').choices)

    event_type = filters.NumberFilter(field_name='event_type__id')
    event_type_code = filters.CharFilter(field_name='event_type__code', lookup_expr='icontains')
    event_type_title = filters.CharFilter(field_name='event_type__title', lookup_expr='icontains')

    organisation = filters.NumberFilter(field_name='organisation__id')
    organisation_name = filters.CharFilter(field_name='organisation__title', lookup_expr='icontains')

    location = filters.NumberFilter(field_name='location__id')
    area = filters.NumberFilter(field_name='location__id')
    area_name = filters.CharFilter(field_name='location__area_name', lookup_expr='icontains')
    chapter = filters.NumberFilter(field_name='location__chapter__id')
    chapter_name = filters.CharFilter(field_name='location__chapter__chapter_name', lookup_expr='icontains')

    venue = filters.NumberFilter(field_name='event_venues__source_venue_id')
    venue_name = filters.CharFilter(field_name='event_venues__name', lookup_expr='icontains')
    venue_address = filters.CharFilter(field_name='event_venues__address', lookup_expr='icontains')
    venue_city = filters.CharFilter(field_name='event_venues__city', lookup_expr='icontains')
    venue_postcode = filters.CharFilter(field_name='event_venues__postcode', lookup_expr='icontains')

    theme = filters.CharFilter(field_name='theme', lookup_expr='icontains')
    anchor_verse = filters.CharFilter(field_name='anchor_verse', lookup_expr='icontains')

    start_after = filters.DateTimeFilter(field_name='start_datetime', lookup_expr='gte')
    start_before = filters.DateTimeFilter(field_name='start_datetime', lookup_expr='lte')
    end_after = filters.DateTimeFilter(field_name='end_datetime', lookup_expr='gte')
    end_before = filters.DateTimeFilter(field_name='end_datetime', lookup_expr='lte')

    search = filters.CharFilter(method='filter_search')
    fuzzy_search = filters.CharFilter(method='filter_fuzzy_search')
    fuzzy_threshold = filters.NumberFilter(method='filter_fuzzy_threshold')
    
    class Meta:
        model = Event
        fields = [
            'title', 'display_code', 'display_identifier',
            'status',
            'event_type', 'event_type_code', 'event_type_title',
            'organisation', 'organisation_name',
            'location', 'area', 'area_name', 'chapter', 'chapter_name',
            'venue', 'venue_name', 'venue_address', 'venue_city', 'venue_postcode',
            'theme', 'anchor_verse',
            'start_after', 'start_before', 'end_after', 'end_before',
            'search', 'fuzzy_search', 'fuzzy_threshold',
            'created_by',
        ]
    
    def filter_search(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(
            Q(title__icontains=value) |
            Q(short_description__icontains=value) |
            Q(long_description__icontains=value) |
            Q(display_code__icontains=value) |
            Q(display_identifier__icontains=value) |
            Q(theme__icontains=value) |
            Q(anchor_verse__icontains=value) |
            Q(organisation__title__icontains=value) |
            Q(event_type__title__icontains=value) |
            Q(event_type__code__icontains=value) |
            Q(location__area_name__icontains=value) |
            Q(location__chapter__chapter_name__icontains=value) |
            Q(event_venues__name__icontains=value) |
            Q(event_venues__address__icontains=value) |
            Q(event_venues__city__icontains=value) |
            Q(event_venues__postcode__icontains=value)
        ).distinct()

    def filter_fuzzy_threshold(self, queryset, name, value):
        # Threshold is consumed by filter_fuzzy_search when present.
        return queryset

    def filter_fuzzy_search(self, queryset, name, value):
        if not value:
            return queryset

        # Fallback to icontains search for non-Postgres backends.
        if connection.vendor != 'postgresql' or TrigramSimilarity is None:
            return self.filter_search(queryset, name, value)

        raw_threshold = self.data.get('fuzzy_threshold')
        try:
            threshold = float(raw_threshold) if raw_threshold not in (None, '') else 0.2
        except (TypeError, ValueError):
            threshold = 0.2

        threshold = max(0.0, min(1.0, threshold))

        try:
            return (
                queryset.annotate(
                    similarity=(
                        TrigramSimilarity('title', value) +
                        TrigramSimilarity('short_description', value) +
                        TrigramSimilarity('long_description', value) +
                        TrigramSimilarity('display_code', value) +
                        TrigramSimilarity('display_identifier', value) +
                        TrigramSimilarity('theme', value) +
                        TrigramSimilarity('anchor_verse', value) +
                        TrigramSimilarity('organisation__title', value) +
                        TrigramSimilarity('event_type__title', value) +
                        TrigramSimilarity('event_type__code', value) +
                        TrigramSimilarity('location__area_name', value) +
                        TrigramSimilarity('location__chapter__chapter_name', value) +
                        TrigramSimilarity('event_venues__name', value) +
                        TrigramSimilarity('event_venues__address', value) +
                        TrigramSimilarity('event_venues__city', value)
                    )
                )
                .filter(similarity__gte=threshold)
                .order_by('-similarity', '-start_datetime')
                .distinct()
            )
        except DatabaseError:
            # If pg_trgm isn't enabled in the database, gracefully fallback.
            return self.filter_search(queryset, name, value)


class EventAuthorizationFilterSet(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=EventAuthorization._meta.get_field('status').choices)
    event_title = filters.CharFilter(field_name='event__title', lookup_expr='icontains')
    event = filters.CharFilter(field_name='event__url_safe_title')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventAuthorization
        fields = ['event', 'status', 'reviewed_by']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(event__title__icontains=value) |
            Q(notes__icontains=value)
        )


class EventPermissionFilterSet(filters.FilterSet):
    name = filters.CharFilter(lookup_expr='icontains')
    code = filters.CharFilter(lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventPermission
        fields = ['name', 'code', 'category']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value) |
            Q(code__icontains=value) |
            Q(description__icontains=value)
        )


class EventRoleFilterSet(filters.FilterSet):
    name = filters.CharFilter(lookup_expr='icontains')
    code = filters.CharFilter(lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventRole
        fields = ['name', 'code', 'category']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value) |
            Q(code__icontains=value) |
            Q(description__icontains=value)
        )


class EventStaffFilterSet(filters.FilterSet):
    user_email = filters.CharFilter(field_name='user__email', lookup_expr='icontains')
    user_name = filters.CharFilter(method='filter_user_name')
    event = filters.CharFilter(field_name='event__url_safe_title')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventStaff
        fields = ['event', 'user']
    
    def filter_user_name(self, queryset, name, value):
        return queryset.filter(
            Q(user__first_name__icontains=value) |
            Q(user__last_name__icontains=value) |
            Q(user__email__icontains=value)
        )
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(user__first_name__icontains=value) |
            Q(user__last_name__icontains=value) |
            Q(user__email__icontains=value) |
            Q(notes__icontains=value)
        )


class EventReviewFilterSet(filters.FilterSet):
    rating_min = filters.NumberFilter(field_name='rating', lookup_expr='gte')
    rating_max = filters.NumberFilter(field_name='rating', lookup_expr='lte')
    event_title = filters.CharFilter(field_name='event__title', lookup_expr='icontains')
    event = filters.CharFilter(field_name='event__url_safe_title')
    user_email = filters.CharFilter(field_name='user__email', lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventReview
        fields = ['event', 'user', 'approved', 'rating']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(comment__icontains=value) |
            Q(event__title__icontains=value) |
            Q(user__email__icontains=value)
        )


class EventQuestionFilterSet(filters.FilterSet):
    question_title = filters.CharFilter(lookup_expr='icontains')
    question_body = filters.CharFilter(lookup_expr='icontains')
    event = filters.CharFilter(field_name='event__url_safe_title')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventQuestion
        fields = ['event', 'question_type', 'required', 'public']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(question_title__icontains=value) |
            Q(question_body__icontains=value)
        )


class EventQuestionAnswerFilterSet(filters.FilterSet):
    """
    Filterset for EventQuestionAnswer with attendee UUID support.
    
    Supports filtering by:
    - Question ID
    - Attendee ID (integer primary key)
    - Attendee ID (UUID - public facing)
    - Event ID (through question)
    - Answer text search
    
    Example queries:
        ?question=123
        ?attendee=456
        ?attendee_id=550e8400-e29b-41d4-a716-446655440000
        ?event=789
        ?search=answer text
    """
    
    # Question filters
    question = filters.UUIDFilter(
        field_name='question__id',
        help_text="Filter by question ID"
    )
    question__event = filters.NumberFilter(
        field_name='question__event__id',
        help_text="Filter by event ID (through question)"
    )
    
    # Attendee filters
    attendee = filters.NumberFilter(
        field_name='attendee__id',
        help_text="Filter by attendee ID (integer primary key)"
    )
    attendee_id = filters.UUIDFilter(
        field_name='attendee__attendee_id',
        help_text="Filter by attendee UUID (public facing identifier)"
    )
    attendee_email = filters.CharFilter(
        field_name='attendee__email',
        lookup_expr='icontains',
        help_text="Filter by attendee email"
    )
    
    # Event filter (shortcut through question)
    event = filters.CharFilter(
        field_name='question__event__url_safe_title',
        help_text="Filter by event URL-safe title"
    )
    
    # Answer text search
    answer_text = filters.CharFilter(
        field_name='answer_text',
        lookup_expr='icontains',
        help_text="Search in answer text"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search across answer text and question title"
    )
    
    class Meta:
        model = EventQuestionAnswer
        fields = [
            'question', 'question__event',
            'attendee', 'attendee_id', 'attendee_email',
            'event',
            'answer_text', 'search'
        ]
    
    def filter_search(self, queryset, name, value):
        """Full-text search across answer text and question title."""
        return queryset.filter(
            Q(answer_text__icontains=value) |
            Q(question__question_title__icontains=value)
        )


class EventPermissionAssignmentFilterSet(filters.FilterSet):
    event = filters.CharFilter(field_name='event__url_safe_title')

    class Meta:
        model = EventPermissionAssignment
        fields = ['event', 'user', 'permission']

from apps.utils.querying import get_event_or_url_safe_title

class EventRoleAssignmentFilterSet(filters.FilterSet):
    event = filters.CharFilter(method='filter_event')

    class Meta:
        model = EventRoleAssignment
        fields = ['event', 'user', 'role']

    def filter_event(self, queryset, name, value):
        """Filter role assignments by event URL-safe title."""
        return queryset.filter(Q(event=get_event_or_url_safe_title(value)))


class EventVenueFilterSet(filters.FilterSet):
    event_id = filters.CharFilter(field_name='event__url_safe_title')
    event = filters.CharFilter(field_name='event__url_safe_title')
    source_venue_id = filters.NumberFilter(field_name='source_venue_id')

    class Meta:
        model = EventVenue
        fields = ['event', 'source_venue_id']


class EventStaffInviteFilterSet(filters.FilterSet):
    event = filters.CharFilter(field_name='event__url_safe_title')
    user_email = filters.CharFilter(field_name='target_user__email', lookup_expr='icontains')
    username = filters.CharFilter(field_name='target_user__username', lookup_expr='icontains')
    accepted = filters.BooleanFilter(field_name='accepted')
    class Meta:
        model = EventStaffInvite
        fields = ['event', 'target_user', 'accepted']


class EventNotificationFilterSet(filters.FilterSet):
    """
    Filterset for EventNotification.

    Supports filtering by:
    - Event (by url_safe_title or ID)
    - Notification type
    - Priority
    - Read status
    - Related object IDs
    - Date range

    Example queries:
        ?event=my-event-2026
        ?is_read=false
        ?notification_type=ORDER_FULFILLMENT
        ?priority=HIGH&priority=URGENT
        ?created_after=2026-01-01
    """

    event = filters.CharFilter(field_name='event__url_safe_title', help_text="Filter by event URL-safe title")
    event_id = filters.NumberFilter(field_name='event__id', help_text="Filter by event ID")
    notification_type = filters.MultipleChoiceFilter(
        field_name='notification_type',
        choices=[
            ('ORDER_FULFILLMENT', 'Order Fulfillment Required'),
            ('BOOKING_CONFIRMATION', 'Booking Confirmed'),
            ('REFUND_REQUEST', 'Refund Requested'),
            ('PAYMENT_FAILED', 'Payment Failed'),
            ('CAPACITY_WARNING', 'Capacity Warning'),
            ('AUTHORIZATION_REQUEST', 'Authorization Request'),
            ('GENERAL', 'General Notification'),
        ],
        help_text="Filter by notification type (multiple values allowed)"
    )
    priority = filters.MultipleChoiceFilter(
        field_name='priority',
        choices=[
            ('LOW', 'Low'),
            ('NORMAL', 'Normal'),
            ('HIGH', 'High'),
            ('URGENT', 'Urgent'),
        ],
        help_text="Filter by priority (multiple values allowed)"
    )
    is_read = filters.BooleanFilter(field_name='is_read', help_text="Filter by read status")
    related_payment = filters.NumberFilter(field_name='related_payment__id', help_text="Filter by related payment ID")
    related_order = filters.NumberFilter(field_name='related_order__id', help_text="Filter by related order ID")
    related_booking = filters.NumberFilter(field_name='related_booking__id', help_text="Filter by related booking ID")
    created_after = filters.DateTimeFilter(field_name='created_at', lookup_expr='gte', help_text="Filter notifications created after this datetime")
    created_before = filters.DateTimeFilter(field_name='created_at', lookup_expr='lte', help_text="Filter notifications created before this datetime")

    class Meta:
        from apps.events.models import EventNotification
        model = EventNotification
        fields = [
            'event', 'event_id', 'notification_type', 'priority',
            'is_read', 'related_payment', 'related_order', 'related_booking',
            'created_after', 'created_before',
        ]
