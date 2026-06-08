"""
Serializers for the Event Forms system.

Provides serialization for EventForm, EventFormQuestion, EventFormQuestionOption,
EventFormResponse, EventFormResponseAnswer, EventFormResponseAnswerChoice,
and EventFormDelegateToken models.
"""
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone

from drf_spectacular.utils import extend_schema_field

from apps.events.models import (
    Event,
    EventForm,
    EventFormStatusChoices,
    EventFormQuestion,
    EventFormQuestionTypeChoices,
    EventFormQuestionOption,
    EventFormResponse,
    EventFormResponseAnswer,
    EventFormResponseAnswerChoice,
    EventFormDelegateToken,
)


# ── Option Serializers ────────────────────────────────────────────────────────

class EventFormQuestionOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventFormQuestionOption
        fields = ('id', 'question', 'option_text', 'order', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class EventFormQuestionNestedOptionSerializer(serializers.ModelSerializer):
    """Lightweight option serializer for nesting inside question serializer."""
    id = serializers.IntegerField(required=False)

    class Meta:
        model = EventFormQuestionOption
        fields = ('id', 'option_text', 'order')
        extra_kwargs = {
            'order': {'required': False, 'default': 0},
        }


# ── Question Serializers ──────────────────────────────────────────────────────

class EventFormQuestionSerializer(serializers.ModelSerializer):
    """
    Serializer for EventFormQuestion with writable nested options.

    Supports creating and updating questions with options in a single request.
    For updates:
      - Options with 'id': update existing
      - Options without 'id': create new
      - Existing options not in payload: deleted
    """
    question_type_display = serializers.CharField(source='get_question_type_display', read_only=True)
    options = EventFormQuestionNestedOptionSerializer(many=True, required=False)
    _links = serializers.SerializerMethodField()

    class Meta:
        model = EventFormQuestion
        fields = (
            'id', 'form', 'question_title', 'question_body',
            'question_type', 'question_type_display',
            'required', 'order', 'max_value', 'min_value',
            'options', 'created_at', 'updated_at', '_links',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'form': {'type': 'string', 'format': 'uri'},
        },
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        links = {
            'self': request.build_absolute_uri(f"/api/event/form-questions/{obj.id}/")
        }
        if obj.form_id:
            links['form'] = request.build_absolute_uri(f"/api/event/forms/{obj.form_id}/")
        return links

    def validate_question_title(self, value):
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError("Question title must be at least 3 characters long.")
        return value.strip()

    def validate(self, data):
        qt = data.get('question_type', getattr(self.instance, 'question_type', None))
        min_value = data.get('min_value')
        max_value = data.get('max_value')
        options = data.get('options', [])
        T = EventFormQuestionTypeChoices

        if qt in T.range_types():
            if min_value is None or max_value is None:
                raise serializers.ValidationError(
                    {'min_value': f"{T(qt).label} questions require both min_value and max_value."}
                )
            if min_value >= max_value:
                raise serializers.ValidationError(
                    {'max_value': "max_value must be greater than min_value."}
                )

        if qt in T.no_option_types():
            if min_value is not None or max_value is not None:
                raise serializers.ValidationError(
                    "This question type does not support min_value or max_value."
                )

        if qt in T.choice_types():
            if not self.instance and len(options) < 1:
                raise serializers.ValidationError(
                    {'options': "Choice questions must have at least one option."}
                )
        else:
            if len(options) > 0:
                raise serializers.ValidationError(
                    {'options': "This question type does not support options."}
                )

        # Validate option text uniqueness
        texts = [opt.get('option_text', '').strip() for opt in options]
        if len(texts) != len(set(texts)):
            raise serializers.ValidationError({'options': "Option texts must be unique within a question."})

        return data

    def create(self, validated_data):
        options_data = validated_data.pop('options', [])
        with transaction.atomic():
            question = EventFormQuestion(**validated_data)
            question.save()
            if options_data:
                EventFormQuestionOption.objects.bulk_create([
                    EventFormQuestionOption(
                        question=question,
                        option_text=opt['option_text'],
                        order=opt.get('order', idx),
                    )
                    for idx, opt in enumerate(options_data)
                ])
        return question

    def update(self, instance, validated_data):
        options_data = validated_data.pop('options', None)
        new_order = validated_data.get('order')

        with transaction.atomic():
            if new_order is not None and new_order != instance.order:
                from django.db.models import F
                old_order = instance.order
                form = instance.form
                EventFormQuestion.objects.filter(form=form).select_for_update().order_by('id').exists()
                instance.order = 999999
                instance.save(update_fields=['order'])
                qs = EventFormQuestion.objects.filter(form=form).exclude(id=instance.id)
                if new_order < old_order:
                    qs.filter(order__gte=new_order, order__lt=old_order).update(order=F('order') + 1)
                else:
                    qs.filter(order__gt=old_order, order__lte=new_order).update(order=F('order') - 1)
                instance.order = new_order

            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if options_data is not None:
                existing_ids = set(instance.options.values_list('id', flat=True))
                provided_ids = set()
                to_update = []
                to_create = []

                for opt_data in options_data:
                    opt_id = opt_data.get('id')
                    if opt_id:
                        provided_ids.add(opt_id)
                        try:
                            opt = EventFormQuestionOption.objects.get(id=opt_id, question=instance)
                            opt.option_text = opt_data.get('option_text', opt.option_text)
                            opt.order = opt_data.get('order', opt.order)
                            to_update.append(opt)
                        except EventFormQuestionOption.DoesNotExist:
                            pass
                    else:
                        to_create.append(EventFormQuestionOption(
                            question=instance,
                            option_text=opt_data['option_text'],
                            order=opt_data.get('order', 0),
                        ))

                to_delete = existing_ids - provided_ids
                if to_delete:
                    EventFormQuestionOption.objects.filter(id__in=to_delete).delete()
                if to_update:
                    EventFormQuestionOption.objects.bulk_update(to_update, ['option_text', 'order'])
                if to_create:
                    EventFormQuestionOption.objects.bulk_create(to_create)

        return instance


# ── Form Serializers ──────────────────────────────────────────────────────────

class EventFormListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list endpoints."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    question_count = serializers.IntegerField(read_only=True, default=0)
    event_title = serializers.CharField(source='event.title', read_only=True)
    _links = serializers.SerializerMethodField()

    class Meta:
        model = EventForm
        fields = (
            'id', 'event', 'event_title', 'title', 'status', 'status_display',
            'required', 'allow_response_editing', 'question_count',
            'created_at', 'updated_at', '_links',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    @extend_schema_field({'type': 'object'})
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        return {
            'self': request.build_absolute_uri(f"/api/event/forms/{obj.id}/"),
            'questions': request.build_absolute_uri(f"/api/event/form-questions/?form={obj.id}"),
        }


class EventFormSerializer(serializers.ModelSerializer):
    """Full serializer with nested questions (read) for detail/create/update."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    question_count = serializers.IntegerField(read_only=True, default=0)
    event_title = serializers.CharField(source='event.title', read_only=True)
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    questions = EventFormQuestionSerializer(many=True, read_only=True)
    _links = serializers.SerializerMethodField()

    class Meta:
        model = EventForm
        fields = (
            'id', 'event', 'event_title', 'title', 'description',
            'status', 'status_display', 'required', 'allow_response_editing',
            'question_count', 'questions', 'created_at', 'updated_at', '_links',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    @extend_schema_field({'type': 'object'})
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        return {
            'self': request.build_absolute_uri(f"/api/event/forms/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.url_safe_title}/"),
            'questions': request.build_absolute_uri(f"/api/event/form-questions/?form={obj.id}"),
            'responses': request.build_absolute_uri(f"/api/event/form-responses/?form={obj.id}"),
        }

    def create(self, validated_data):
        user = self.context['request'].user if self.context.get('request') else None
        if user and user.is_authenticated and not validated_data.get('created_by'):
            validated_data['created_by'] = user
        return super().create(validated_data)


# ── Response Answer Choice Serializer ─────────────────────────────────────────

class EventFormResponseAnswerChoiceSerializer(serializers.ModelSerializer):
    option_text = serializers.CharField(source='option.option_text', read_only=True)

    class Meta:
        model = EventFormResponseAnswerChoice
        fields = ('id', 'answer', 'option', 'option_text', 'selected_at')
        read_only_fields = ('id', 'selected_at')


# ── Response Answer Serializer ─────────────────────────────────────────────────

class EventFormResponseAnswerSerializer(serializers.ModelSerializer):
    """
    Serializer for EventFormResponseAnswer with choice and file upload support.

    For choice questions: provide selected_option_ids (write-only list of option PKs).
    For upload questions: submit multipart/form-data with answer_file.
    """
    selected_option_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )
    selected_options = EventFormResponseAnswerChoiceSerializer(
        source='selected_options',
        many=True,
        read_only=True,
    )
    answer_file_url = serializers.SerializerMethodField(read_only=True)
    question_type = serializers.CharField(source='question.question_type', read_only=True)

    class Meta:
        model = EventFormResponseAnswer
        fields = (
            'id', 'response', 'question', 'question_type',
            'answer_text', 'answer_file', 'answer_file_url',
            'selected_option_ids', 'selected_options',
            'submitted_at', 'updated_at',
        )
        read_only_fields = ('id', 'submitted_at', 'updated_at', 'answer_file_url')
        extra_kwargs = {
            'answer_file': {'write_only': True, 'required': False},
            'answer_text': {'required': False},
        }

    @extend_schema_field({'type': 'string', 'format': 'uri', 'nullable': True})
    def get_answer_file_url(self, obj):
        if not obj.answer_file:
            return None
        request = self.context.get('request')
        try:
            url = obj.answer_file.url
            return request.build_absolute_uri(url) if request else url
        except Exception:
            return None

    def validate(self, data):
        question = data.get('question', getattr(self.instance, 'question', None))
        if not question:
            return data

        qt = question.question_type
        T = EventFormQuestionTypeChoices
        selected_ids = data.get('selected_option_ids', [])

        if qt in T.choice_types():
            if not selected_ids:
                if question.required:
                    raise serializers.ValidationError(
                        {'selected_option_ids': "A selection is required for this question."}
                    )
        elif qt == T.UPLOAD:
            answer_file = data.get('answer_file', getattr(self.instance, 'answer_file', None))
            if not answer_file and question.required:
                raise serializers.ValidationError(
                    {'answer_file': "A file upload is required for this question."}
                )
        else:
            answer_text = data.get('answer_text', '')
            if question.required and not answer_text:
                raise serializers.ValidationError(
                    {'answer_text': "An answer is required for this question."}
                )
            if answer_text:
                try:
                    question.validate_answer(answer_text)
                except Exception as e:
                    raise serializers.ValidationError({'answer_text': str(e)})

        return data

    def create(self, validated_data):
        selected_ids = validated_data.pop('selected_option_ids', [])
        with transaction.atomic():
            answer = super().create(validated_data)
            if selected_ids:
                self._save_choices(answer, selected_ids)
        return answer

    def update(self, instance, validated_data):
        selected_ids = validated_data.pop('selected_option_ids', None)
        with transaction.atomic():
            answer = super().update(instance, validated_data)
            if selected_ids is not None:
                answer.selected_options.all().delete()
                self._save_choices(answer, selected_ids)
        return answer

    def _save_choices(self, answer, option_ids):
        qt = answer.question.question_type
        T = EventFormQuestionTypeChoices
        if qt == T.SINGLE_CHOICE:
            option_ids = option_ids[:1]
        for oid in option_ids:
            try:
                option = EventFormQuestionOption.objects.get(id=oid, question=answer.question)
                EventFormResponseAnswerChoice.objects.get_or_create(answer=answer, option=option)
            except EventFormQuestionOption.DoesNotExist:
                pass


# ── Response Serializer ────────────────────────────────────────────────────────

class EventFormResponseSerializer(serializers.ModelSerializer):
    """Serializer for EventFormResponse with nested read-only answers."""
    answers = EventFormResponseAnswerSerializer(many=True, read_only=True)
    attendee_display = serializers.SerializerMethodField(read_only=True)
    _links = serializers.SerializerMethodField()

    class Meta:
        model = EventFormResponse
        fields = (
            'id', 'form', 'attendee', 'attendee_display',
            'is_complete', 'answers',
            'submitted_at', 'updated_at', '_links',
        )
        read_only_fields = ('id', 'submitted_at', 'updated_at')

    @extend_schema_field({'type': 'string', 'nullable': True})
    def get_attendee_display(self, obj):
        try:
            return getattr(obj.attendee, 'attendee_display_id', None) or str(obj.attendee_id)
        except Exception:
            return None

    @extend_schema_field({'type': 'object'})
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        return {
            'self': request.build_absolute_uri(f"/api/event/form-responses/{obj.id}/"),
            'form': request.build_absolute_uri(f"/api/event/forms/{obj.form_id}/"),
        }


# ── Delegate Token Serializers ─────────────────────────────────────────────────

class EventFormDelegateTokenSerializer(serializers.ModelSerializer):
    is_valid = serializers.BooleanField(read_only=True)
    token = serializers.UUIDField(read_only=True)

    class Meta:
        model = EventFormDelegateToken
        fields = ('id', 'token', 'response', 'expires_at', 'is_used', 'is_valid', 'created_by', 'created_at')
        read_only_fields = ('id', 'token', 'is_used', 'is_valid', 'created_by', 'created_at')

    def validate_expires_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("expires_at must be a future datetime.")
        return value

    def create(self, validated_data):
        user = self.context['request'].user if self.context.get('request') else None
        if user and user.is_authenticated:
            validated_data['created_by'] = user
        return super().create(validated_data)


class EventFormDelegateTokenValidateSerializer(serializers.Serializer):
    """Read-only serializer returned by the public validate_token endpoint."""
    token = serializers.UUIDField()
    is_valid = serializers.BooleanField()
    form_id = serializers.UUIDField()
    form_title = serializers.CharField()
    attendee_id = serializers.CharField()
    expires_at = serializers.DateTimeField()


__all__ = [
    'EventFormQuestionOptionSerializer',
    'EventFormQuestionNestedOptionSerializer',
    'EventFormQuestionSerializer',
    'EventFormListSerializer',
    'EventFormSerializer',
    'EventFormResponseAnswerChoiceSerializer',
    'EventFormResponseAnswerSerializer',
    'EventFormResponseSerializer',
    'EventFormDelegateTokenSerializer',
    'EventFormDelegateTokenValidateSerializer',
]
