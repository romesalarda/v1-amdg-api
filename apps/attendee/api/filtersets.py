"""
FilterSets for the attendee app.

Provides comprehensive filtering capabilities for attendee search and queries,
including advanced search by personal information.
"""
import django_filters
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from apps.attendee.models import (
    Attendee, AttendeeGuardian, AttendeeAction,
    FamilyGroup, FamilyAttendee, AttendeeMessage,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    EmergencyContact, Consent, AttendeeConsent,
    EventAttendance, AttendeeOrganisation,
    AttendeeRelationship, AttendeeActionChoices,
    AttendeeMessagePriority, HumanRelationshipChoices,
)

from apps.common.models import VerificationStatus
from apps.events.models import EventQuestionTypeChoices, EventFormQuestionTypeChoices
from apps.products.models import OrderStatusChoices, ProductVariant
from apps.payments.models import PaymentStatusChoices, PaymentMethodTypeChoices
from django.db.models import Value, TextField

try:
    from django.contrib.postgres.search import TrigramSimilarity
except Exception:  # pragma: no cover - optional postgres feature
    TrigramSimilarity = None

PAYMENT_TARGET_CHOICES = (
    ('booking', 'Booking'),
    ('order', 'Order'),
    ('ticket', 'Ticket'),
)


# ── Custom multi-value filters ─────────────────────────────────────────────────

class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """Accepts comma-separated string values, e.g. ?status=active,inactive"""
    pass


class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    """Accepts comma-separated integer/float values, e.g. ?ids=1,2,3"""
    pass


class UUIDInFilter(django_filters.BaseInFilter, django_filters.UUIDFilter):
    """Accepts comma-separated UUID values, e.g. ?uuids=abc...,def..."""
    pass


