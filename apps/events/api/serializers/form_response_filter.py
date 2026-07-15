"""
Serializers for POST /api/event-form-responses/filter/

Provides structured filtering of EventFormResponse objects by:
  - Attendee demographics (gender, age, organisation, location, dietary/medical/accessibility needs)
  - Attendee status (checked-in, registered, cancelled, staff)
  - Question answer conditions for THIS form's questions specifically
"""
from rest_framework import serializers

# Reuse question-condition types from attendee filter serializers
from apps.attendee.api.serializers.filtering import (
    DemographicsFilterSerializer,
    StatusFilterSerializer,
    FormQuestionConditionSerializer,
)


class FormResponseQuestionFilterSerializer(serializers.Serializer):
    """
    Question-answer conditions scoped to the form being filtered.

    Since the form ID is already known (taken from the `form` field in the request),
    there is no need to pick a form inside each condition.
    """
    operator = serializers.ChoiceField(choices=['AND', 'OR'], default='AND')
    conditions = FormQuestionConditionSerializer(many=True, required=False, default=list)

    def validate_conditions(self, value):
        if len(value) > 50:
            raise serializers.ValidationError("At most 50 question conditions are allowed.")
        return value


class FormResponseFilterRequestSerializer(serializers.Serializer):
    """
    Root serializer for POST /api/event-form-responses/filter/

    Returns the same paginated EventFormResponse list as the GET endpoint but allows
    richer filtering via a structured JSON body.
    """
    form = serializers.UUIDField(required=True)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=25, min_value=1, max_value=200)
    ordering = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=100)
    search = serializers.CharField(required=False, allow_null=True, allow_blank=False, max_length=300)

    # Attendee demographic filters
    demographics = DemographicsFilterSerializer(required=False)

    # Attendee status filters
    status = StatusFilterSerializer(required=False)

    # Question answer conditions for this form
    question_filter = FormResponseQuestionFilterSerializer(required=False)

    def validate_ordering(self, value):
        if value is None:
            return value
        allowed = {
            'submitted_at', '-submitted_at',
            'updated_at', '-updated_at',
        }
        if value not in allowed:
            raise serializers.ValidationError(
                f"Invalid ordering '{value}'. Allowed: {', '.join(sorted(allowed))}."
            )
        return value
