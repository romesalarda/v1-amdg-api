"""
Serializers for the POST /api/attendees/filter/ endpoint.

Provides type-aware validation for structured filter bodies, replacing the flat
GET query param approach with a nested JSON structure that supports per-question
conditions for both EventForm responses and registration questions.
"""
from rest_framework import serializers


# ── Question type constants ───────────────────────────────────────────────────

FORM_QUESTION_TYPE_TEXT = ('short_answer', 'long_answer', 'email', 'phone')
FORM_QUESTION_TYPE_CHOICE = ('single_choice', 'multiple_choice')
FORM_QUESTION_TYPE_RANGE = ('slider', 'rating')
FORM_QUESTION_TYPE_DATE = ('date',)
FORM_QUESTION_TYPE_TIME = ('time',)
FORM_QUESTION_TYPE_UPLOAD = ('upload',)

VALID_FORM_QUESTION_TYPES = (
    FORM_QUESTION_TYPE_TEXT
    + FORM_QUESTION_TYPE_CHOICE
    + FORM_QUESTION_TYPE_RANGE
    + FORM_QUESTION_TYPE_DATE
    + FORM_QUESTION_TYPE_TIME
    + FORM_QUESTION_TYPE_UPLOAD
)

# Registration questions support a subset of types
VALID_REG_QUESTION_TYPES = ('short_answer', 'long_answer', 'upload', 'single_choice', 'multiple_choice', 'slider')


# ── Per-question condition serializer ────────────────────────────────────────