class AttendeeFilterSet(django_filters.FilterSet):
    """
    Advanced filterset for Attendee with comprehensive search capabilities.
    """
    # Text search
    search = django_filters.CharFilter(method='filter_search', label='Search by name, email, or ID')
    
    # Name filters
    first_name = django_filters.CharFilter(lookup_expr='icontains')
    last_name = django_filters.CharFilter(lookup_expr='icontains')
    full_name = django_filters.CharFilter(method='filter_full_name', label='Full name search')
    
    # Contact filters
    email = django_filters.CharFilter(lookup_expr='icontains')
    phone_number = django_filters.CharFilter(lookup_expr='icontains')
    
    # Demographic filters
    gender = django_filters.CharFilter(lookup_expr='iexact')
    age_min = django_filters.NumberFilter(method='filter_age_min', label='Minimum age')
    age_max = django_filters.NumberFilter(method='filter_age_max', label='Maximum age')
    is_minor = django_filters.BooleanFilter(method='filter_is_minor', label='Is minor (under 18)')
    
    # Date filters
    date_of_birth = django_filters.DateFilter()
    date_of_birth_after = django_filters.DateFilter(field_name='date_of_birth', lookup_expr='gte')
    date_of_birth_before = django_filters.DateFilter(field_name='date_of_birth', lookup_expr='lte')
    
    # Relationship filters
    relationship_to_user = django_filters.ChoiceFilter(choices=AttendeeRelationship.choices)
    self_registered = django_filters.BooleanFilter(method='filter_self_registered')
    
    # Event filters
    event = CharInFilter(field_name='event__url_safe_title', lookup_expr='in', label='Filter by event slug(s), comma-separated')
    event_title = django_filters.CharFilter(field_name='event__title', lookup_expr='icontains')
    
    # Booking filters
    booking = UUIDInFilter(field_name='booking__booking_id', lookup_expr='in', label='Filter by booking UUID(s), comma-separated')
    has_booking = django_filters.BooleanFilter(method='filter_has_booking')
    
    # Location filters
    area_from = NumberInFilter(field_name='area_from__id', lookup_expr='in', label='Filter by area ID(s), comma-separated')
    area_from_name = django_filters.CharFilter(field_name='area_from__area_name', lookup_expr='icontains')
    
    # Status filters
    is_cancelled = django_filters.BooleanFilter(method='filter_is_cancelled')
    is_registered = django_filters.BooleanFilter(method='filter_is_registered')
    is_checked_in = django_filters.BooleanFilter(method='filter_is_checked_in')
    is_event_staff = django_filters.BooleanFilter(method='filter_is_event_staff')
    
    # Personal information filters
    has_dietary_requirements = django_filters.BooleanFilter(method='filter_has_dietary_requirements')
    dietary_requirement = NumberInFilter(method='filter_dietary_requirement', label='Filter by dietary requirement ID(s), comma-separated')
    
    has_medical_conditions = django_filters.BooleanFilter(method='filter_has_medical_conditions')
    medical_condition = NumberInFilter(method='filter_medical_condition', label='Filter by medical condition ID(s), comma-separated')
    
    has_accessibility_requirements = django_filters.BooleanFilter(method='filter_has_accessibility_requirements')
    accessibility_requirement = NumberInFilter(method='filter_accessibility_requirement', label='Filter by accessibility requirement ID(s), comma-separated')
    
    has_emergency_contacts = django_filters.BooleanFilter(method='filter_has_emergency_contacts')
    
    # Organisation filters
    organisation = NumberInFilter(method='filter_organisation', label='Filter by organisation ID(s), comma-separated')
    organisation_name = django_filters.CharFilter(method='filter_organisation_name')
    
    # Date range filters
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    updated_after = django_filters.DateTimeFilter(field_name='updated_at', lookup_expr='gte')
    updated_before = django_filters.DateTimeFilter(field_name='updated_at', lookup_expr='lte')
    
    # Soft delete filter
    include_deleted = django_filters.BooleanFilter(method='filter_include_deleted')
    
    # Question answer filters
    has_answered_questions = django_filters.BooleanFilter(method='filter_has_answered_questions', label='Has answered any questions')
    question = UUIDInFilter(method='filter_question', label='Filter by question UUID(s), comma-separated')
    question_answer_search = django_filters.CharFilter(method='filter_question_answer_search', label='Search within answer text')
    answered_question_type = CharInFilter(method='filter_answered_question_type', label='Filter by question type(s), comma-separated')
    has_unanswered_required_questions = django_filters.BooleanFilter(method='filter_has_unanswered_required_questions', label='Has incomplete required questions')
    selected_option = NumberInFilter(method='filter_selected_option', label='Filter by selected choice option ID(s), comma-separated')
    answer_submitted_after = django_filters.DateTimeFilter(method='filter_answer_submitted_after', label='Answers submitted after date')
    answer_submitted_before = django_filters.DateTimeFilter(method='filter_answer_submitted_before', label='Answers submitted before date')
    slider_answer_min = django_filters.NumberFilter(method='filter_slider_answer_min', label='Slider answer minimum value')
    slider_answer_max = django_filters.NumberFilter(method='filter_slider_answer_max', label='Slider answer maximum value')
    
    # Order filters
    has_orders = django_filters.BooleanFilter(method='filter_has_orders', label='Has any orders')
    order_status = CharInFilter(method='filter_order_status', label='Filter by order status(es), comma-separated')
    order_status_not = CharInFilter(method='filter_order_status_not', label='Exclude order status(es), comma-separated')
    purchased_product = NumberInFilter(method='filter_purchased_product', label='Filter by purchased product variant ID(s), comma-separated')
    purchased_product_title = django_filters.CharFilter(method='filter_purchased_product_title', label='Search in purchased product titles')
    order_total_min = django_filters.NumberFilter(method='filter_order_total_min', label='Order total minimum amount')
    order_total_max = django_filters.NumberFilter(method='filter_order_total_max', label='Order total maximum amount')
    order_created_after = django_filters.DateTimeFilter(method='filter_order_created_after', label='Orders created after date')
    order_created_before = django_filters.DateTimeFilter(method='filter_order_created_before', label='Orders created before date')
    order_reference_id = django_filters.CharFilter(method='filter_order_reference_id', label='Search by order reference ID')
    has_completed_orders = django_filters.BooleanFilter(method='filter_has_completed_orders', label='Has at least one completed order')
    has_pending_orders = django_filters.BooleanFilter(method='filter_has_pending_orders', label='Has pending or processing orders')

    # Payment filters
    has_payments = django_filters.BooleanFilter(method='filter_has_payments', label='Has any payments')
    payment_id = UUIDInFilter(method='filter_payment_id', label='Filter by payment UUID(s), comma-separated')
    payment_reference = django_filters.CharFilter(method='filter_payment_reference', label='Filter by payment reference')
    bank_transfer_reference = django_filters.CharFilter(method='filter_bank_transfer_reference', label='Filter by bank transfer reference')
    payment_status = CharInFilter(
        method='filter_payment_status',
        label='Filter by payment status(es), comma-separated'
    )
    payment_target = django_filters.ChoiceFilter(method='filter_payment_target', choices=PAYMENT_TARGET_CHOICES, label='Payment target type')
    payment_method_type = CharInFilter(
        method='filter_payment_method_type',
        label='Filter by payment method type(s), comma-separated'
    )
    payment_method_title = django_filters.CharFilter(method='filter_payment_method_title', label='Filter by payment method title')

    # Refund filters
    has_refunds = django_filters.BooleanFilter(method='filter_has_refunds', label='Has any refunds')
    refund_status = CharInFilter(method='filter_refund_status', label='Filter by refund verification status(es), comma-separated')
    refund_is_active = django_filters.BooleanFilter(method='filter_refund_is_active', label='Filter by active refund requests')

    # Donation filters
    has_donations = django_filters.BooleanFilter(method='filter_has_donations', label='Has any donations')
    donation_status = CharInFilter(method='filter_donation_status', label='Filter by donation verification status(es), comma-separated')

    # Discount filters (actual transaction-linked usage)
    has_discounts_used = django_filters.BooleanFilter(method='filter_has_discounts_used', label='Has discounts used in transactions')
    discount_id = UUIDInFilter(method='filter_discount_id', label='Filter by discount UUID(s), comma-separated')
    discount_name = django_filters.CharFilter(method='filter_discount_name', label='Filter by discount name')

    # ── EventForm response filters ─────────────────────────────────────────────
    has_form_responses = django_filters.BooleanFilter(
        method='filter_has_form_responses',
        label='Has any EventForm responses',
    )
    form_response_form = UUIDInFilter(
        method='filter_form_response_form',
        label='Filter by EventForm UUID(s), comma-separated',
    )
    form_response_complete = django_filters.BooleanFilter(
        method='filter_form_response_complete',
        label='Filter by form response completion status',
    )
    form_answer_search = django_filters.CharFilter(
        method='filter_form_answer_search',
        label='Search within EventForm answer text (icontains)',
    )
    form_answered_question = NumberInFilter(
        method='filter_form_answered_question',
        label='Filter by EventForm question ID(s), comma-separated',
    )
    form_answered_question_type = CharInFilter(
        method='filter_form_answered_question_type',
        label='Filter by EventForm question type(s), comma-separated',
    )
    form_has_unanswered_required = django_filters.BooleanFilter(
        method='filter_form_has_unanswered_required',
        label='Has unanswered required EventForm questions (uses is_complete flag)',
    )
    form_selected_option = NumberInFilter(
        method='filter_form_selected_option',
        label='Filter by selected EventForm choice option ID(s), comma-separated',
    )
    form_answer_submitted_after = django_filters.DateTimeFilter(
        method='filter_form_answer_submitted_after',
        label='EventForm answers submitted after this datetime',
    )
    form_answer_submitted_before = django_filters.DateTimeFilter(
        method='filter_form_answer_submitted_before',
        label='EventForm answers submitted before this datetime',
    )
    form_numeric_answer_min = django_filters.NumberFilter(
        method='filter_form_numeric_answer_min',
        label='EventForm slider/rating answer minimum value (numeric cast)',
    )
    form_numeric_answer_max = django_filters.NumberFilter(
        method='filter_form_numeric_answer_max',
        label='EventForm slider/rating answer maximum value (numeric cast)',
    )
    form_answer_date_after = django_filters.DateFilter(
        method='filter_form_answer_date_after',
        label='EventForm date-type answer on or after this date (YYYY-MM-DD)',
    )
    form_answer_date_before = django_filters.DateFilter(
        method='filter_form_answer_date_before',
        label='EventForm date-type answer on or before this date (YYYY-MM-DD)',
    )

    class Meta:
        model = Attendee
        fields = {
            'attendee_display_id': ['exact', 'icontains'],
            'relationship_to_user': ['exact'],
            'gender': ['exact', 'icontains'],
        }

    def _booking_payment_attendee_ids(self, payment_queryset):
        """Return attendee ids whose booking is targeted by the supplied payments."""
        from apps.bookings.models import Booking

        booking_ct = ContentType.objects.get_for_model(Booking)
        booking_ids = payment_queryset.filter(target_type=booking_ct).values_list('target_id', flat=True)
        return Attendee.objects.filter(booking_id__in=list(booking_ids)).values_list('id', flat=True)

    def _filter_attendees_by_payment_queryset(self, queryset, payment_queryset, targets=None):
        """Filter attendees by payment queryset across booking, order, and ticket payment paths."""
        selected_targets = set(targets or {'booking', 'order', 'ticket'})
        attendee_event_ids = queryset.values_list('event_id', flat=True).distinct()
        if attendee_event_ids.exists():
            payment_queryset = payment_queryset.filter(event_id__in=attendee_event_ids)

        criteria = Q()
        if 'ticket' in selected_targets:
            criteria |= Q(tickets__payment__in=payment_queryset)
        if 'order' in selected_targets:
            criteria |= Q(orders__payment__in=payment_queryset)
        if 'booking' in selected_targets:
            criteria |= Q(id__in=self._booking_payment_attendee_ids(payment_queryset))

        if not criteria.children:
            return queryset.none()

        return queryset.filter(criteria).distinct()

    def _filter_attendees_by_discount_queryset(self, queryset, discount_queryset):
        """Filter attendees by discounts linked to booking package or product variant transactions."""
        from apps.bookings.models import BookingPackage

        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        product_variant_ct = ContentType.objects.get_for_model(ProductVariant)

        booking_package_ids = discount_queryset.filter(target_type=booking_package_ct).values_list('target_id', flat=True)
        product_variant_ids = discount_queryset.filter(target_type=product_variant_ct).values_list('target_id', flat=True)

        criteria = (
            Q(tickets__package_id__in=booking_package_ids) |
            Q(orders__booking_package_id__in=booking_package_ids) |
            Q(orders__order_items__product_variant_id__in=product_variant_ids)
        )
        return queryset.filter(criteria).distinct()
    
    def filter_search(self, queryset, name, value):
        """Search across name, email, phone, and display ID."""
        base = queryset.filter(
                    Q(first_name__icontains=value) |
                    Q(last_name__icontains=value) |
                    Q(email__icontains=value) |
                    Q(phone_number__icontains=value) |
                    Q(attendee_display_id__icontains=value)
                )
        # TODO: WARNING: need to ensure similarirty function is enabled on new postgres creation

        if TrigramSimilarity:
            qs = queryset.all().annotate(
                similarity=
                    TrigramSimilarity('first_name', Value(value, output_field=TextField())) + 
                    TrigramSimilarity('last_name', Value(value, output_field=TextField())) 
                    # TrigramSimilarity('email', Value(value, output_field=TextField())) + 
                    # TrigramSimilarity('phone_number', Value(value, output_field=TextField())) + 
                    # TrigramSimilarity('attendee_display_id', Value(value, output_field=TextField()))
            ).filter(similarity__gt=0.3).order_by('-similarity')
            if not qs.exists():
                return base
            return qs.all()
        
        return base

    def filter_full_name(self, queryset, name, value):
        """Search by full name (first + last)."""
        return queryset.filter(
            Q(first_name__icontains=value) | Q(last_name__icontains=value)
        )
    
    def filter_age_min(self, queryset, name, value):
        """Filter by minimum age."""
        from datetime import date
        from dateutil.relativedelta import relativedelta
        max_birth_date = date.today() - relativedelta(years=int(value))
        return queryset.filter(date_of_birth__lte=max_birth_date)
    
    def filter_age_max(self, queryset, name, value):
        """Filter by maximum age."""
        from datetime import date
        from dateutil.relativedelta import relativedelta
        min_birth_date = date.today() - relativedelta(years=int(value) + 1)
        return queryset.filter(date_of_birth__gte=min_birth_date)
    
    def filter_is_minor(self, queryset, name, value):
        """Filter by minor status (under 18)."""
        from datetime import date
        from dateutil.relativedelta import relativedelta
        eighteen_years_ago = date.today() - relativedelta(years=18)
        if value:
            return queryset.filter(date_of_birth__gt=eighteen_years_ago)
        else:
            return queryset.filter(date_of_birth__lte=eighteen_years_ago)
    
    def filter_self_registered(self, queryset, name, value):
        """Filter attendees who self-registered."""
        if value:
            return queryset.filter(relationship_to_user=AttendeeRelationship.SELF, user__isnull=False)
        else:
            return queryset.exclude(relationship_to_user=AttendeeRelationship.SELF, user__isnull=False)
    
    def filter_has_booking(self, queryset, name, value):
        """Filter attendees with/without bookings."""
        if value:
            return queryset.filter(booking__isnull=False)
        else:
            return queryset.filter(booking__isnull=True)
    
    def filter_is_cancelled(self, queryset, name, value):
        """Filter cancelled attendees."""
        if value:
            return queryset.filter(actions__action=AttendeeActionChoices.CANCELLED).distinct()
        else:
            return queryset.exclude(actions__action=AttendeeActionChoices.CANCELLED).distinct()
    
    def filter_is_registered(self, queryset, name, value):
        """Filter registered attendees."""
        if value:
            return queryset.filter(actions__action=AttendeeActionChoices.REGISTERED).distinct()
        else:
            return queryset.exclude(actions__action=AttendeeActionChoices.REGISTERED).distinct()
    
    def filter_is_checked_in(self, queryset, name, value):
        """Filter checked-in attendees."""
        if value:
            return queryset.filter(
                event_attendances__check_in_time__isnull=False,
                event_attendances__check_out_time__isnull=True
            ).distinct()
        else:
            return queryset.exclude(
                event_attendances__check_in_time__isnull=False,
                event_attendances__check_out_time__isnull=True
            ).distinct()
    
    def filter_is_event_staff(self, queryset, name, value):
        """Filter attendees who are event staff."""
        from apps.events.models import EventStaff
        if value:
            return queryset.filter(
                user__isnull=False,
                user__event_staff__event=models.F('event')
            ).distinct()
        else:
            return queryset.exclude(
                user__isnull=False,
                user__event_staff__event=models.F('event')
            ).distinct()
    
    def filter_has_dietary_requirements(self, queryset, name, value):
        """Filter attendees with dietary requirements."""
        if value:
            return queryset.filter(attendeedietaryrequirement__isnull=False).distinct()
        else:
            return queryset.filter(attendeedietaryrequirement__isnull=True).distinct()
    
    def filter_dietary_requirement(self, queryset, name, value):
        """Filter by specific dietary requirement(s)."""
        return queryset.filter(attendeedietaryrequirement__dietary_requirement__id__in=value).distinct()
    
    def filter_has_medical_conditions(self, queryset, name, value):
        """Filter attendees with medical conditions."""
        if value:
            return queryset.filter(attendeemedicalcondition__isnull=False).distinct()
        else:
            return queryset.filter(attendeemedicalcondition__isnull=True).distinct()
    
    def filter_medical_condition(self, queryset, name, value):
        """Filter by specific medical condition(s)."""
        return queryset.filter(attendeemedicalcondition__medical_condition__id__in=value).distinct()
    
    def filter_has_accessibility_requirements(self, queryset, name, value):
        """Filter attendees with accessibility requirements."""
        if value:
            return queryset.filter(attendeeaccessibilityrequirement__isnull=False).distinct()
        else:
            return queryset.filter(attendeeaccessibilityrequirement__isnull=True).distinct()
    
    def filter_accessibility_requirement(self, queryset, name, value):
        """Filter by specific accessibility requirement(s)."""
        return queryset.filter(
            attendeeaccessibilityrequirement__accessibility_requirement__id__in=value
        ).distinct()
    
    def filter_has_emergency_contacts(self, queryset, name, value):
        """Filter attendees with emergency contacts."""
        if value:
            return queryset.filter(emergency_contacts__isnull=False).distinct()
        else:
            return queryset.filter(emergency_contacts__isnull=True).distinct()
    
    def filter_organisation(self, queryset, name, value):
        """Filter by organisation ID(s)."""
        return queryset.filter(organisations__organisation__id__in=value).distinct()
    
    def filter_organisation_name(self, queryset, name, value):
        """Filter by organisation name."""
        return queryset.filter(organisations__organisation__title__icontains=value).distinct()
    
    def filter_include_deleted(self, queryset, name, value):
        """Include or exclude soft-deleted attendees."""
        if value:
            return queryset.all()  # Include deleted
        else:
            return queryset.filter(deleted_at__isnull=True)  # Exclude deleted
    
    # Question answer filter methods
    def filter_has_answered_questions(self, queryset, name, value):
        """Filter attendees who have answered any questions."""
        if value:
            return queryset.filter(question_answers__isnull=False).distinct()
        else:
            return queryset.filter(question_answers__isnull=True).distinct()
    
    def filter_question(self, queryset, name, value):
        """Filter attendees who answered specific question(s)."""
        return queryset.filter(question_answers__question__id__in=value).distinct()
    
    def filter_question_answer_search(self, queryset, name, value):
        """Search within question answer text."""
        return queryset.filter(question_answers__answer_text__icontains=value).distinct()
    
    def filter_answered_question_type(self, queryset, name, value):
        """Filter attendees who answered questions of specific type(s)."""
        valid = {c[0] for c in EventQuestionTypeChoices.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset
        return queryset.filter(question_answers__question__question_type__in=values).distinct()
    
    def filter_has_unanswered_required_questions(self, queryset, name, value):
        """Filter attendees with incomplete required questions for their event."""
        if value:
            # Get attendees who have required questions in their event that they haven't answered
            return queryset.filter(
                event__questions__required=True
            ).exclude(
                question_answers__question__in=Q(event__questions__required=True)
            ).distinct()
        else:
            # Get attendees who have answered all required questions
            # This is complex - for now, return attendees who have at least one answer
            return queryset.filter(question_answers__question__required=True).distinct()
    
    def filter_selected_option(self, queryset, name, value):
        """Filter attendees who selected specific choice option(s)."""
        return queryset.filter(
            question_answers__selected_options__option__id__in=value
        ).distinct()
    
    def filter_answer_submitted_after(self, queryset, name, value):
        """Filter attendees who submitted answers after a specific date."""
        return queryset.filter(question_answers__submitted_at__gte=value).distinct()
    
    def filter_answer_submitted_before(self, queryset, name, value):
        """Filter attendees who submitted answers before a specific date."""
        return queryset.filter(question_answers__submitted_at__lte=value).distinct()
    
    def filter_slider_answer_min(self, queryset, name, value):
        """Filter attendees whose slider answers are at least the specified value."""
        return queryset.filter(
            question_answers__question__question_type=EventQuestionTypeChoices.SLIDER,
            question_answers__answer_text__gte=str(value)
        ).distinct()
    
    def filter_slider_answer_max(self, queryset, name, value):
        """Filter attendees whose slider answers are at most the specified value."""
        return queryset.filter(
            question_answers__question__question_type=EventQuestionTypeChoices.SLIDER,
            question_answers__answer_text__lte=str(value)
        ).distinct()
    
    # Order filter methods
    def filter_has_orders(self, queryset, name, value):
        """Filter attendees with any orders."""
        if value:
            return queryset.filter(orders__isnull=False).distinct()
        else:
            return queryset.filter(orders__isnull=True).distinct()
    
    def filter_order_status(self, queryset, name, value):
        """Filter attendees with orders in specific status(es)."""
        valid = {c[0] for c in OrderStatusChoices.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset
        return queryset.filter(orders__status__in=values).distinct()
    
    def filter_order_status_not(self, queryset, name, value):
        """Exclude attendees with orders in specific status(es)."""
        valid = {c[0] for c in OrderStatusChoices.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset
        return queryset.exclude(orders__status__in=values).distinct()
    
    def filter_purchased_product(self, queryset, name, value):
        """Filter attendees who purchased specific product variant(s)."""
        return queryset.filter(
            orders__order_items__product_variant__id__in=value
        ).distinct()
    
    def filter_purchased_product_title(self, queryset, name, value):
        """Search attendees by purchased product titles."""
        return queryset.filter(
            orders__order_items__product_variant__product__title__icontains=value
        ).distinct()
    
    def filter_order_total_min(self, queryset, name, value):
        """Filter attendees with orders totaling at least the specified amount."""
        return queryset.filter(orders__total_amount__gte=value).distinct()
    
    def filter_order_total_max(self, queryset, name, value):
        """Filter attendees with orders totaling at most the specified amount."""
        return queryset.filter(orders__total_amount__lte=value).distinct()
    
    def filter_order_created_after(self, queryset, name, value):
        """Filter attendees with orders created after a specific date."""
        return queryset.filter(orders__created_at__gte=value).distinct()
    
    def filter_order_created_before(self, queryset, name, value):
        """Filter attendees with orders created before a specific date."""
        return queryset.filter(orders__created_at__lte=value).distinct()
    
    def filter_order_reference_id(self, queryset, name, value):
        """Search attendees by order reference ID."""
        return queryset.filter(orders__order_reference_id__icontains=value).distinct()
    
    def filter_has_completed_orders(self, queryset, name, value):
        """Filter attendees with at least one completed order."""
        if value:
            return queryset.filter(orders__status=OrderStatusChoices.COMPLETED).distinct()
        else:
            return queryset.exclude(orders__status=OrderStatusChoices.COMPLETED).distinct()
    
    def filter_has_pending_orders(self, queryset, name, value):
        """Filter attendees with pending or processing orders."""
        if value:
            return queryset.filter(
                Q(orders__status=OrderStatusChoices.PENDING) |
                Q(orders__status=OrderStatusChoices.PROCESSING)
            ).distinct()
        else:
            return queryset.exclude(
                Q(orders__status=OrderStatusChoices.PENDING) |
                Q(orders__status=OrderStatusChoices.PROCESSING)
            ).distinct()

    # Payment filter methods
    def filter_has_payments(self, queryset, name, value):
        """Filter attendees with any linked payments."""
        from apps.payments.models import Payment

        matched = self._filter_attendees_by_payment_queryset(queryset, Payment.objects.all())
        if value:
            return matched
        return queryset.exclude(id__in=matched.values_list('id', flat=True)).distinct()

    def filter_payment_id(self, queryset, name, value):
        """Filter attendees by payment UUID(s)."""
        from apps.payments.models import Payment
        return self._filter_attendees_by_payment_queryset(queryset, Payment.objects.filter(payment_id__in=value))

    def filter_payment_reference(self, queryset, name, value):
        """Filter attendees by payment reference."""
        from apps.payments.models import Payment
        return self._filter_attendees_by_payment_queryset(queryset, Payment.objects.filter(payment_reference__icontains=value))

    def filter_bank_transfer_reference(self, queryset, name, value):
        """Filter attendees by bank transfer reference."""
        from apps.payments.models import Payment
        return self._filter_attendees_by_payment_queryset(queryset, Payment.objects.filter(bank_transfer_reference__icontains=value))

    def filter_payment_status(self, queryset, name, value):
        """Filter attendees by payment status(es)."""
        from apps.payments.models import Payment

        valid = {c[0] for c in PaymentStatusChoices.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset

        selected_target = self.form.cleaned_data.get('payment_target')
        valid_targets = {choice[0] for choice in PAYMENT_TARGET_CHOICES}
        if selected_target in valid_targets:
            targets = {selected_target}
        else:
            targets = {'booking'}

        return self._filter_attendees_by_payment_queryset(
            queryset,
            Payment.objects.filter(status__in=values),
            targets=targets,
        )

    def filter_payment_target(self, queryset, name, value):
        """Filter attendees by payment target type without exposing GenericFK internals."""
        from apps.payments.models import Payment
        return self._filter_attendees_by_payment_queryset(queryset, Payment.objects.all(), targets={value})

    def filter_payment_method_type(self, queryset, name, value):
        """Filter attendees by payment method type(s)."""
        from apps.payments.models import Payment
        valid = {c[0] for c in PaymentMethodTypeChoices.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset
        return self._filter_attendees_by_payment_queryset(queryset, Payment.objects.filter(method__method_type__in=values))

    def filter_payment_method_title(self, queryset, name, value):
        """Filter attendees by payment method title."""
        from apps.payments.models import Payment
        return self._filter_attendees_by_payment_queryset(queryset, Payment.objects.filter(method__title__icontains=value))

    # Refund filter methods
    def filter_has_refunds(self, queryset, name, value):
        """Filter attendees with any refunds linked to their payments."""
        from apps.payments.models import Payment

        matched = self._filter_attendees_by_payment_queryset(
            queryset,
            Payment.objects.filter(refund_requests__isnull=False).distinct()
        )
        if value:
            return matched
        return queryset.exclude(id__in=matched.values_list('id', flat=True)).distinct()

    def filter_refund_status(self, queryset, name, value):
        """Filter attendees by refund verification status(es)."""
        from apps.payments.models import Payment
        valid = {c[0] for c in VerificationStatus.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset
        return self._filter_attendees_by_payment_queryset(
            queryset,
            Payment.objects.filter(refund_requests__verification_status__in=values).distinct()
        )

    def filter_refund_is_active(self, queryset, name, value):
        """Filter attendees by active/inactive refund requests."""
        from apps.payments.models import Payment
        return self._filter_attendees_by_payment_queryset(
            queryset,
            Payment.objects.filter(refund_requests__is_active=value).distinct()
        )

    # Donation filter methods
    def filter_has_donations(self, queryset, name, value):
        """Filter attendees with any donations linked to their payments."""
        from apps.payments.models import Payment

        matched = self._filter_attendees_by_payment_queryset(
            queryset,
            Payment.objects.filter(donations__isnull=False).distinct()
        )
        if value:
            return matched
        return queryset.exclude(id__in=matched.values_list('id', flat=True)).distinct()

    def filter_donation_status(self, queryset, name, value):
        """Filter attendees by donation verification status(es)."""
        from apps.payments.models import Payment
        valid = {c[0] for c in VerificationStatus.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset
        return self._filter_attendees_by_payment_queryset(
            queryset,
            Payment.objects.filter(donations__verification_status__in=values).distinct()
        )

    # Discount filter methods
    def filter_has_discounts_used(self, queryset, name, value):
        """Filter attendees that used transaction-linked discounts."""
        from apps.payments.models import Discount

        matched = self._filter_attendees_by_discount_queryset(queryset, Discount.objects.all())
        if value:
            return matched
        return queryset.exclude(id__in=matched.values_list('id', flat=True)).distinct()

    def filter_discount_id(self, queryset, name, value):
        """Filter attendees by discount UUID(s) used in transaction-linked entities."""
        from apps.payments.models import Discount
        return self._filter_attendees_by_discount_queryset(
            queryset,
            Discount.objects.filter(discount_id__in=value)
        )

    def filter_discount_name(self, queryset, name, value):
        """Filter attendees by discount name used in transaction-linked entities."""
        from apps.payments.models import Discount
        return self._filter_attendees_by_discount_queryset(
            queryset,
            Discount.objects.filter(name__icontains=value)
        )

    # ── EventForm response filter methods ─────────────────────────────────────

    def filter_has_form_responses(self, queryset, name, value):
        """Filter attendees who have (or have not) submitted any EventForm responses."""
        if value:
            return queryset.filter(form_responses__isnull=False).distinct()
        return queryset.filter(form_responses__isnull=True).distinct()

    def filter_form_response_form(self, queryset, name, value):
        """Filter attendees who responded to specific EventForm(s) by UUID."""
        return queryset.filter(form_responses__form__id__in=value).distinct()

    def filter_form_response_complete(self, queryset, name, value):
        """Filter attendees by whether their form response is marked complete."""
        return queryset.filter(form_responses__is_complete=value).distinct()

    def filter_form_answer_search(self, queryset, name, value):
        """Search attendees by text within their EventForm answer_text fields."""
        return queryset.filter(
            form_responses__answers__answer_text__icontains=value
        ).distinct()

    def filter_form_answered_question(self, queryset, name, value):
        """Filter attendees who answered specific EventForm question(s) by ID."""
        return queryset.filter(
            form_responses__answers__question__id__in=value
        ).distinct()

    def filter_form_answered_question_type(self, queryset, name, value):
        """Filter attendees who answered EventForm questions of specific type(s)."""
        valid = {c[0] for c in EventFormQuestionTypeChoices.choices}
        values = [v for v in value if v in valid]
        if not values:
            return queryset
        return queryset.filter(
            form_responses__answers__question__question_type__in=values
        ).distinct()

    def filter_form_has_unanswered_required(self, queryset, name, value):
        """Filter attendees with incomplete (is_complete=False) EventForm responses."""
        if value:
            return queryset.filter(
                form_responses__isnull=False,
                form_responses__is_complete=False,
            ).distinct()
        return queryset.exclude(
            form_responses__isnull=False,
            form_responses__is_complete=False,
        ).distinct()

    def filter_form_selected_option(self, queryset, name, value):
        """Filter attendees who selected specific EventForm choice option(s) by ID."""
        return queryset.filter(
            form_responses__answers__selected_options__option__id__in=value
        ).distinct()

    def filter_form_answer_submitted_after(self, queryset, name, value):
        """Filter attendees who submitted EventForm answers after a specific datetime."""
        return queryset.filter(
            form_responses__answers__submitted_at__gte=value
        ).distinct()

    def filter_form_answer_submitted_before(self, queryset, name, value):
        """Filter attendees who submitted EventForm answers before a specific datetime."""
        return queryset.filter(
            form_responses__answers__submitted_at__lte=value
        ).distinct()

    def filter_form_numeric_answer_min(self, queryset, name, value):
        """Filter by EventForm slider/rating answers >= value (numeric cast)."""
        from apps.events.models.forms.responses import EventFormResponseAnswer
        from django.db.models.functions import Cast
        from django.db.models import IntegerField

        range_types = list(EventFormQuestionTypeChoices.range_types())
        matching = (
            EventFormResponseAnswer.objects
            .filter(
                question__question_type__in=range_types,
                answer_text__regex=r'^-?\d+$',
            )
            .annotate(numeric_val=Cast('answer_text', output_field=IntegerField()))
            .filter(numeric_val__gte=value)
            .values('response__attendee_id')
        )
        return queryset.filter(id__in=matching).distinct()

    def filter_form_numeric_answer_max(self, queryset, name, value):
        """Filter by EventForm slider/rating answers <= value (numeric cast)."""
        from apps.events.models.forms.responses import EventFormResponseAnswer
        from django.db.models.functions import Cast
        from django.db.models import IntegerField

        range_types = list(EventFormQuestionTypeChoices.range_types())
        matching = (
            EventFormResponseAnswer.objects
            .filter(
                question__question_type__in=range_types,
                answer_text__regex=r'^-?\d+$',
            )
            .annotate(numeric_val=Cast('answer_text', output_field=IntegerField()))
            .filter(numeric_val__lte=value)
            .values('response__attendee_id')
        )
        return queryset.filter(id__in=matching).distinct()

    def filter_form_answer_date_after(self, queryset, name, value):
        """Filter by EventForm DATE-type answers on or after the given date."""
        return queryset.filter(
            form_responses__answers__question__question_type=EventFormQuestionTypeChoices.DATE,
            form_responses__answers__answer_text__gte=value.isoformat(),
        ).distinct()

    def filter_form_answer_date_before(self, queryset, name, value):
        """Filter by EventForm DATE-type answers on or before the given date."""
        return queryset.filter(
            form_responses__answers__question__question_type=EventFormQuestionTypeChoices.DATE,
            form_responses__answers__answer_text__lte=value.isoformat(),
        ).distinct()


class AttendeeGuardianFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeGuardian."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    user = django_filters.NumberFilter(field_name='user__id')
    relationship = django_filters.ChoiceFilter(choices=AttendeeRelationship.choices)
    
    class Meta:
        model = AttendeeGuardian
        fields = ['attendee', 'user', 'relationship']


class AttendeeActionFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeAction."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    action = django_filters.ChoiceFilter(choices=AttendeeActionChoices.choices)
    performed_after = django_filters.DateTimeFilter(field_name='performed_at', lookup_expr='gte')
    performed_before = django_filters.DateTimeFilter(field_name='performed_at', lookup_expr='lte')
    
    class Meta:
        model = AttendeeAction
        fields = ['attendee', 'action', 'performed_by']


class FamilyGroupFilterSet(django_filters.FilterSet):
    """FilterSet for FamilyGroup."""
    
    family_name = django_filters.CharFilter(lookup_expr='icontains')
    created_by = django_filters.NumberFilter(field_name='created_by__id')
    event = django_filters.CharFilter(field_name='event__url_safe_title')
    organisation = django_filters.NumberFilter(field_name='organisation__id')
    
    class Meta:
        model = FamilyGroup
        fields = ['family_name', 'created_by', 'event', 'organisation']


class FamilyAttendeeFilterSet(django_filters.FilterSet):
    """FilterSet for FamilyAttendee."""
    
    family_group = django_filters.NumberFilter(field_name='family_group__id')
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    event = django_filters.CharFilter(field_name='family_group__event__url_safe_title')
    organisation = django_filters.NumberFilter(field_name='family_group__organisation__id')
    relationship = django_filters.ChoiceFilter(choices=HumanRelationshipChoices.choices)
    is_primary_guardian = django_filters.BooleanFilter()
    
    class Meta:
        model = FamilyAttendee
        fields = ['family_group', 'attendee', 'event', 'organisation', 'relationship', 'is_primary_guardian']


class AttendeeMessageFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeMessage."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    priority = django_filters.ChoiceFilter(choices=AttendeeMessagePriority.choices)
    is_responded = django_filters.BooleanFilter(method='filter_is_responded')
    submitted_after = django_filters.DateTimeFilter(field_name='submitted_at', lookup_expr='gte')
    submitted_before = django_filters.DateTimeFilter(field_name='submitted_at', lookup_expr='lte')
    
    class Meta:
        model = AttendeeMessage
        fields = ['attendee', 'priority', 'responsed_by']
    
    def filter_is_responded(self, queryset, name, value):
        """Filter by response status."""
        if value:
            return queryset.filter(responsed_at__isnull=False)
        else:
            return queryset.filter(responsed_at__isnull=True)


class AccessibilityRequirementFilterSet(django_filters.FilterSet):
    """FilterSet for AccessibilityRequirement."""
    
    code = django_filters.CharFilter(lookup_expr='iexact')
    label = django_filters.CharFilter(lookup_expr='icontains')
    active = django_filters.BooleanFilter()
    verification_status = django_filters.ChoiceFilter(choices=VerificationStatus.choices)
    
    class Meta:
        model = AccessibilityRequirement
        fields = ['code', 'label', 'active', 'verification_status']


class AttendeeAccessibilityRequirementFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeAccessibilityRequirement."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    accessibility_requirement = django_filters.NumberFilter(field_name='accessibility_requirement__id')
    verification_status = django_filters.ChoiceFilter(choices=VerificationStatus.choices)
    
    class Meta:
        model = AttendeeAccessibilityRequirement
        fields = ['attendee', 'accessibility_requirement', 'verification_status']


class DietaryRequirementFilterSet(django_filters.FilterSet):
    """FilterSet for DietaryRequirement."""
    
    code = django_filters.CharFilter(lookup_expr='iexact')
    label = django_filters.CharFilter(lookup_expr='icontains')
    active = django_filters.BooleanFilter()
    verification_status = django_filters.ChoiceFilter(choices=VerificationStatus.choices)
    
    class Meta:
        model = DietaryRequirement
        fields = ['code', 'label', 'active', 'verification_status']


class AttendeeDietaryRequirementFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeDietaryRequirement."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    dietary_requirement = django_filters.NumberFilter(field_name='dietary_requirement__id')
    verification_status = django_filters.ChoiceFilter(choices=VerificationStatus.choices)
    
    class Meta:
        model = AttendeeDietaryRequirement
        fields = ['attendee', 'dietary_requirement', 'verification_status']


class MedicalConditionFilterSet(django_filters.FilterSet):
    """FilterSet for MedicalCondition."""
    
    code = django_filters.CharFilter(lookup_expr='iexact')
    label = django_filters.CharFilter(lookup_expr='icontains')
    active = django_filters.BooleanFilter()
    verification_status = django_filters.ChoiceFilter(choices=VerificationStatus.choices)
    
    class Meta:
        model = MedicalCondition
        fields = ['code', 'label', 'active', 'verification_status']


class AttendeeMedicalConditionFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeMedicalCondition."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    medical_condition = django_filters.NumberFilter(field_name='medical_condition__id')
    verification_status = django_filters.ChoiceFilter(choices=VerificationStatus.choices)
    
    class Meta:
        model = AttendeeMedicalCondition
        fields = ['attendee', 'medical_condition', 'verification_status']


class EmergencyContactFilterSet(django_filters.FilterSet):
    """FilterSet for EmergencyContact."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    relationship = django_filters.ChoiceFilter(choices=HumanRelationshipChoices.choices)
    primary_contact = django_filters.BooleanFilter()
    verification_status = django_filters.ChoiceFilter(choices=VerificationStatus.choices)
    
    search = django_filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EmergencyContact
        fields = ['attendee', 'relationship', 'primary_contact', 'verification_status']
    
    def filter_search(self, queryset, name, value):
        """Search by name, phone, or email."""
        return queryset.filter(
            Q(first_name__icontains=value) |
            Q(last_name__icontains=value) |
            Q(phone_number__icontains=value) |
            Q(email__icontains=value)
        )


class ConsentFilterSet(django_filters.FilterSet):
    """FilterSet for Consent."""
    
    event = django_filters.CharFilter(field_name='event__url_safe_title')
    code = django_filters.CharFilter(lookup_expr='iexact')
    title = django_filters.CharFilter(lookup_expr='icontains')
    required = django_filters.BooleanFilter()
    active = django_filters.BooleanFilter()
    
    class Meta:
        model = Consent
        fields = ['event', 'code', 'title', 'required', 'active']


class AttendeeConsentFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeConsent."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    consent = django_filters.NumberFilter(field_name='consent__id')
    consent_given = django_filters.BooleanFilter()
    
    class Meta:
        model = AttendeeConsent
        fields = ['attendee', 'consent', 'consent_given']


class EventAttendanceFilterSet(django_filters.FilterSet):
    """FilterSet for EventAttendance."""
    
    event = django_filters.CharFilter(field_name='event__url_safe_title')
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    is_checked_in = django_filters.BooleanFilter(method='filter_is_checked_in')
    is_checked_out = django_filters.BooleanFilter(method='filter_is_checked_out')
    
    class Meta:
        model = EventAttendance
        fields = ['event', 'attendee']
    
    def filter_is_checked_in(self, queryset, name, value):
        """Filter by check-in status."""
        if value:
            return queryset.filter(
                check_in_time__isnull=False
            ).filter(
                Q(check_out_time__isnull=True) | Q(check_out_time__gt=models.F('check_in_time'))
            )
        else:
            return queryset.filter(check_in_time__isnull=True)
    
    def filter_is_checked_out(self, queryset, name, value):
        """Filter by check-out status."""
        if value:
            return queryset.filter(
                check_out_time__isnull=False
            ).filter(
                Q(check_in_time__isnull=True) | Q(check_out_time__gt=models.F('check_in_time'))
            )
        else:
            return queryset.filter(check_out_time__isnull=True)


class AttendeeOrganisationFilterSet(django_filters.FilterSet):
    """FilterSet for AttendeeOrganisation."""
    
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    organisation = django_filters.NumberFilter(field_name='organisation__id')
    
    class Meta:
        model = AttendeeOrganisation
        fields = ['attendee', 'organisation']

