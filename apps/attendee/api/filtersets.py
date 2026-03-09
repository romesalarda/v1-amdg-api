"""
FilterSets for the attendee app.

Provides comprehensive filtering capabilities for attendee search and queries,
including advanced search by personal information.
"""
import django_filters
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
from apps.events.models import EventQuestion, EventQuestionAnswer, EventQuestionOption, EventQuestionTypeChoices
from apps.products.models import Order, OrderItem, OrderStatusChoices


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
    event = django_filters.UUIDFilter(field_name='event__event_id')
    event_title = django_filters.CharFilter(field_name='event__title', lookup_expr='icontains')
    
    # Booking filters
    booking = django_filters.UUIDFilter(field_name='booking__booking_id')
    has_booking = django_filters.BooleanFilter(method='filter_has_booking')
    
    # Location filters
    area_from = django_filters.NumberFilter(field_name='area_from__id')
    area_from_name = django_filters.CharFilter(field_name='area_from__area_name', lookup_expr='icontains')
    
    # Status filters
    is_cancelled = django_filters.BooleanFilter(method='filter_is_cancelled')
    is_registered = django_filters.BooleanFilter(method='filter_is_registered')
    is_checked_in = django_filters.BooleanFilter(method='filter_is_checked_in')
    is_event_staff = django_filters.BooleanFilter(method='filter_is_event_staff')
    
    # Personal information filters
    has_dietary_requirements = django_filters.BooleanFilter(method='filter_has_dietary_requirements')
    dietary_requirement = django_filters.NumberFilter(method='filter_dietary_requirement')
    
    has_medical_conditions = django_filters.BooleanFilter(method='filter_has_medical_conditions')
    medical_condition = django_filters.NumberFilter(method='filter_medical_condition')
    
    has_accessibility_requirements = django_filters.BooleanFilter(method='filter_has_accessibility_requirements')
    accessibility_requirement = django_filters.NumberFilter(method='filter_accessibility_requirement')
    
    has_emergency_contacts = django_filters.BooleanFilter(method='filter_has_emergency_contacts')
    
    # Organisation filters
    organisation = django_filters.NumberFilter(method='filter_organisation')
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
    question = django_filters.UUIDFilter(method='filter_question', label='Filter by specific question UUID')
    question_answer_search = django_filters.CharFilter(method='filter_question_answer_search', label='Search within answer text')
    answered_question_type = django_filters.ChoiceFilter(method='filter_answered_question_type', choices=EventQuestionTypeChoices.choices, label='Filter by question type')
    has_unanswered_required_questions = django_filters.BooleanFilter(method='filter_has_unanswered_required_questions', label='Has incomplete required questions')
    selected_option = django_filters.NumberFilter(method='filter_selected_option', label='Filter by selected choice option ID')
    answer_submitted_after = django_filters.DateTimeFilter(method='filter_answer_submitted_after', label='Answers submitted after date')
    answer_submitted_before = django_filters.DateTimeFilter(method='filter_answer_submitted_before', label='Answers submitted before date')
    slider_answer_min = django_filters.NumberFilter(method='filter_slider_answer_min', label='Slider answer minimum value')
    slider_answer_max = django_filters.NumberFilter(method='filter_slider_answer_max', label='Slider answer maximum value')
    
    # Order filters
    has_orders = django_filters.BooleanFilter(method='filter_has_orders', label='Has any orders')
    order_status = django_filters.ChoiceFilter(method='filter_order_status', choices=OrderStatusChoices.choices, label='Filter by order status')
    order_status_not = django_filters.ChoiceFilter(method='filter_order_status_not', choices=OrderStatusChoices.choices, label='Exclude order status')
    purchased_product = django_filters.NumberFilter(method='filter_purchased_product', label='Filter by purchased product variant ID')
    purchased_product_title = django_filters.CharFilter(method='filter_purchased_product_title', label='Search in purchased product titles')
    order_total_min = django_filters.NumberFilter(method='filter_order_total_min', label='Order total minimum amount')
    order_total_max = django_filters.NumberFilter(method='filter_order_total_max', label='Order total maximum amount')
    order_created_after = django_filters.DateTimeFilter(method='filter_order_created_after', label='Orders created after date')
    order_created_before = django_filters.DateTimeFilter(method='filter_order_created_before', label='Orders created before date')
    order_reference_id = django_filters.CharFilter(method='filter_order_reference_id', label='Search by order reference ID')
    has_completed_orders = django_filters.BooleanFilter(method='filter_has_completed_orders', label='Has at least one completed order')
    has_pending_orders = django_filters.BooleanFilter(method='filter_has_pending_orders', label='Has pending or processing orders')
    
    class Meta:
        model = Attendee
        fields = {
            'attendee_display_id': ['exact', 'icontains'],
            'relationship_to_user': ['exact'],
            'gender': ['exact', 'icontains'],
        }
    
    def filter_search(self, queryset, name, value):
        """Search across name, email, phone, and display ID."""
        return queryset.filter(
            Q(first_name__icontains=value) |
            Q(last_name__icontains=value) |
            Q(email__icontains=value) |
            Q(phone_number__icontains=value) |
            Q(attendee_display_id__icontains=value)
        )
    
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
        """Filter by specific dietary requirement."""
        return queryset.filter(attendeedietaryrequirement__dietary_requirement__id=value).distinct()
    
    def filter_has_medical_conditions(self, queryset, name, value):
        """Filter attendees with medical conditions."""
        if value:
            return queryset.filter(attendeemedicalcondition__isnull=False).distinct()
        else:
            return queryset.filter(attendeemedicalcondition__isnull=True).distinct()
    
    def filter_medical_condition(self, queryset, name, value):
        """Filter by specific medical condition."""
        return queryset.filter(attendeemedicalcondition__medical_condition__id=value).distinct()
    
    def filter_has_accessibility_requirements(self, queryset, name, value):
        """Filter attendees with accessibility requirements."""
        if value:
            return queryset.filter(attendeeaccessibilityrequirement__isnull=False).distinct()
        else:
            return queryset.filter(attendeeaccessibilityrequirement__isnull=True).distinct()
    
    def filter_accessibility_requirement(self, queryset, name, value):
        """Filter by specific accessibility requirement."""
        return queryset.filter(
            attendeeaccessibilityrequirement__accessibility_requirement__id=value
        ).distinct()
    
    def filter_has_emergency_contacts(self, queryset, name, value):
        """Filter attendees with emergency contacts."""
        if value:
            return queryset.filter(emergency_contacts__isnull=False).distinct()
        else:
            return queryset.filter(emergency_contacts__isnull=True).distinct()
    
    def filter_organisation(self, queryset, name, value):
        """Filter by organisation ID."""
        return queryset.filter(organisations__organisation__id=value).distinct()
    
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
        """Filter attendees who answered a specific question."""
        return queryset.filter(question_answers__question__id=value).distinct()
    
    def filter_question_answer_search(self, queryset, name, value):
        """Search within question answer text."""
        return queryset.filter(question_answers__answer_text__icontains=value).distinct()
    
    def filter_answered_question_type(self, queryset, name, value):
        """Filter attendees who answered questions of a specific type."""
        return queryset.filter(question_answers__question__question_type=value).distinct()
    
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
        """Filter attendees who selected a specific choice option."""
        return queryset.filter(
            question_answers__selected_options__option__id=value
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
        """Filter attendees with orders in a specific status."""
        return queryset.filter(orders__status=value).distinct()
    
    def filter_order_status_not(self, queryset, name, value):
        """Exclude attendees with orders in a specific status."""
        return queryset.exclude(orders__status=value).distinct()
    
    def filter_purchased_product(self, queryset, name, value):
        """Filter attendees who purchased a specific product variant."""
        return queryset.filter(
            orders__order_items__product_variant__id=value
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
    
    class Meta:
        model = FamilyGroup
        fields = ['family_name', 'created_by']


class FamilyAttendeeFilterSet(django_filters.FilterSet):
    """FilterSet for FamilyAttendee."""
    
    family_group = django_filters.NumberFilter(field_name='family_group__id')
    attendee = django_filters.UUIDFilter(field_name='attendee__attendee_id')
    relationship = django_filters.ChoiceFilter(choices=HumanRelationshipChoices.choices)
    is_primary_guardian = django_filters.BooleanFilter()
    
    class Meta:
        model = FamilyAttendee
        fields = ['family_group', 'attendee', 'relationship', 'is_primary_guardian']


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
    
    event = django_filters.UUIDFilter(field_name='event__event_id')
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
    
    event = django_filters.UUIDFilter(field_name='event__event_id')
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


# Import models for filter methods
from django.db import models
from apps.attendee.models.groups import HumanRelationshipChoices