class FormQuestionConditionSerializer(serializers.Serializer):
    """
    Validates a single per-question condition for an EventForm question.

    The `type` field drives which filter fields are permitted:
      - text/email/phone  → contains
      - choice            → selected_options (list of option IDs)
      - slider/rating     → min, max
      - date              → date_after, date_before
      - time              → time_after, time_before
      - upload            → submitted_after, submitted_before
    """
    question_id = serializers.IntegerField(min_value=1)
    type = serializers.ChoiceField(choices=list(VALID_FORM_QUESTION_TYPES))

    # Text
    contains = serializers.CharField(required=False, allow_blank=False, max_length=500)

    # Choice
    selected_options = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
        max_length=200,
    )

    # Range (slider / rating)
    min = serializers.IntegerField(required=False)
    max = serializers.IntegerField(required=False)

    # Date
    date_after = serializers.DateField(required=False)
    date_before = serializers.DateField(required=False)

    # Time
    time_after = serializers.TimeField(required=False)
    time_before = serializers.TimeField(required=False)

    # Upload / submission date (also valid for any type)
    submitted_after = serializers.DateTimeField(required=False)
    submitted_before = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        q_type = attrs['type']
        errors = {}

        # Disallow irrelevant fields per type
        if q_type in FORM_QUESTION_TYPE_TEXT:
            for f in ('selected_options', 'min', 'max', 'date_after', 'date_before', 'time_after', 'time_before'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."

        elif q_type in FORM_QUESTION_TYPE_CHOICE:
            for f in ('contains', 'min', 'max', 'date_after', 'date_before', 'time_after', 'time_before'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."

        elif q_type in FORM_QUESTION_TYPE_RANGE:
            for f in ('contains', 'selected_options', 'date_after', 'date_before', 'time_after', 'time_before'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."
            if 'min' in attrs and 'max' in attrs and attrs['min'] > attrs['max']:
                errors['min'] = "min must be less than or equal to max."

        elif q_type in FORM_QUESTION_TYPE_DATE:
            for f in ('contains', 'selected_options', 'min', 'max', 'time_after', 'time_before'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."
            if 'date_after' in attrs and 'date_before' in attrs and attrs['date_after'] > attrs['date_before']:
                errors['date_after'] = "date_after must be on or before date_before."

        elif q_type in FORM_QUESTION_TYPE_TIME:
            for f in ('contains', 'selected_options', 'min', 'max', 'date_after', 'date_before'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."
            # if 'time_after' in attrs and 'time_before' in attrs and attrs['time_after'] > attrs['time_before']:
            #     errors['time_after'] = "time_after must be on or before time_before."

        elif q_type in FORM_QUESTION_TYPE_UPLOAD:
            for f in ('contains', 'selected_options', 'min', 'max', 'date_after', 'date_before', 'time_after', 'time_before'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class RegQuestionConditionSerializer(serializers.Serializer):
    """
    Validates a single per-question condition for a registration (EventQuestion) question.

    Registration questions use UUID IDs and support fewer types than EventFormQuestions.
    """
    question_id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=list(VALID_REG_QUESTION_TYPES))

    # Text
    contains = serializers.CharField(required=False, allow_blank=False, max_length=500)

    # Choice
    selected_options = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
        max_length=200,
    )

    # Range (slider only for reg questions)
    min = serializers.IntegerField(required=False)
    max = serializers.IntegerField(required=False)

    # Upload / submission date
    submitted_after = serializers.DateTimeField(required=False)
    submitted_before = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        q_type = attrs['type']
        errors = {}

        if q_type in ('short_answer', 'long_answer'):
            for f in ('selected_options', 'min', 'max'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."

        elif q_type in ('single_choice', 'multiple_choice'):
            for f in ('contains', 'min', 'max'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."

        elif q_type == 'slider':
            for f in ('contains', 'selected_options'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."
            if 'min' in attrs and 'max' in attrs and attrs['min'] > attrs['max']:
                errors['min'] = "min must be less than or equal to max."

        elif q_type == 'upload':
            for f in ('contains', 'selected_options', 'min', 'max'):
                if f in attrs:
                    errors[f] = f"Field '{f}' is not valid for question type '{q_type}'."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


# ── Form condition ────────────────────────────────────────────────────────────

class FormConditionSerializer(serializers.Serializer):
    """
    A filter condition scoped to a single EventForm.

    `questions` contains per-question conditions for questions belonging to this form.
    The `operator` controls how multiple question conditions within this form are combined.
    """
    form = serializers.UUIDField()
    has_response = serializers.BooleanField(required=False, allow_null=True, default=None)
    response_complete = serializers.BooleanField(required=False, allow_null=True, default=None)
    operator = serializers.ChoiceField(choices=['AND', 'OR'], default='AND')
    questions = FormQuestionConditionSerializer(many=True, required=False, default=list)

    def validate_questions(self, value):
        if len(value) > 50:
            raise serializers.ValidationError("A form condition may have at most 50 question conditions.")
        return value


# ── Top-level section serializers ─────────────────────────────────────────────

class FormsFilterSerializer(serializers.Serializer):
    """
    Filters for EventForm responses.

    `operator` controls how multiple FormConditions are combined (AND/OR).
    """
    operator = serializers.ChoiceField(choices=['AND', 'OR'], default='AND')
    conditions = FormConditionSerializer(many=True, required=False, default=list)

    def validate_conditions(self, value):
        if len(value) > 20:
            raise serializers.ValidationError("At most 20 form conditions are allowed.")
        return value


class RegistrationQuestionsFilterSerializer(serializers.Serializer):
    """Filters for event registration (EventQuestion) answers."""
    operator = serializers.ChoiceField(choices=['AND', 'OR'], default='AND')
    conditions = RegQuestionConditionSerializer(many=True, required=False, default=list)

    def validate_conditions(self, value):
        if len(value) > 50:
            raise serializers.ValidationError("At most 50 registration question conditions are allowed.")
        return value


class DemographicsFilterSerializer(serializers.Serializer):
    gender = serializers.CharField(required=False, allow_null=True, max_length=100)
    age_min = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=150)
    age_max = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=150)
    is_minor = serializers.BooleanField(required=False, allow_null=True)
    organisation = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    area_from = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    chapter_from = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    cluster_from = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    country_from = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    has_dietary_requirements = serializers.BooleanField(required=False, allow_null=True)
    dietary_requirement = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    has_medical_conditions = serializers.BooleanField(required=False, allow_null=True)
    medical_condition = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    has_accessibility_requirements = serializers.BooleanField(required=False, allow_null=True)
    accessibility_requirement = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False, allow_empty=True, default=list,
    )
    has_emergency_contacts = serializers.BooleanField(required=False, allow_null=True)
    include_deleted = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        age_min = attrs.get('age_min')
        age_max = attrs.get('age_max')
        if age_min is not None and age_max is not None and age_min > age_max:
            raise serializers.ValidationError({'age_min': 'age_min must be less than or equal to age_max.'})
        return attrs


class StatusFilterSerializer(serializers.Serializer):
    is_checked_in = serializers.BooleanField(required=False, allow_null=True)
    is_registered = serializers.BooleanField(required=False, allow_null=True)
    is_cancelled = serializers.BooleanField(required=False, allow_null=True)
    is_staff = serializers.BooleanField(required=False, allow_null=True)


class OrdersFilterSerializer(serializers.Serializer):
    has_orders = serializers.BooleanField(required=False, allow_null=True)
    order_status = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True, default=list,
    )
    order_status_not = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True, default=list,
    )
    purchased_product = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, allow_empty=True, default=list,
    )
    purchased_product_title = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=255)
    order_total_min = serializers.DecimalField(required=False, allow_null=True, max_digits=12, decimal_places=2)
    order_total_max = serializers.DecimalField(required=False, allow_null=True, max_digits=12, decimal_places=2)
    order_created_after = serializers.DateTimeField(required=False, allow_null=True)
    order_created_before = serializers.DateTimeField(required=False, allow_null=True)
    order_reference_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=100)
    has_completed_orders = serializers.BooleanField(required=False, allow_null=True)
    has_pending_orders = serializers.BooleanField(required=False, allow_null=True)

    def validate(self, attrs):
        mn = attrs.get('order_total_min')
        mx = attrs.get('order_total_max')
        if mn is not None and mx is not None and mn > mx:
            raise serializers.ValidationError({'order_total_min': 'order_total_min must be <= order_total_max.'})
        after = attrs.get('order_created_after')
        before = attrs.get('order_created_before')
        if after and before and after > before:
            raise serializers.ValidationError({'order_created_after': 'order_created_after must be before order_created_before.'})
        return attrs


class PaymentsFilterSerializer(serializers.Serializer):
    has_payments = serializers.BooleanField(required=False, allow_null=True)
    payment_id = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, default=list,
    )
    payment_reference = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=200)
    bank_transfer_reference = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=200)
    payment_status = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True, default=list,
    )
    payment_target = serializers.ChoiceField(
        choices=['booking', 'order', 'ticket'], required=False, allow_null=True,
    )
    payment_method_type = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True, default=list,
    )
    payment_method_title = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=200)
    has_refunds = serializers.BooleanField(required=False, allow_null=True)
    refund_status = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True, default=list,
    )
    refund_is_active = serializers.BooleanField(required=False, allow_null=True)
    has_donations = serializers.BooleanField(required=False, allow_null=True)
    donation_status = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True, default=list,
    )
    has_discounts_used = serializers.BooleanField(required=False, allow_null=True)
    discount_id = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, default=list,
    )
    discount_name = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=200)


class AdvancedFilterSerializer(serializers.Serializer):
    relationship_to_user = serializers.CharField(required=False, allow_null=True, max_length=50)
    self_registered = serializers.BooleanField(required=False, allow_null=True)
    has_booking = serializers.BooleanField(required=False, allow_null=True)
    booking = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, default=list,
    )
    date_of_birth_after = serializers.DateField(required=False, allow_null=True)
    date_of_birth_before = serializers.DateField(required=False, allow_null=True)
    created_after = serializers.DateTimeField(required=False, allow_null=True)
    created_before = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        dob_after = attrs.get('date_of_birth_after')
        dob_before = attrs.get('date_of_birth_before')
        if dob_after and dob_before and dob_after > dob_before:
            raise serializers.ValidationError({'date_of_birth_after': 'date_of_birth_after must be on or before date_of_birth_before.'})
        ca = attrs.get('created_after')
        cb = attrs.get('created_before')
        if ca and cb and ca > cb:
            raise serializers.ValidationError({'created_after': 'created_after must be before created_before.'})
        return attrs


# ── Root filter container ─────────────────────────────────────────────────────

class AttendeeFiltersSerializer(serializers.Serializer):
    """
    The top-level `filters` object in the POST body.

    `operator` controls how the top-level sections are combined (currently AND-only
    across sections; OR applies within forms.operator and registration_questions.operator).
    """
    operator = serializers.ChoiceField(choices=['AND', 'OR'], default='AND')
    demographics = DemographicsFilterSerializer(required=False)
    status = StatusFilterSerializer(required=False)
    forms = FormsFilterSerializer(required=False)
    registration_questions = RegistrationQuestionsFilterSerializer(required=False)
    orders = OrdersFilterSerializer(required=False)
    payments = PaymentsFilterSerializer(required=False)
    advanced = AdvancedFilterSerializer(required=False)


# ── Request root ──────────────────────────────────────────────────────────────

class AttendeeFilterRequestSerializer(serializers.Serializer):
    """
    Root serializer for POST /api/attendees/filter/

    Pagination and ordering live here alongside the nested `filters` object.
    """
    event = serializers.CharField(required=True, max_length=255)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=25, min_value=1, max_value=200)
    search = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=300)
    ordering = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=100)
    filters = AttendeeFiltersSerializer(required=False, default=dict)

    def validate_ordering(self, value):
        if value is None:
            return value
        allowed_fields = {
            'created_at', 'first_name', 'last_name', 'date_of_birth',
            '-created_at', '-first_name', '-last_name', '-date_of_birth',
        }
        if value not in allowed_fields:
            raise serializers.ValidationError(
                f"Invalid ordering '{value}'. Allowed values: {', '.join(sorted(allowed_fields))}."
            )
        return value


# ── Response serializer ───────────────────────────────────────────────────────

class AttendeeFilterResponseSerializer(serializers.Serializer):
    """Shape of the paginated response from POST /api/attendees/filter/"""
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()
    results = serializers.ListField(child=serializers.DictField())
