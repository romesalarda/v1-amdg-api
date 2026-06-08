from django.db import models
from django.core.exceptions import ValidationError


class EventFormQuestionTypeChoices(models.TextChoices):
    SHORT_ANSWER = 'short_answer', 'Short Answer'
    LONG_ANSWER = 'long_answer', 'Long Answer'
    UPLOAD = 'upload', 'Upload'
    MULTIPLE_CHOICE = 'multiple_choice', 'Multiple Choice'
    SINGLE_CHOICE = 'single_choice', 'Single Choice'
    SLIDER = 'slider', 'Slider'
    DATE = 'date', 'Date'
    TIME = 'time', 'Time'
    EMAIL = 'email', 'Email'
    PHONE = 'phone', 'Phone'
    RATING = 'rating', 'Rating'

    # Types that support min/max
    _RANGE_TYPES = None  # see class method below

    @classmethod
    def range_types(cls):
        return {cls.SLIDER, cls.RATING}

    @classmethod
    def choice_types(cls):
        return {cls.MULTIPLE_CHOICE, cls.SINGLE_CHOICE}

    @classmethod
    def text_types(cls):
        return {cls.SHORT_ANSWER, cls.LONG_ANSWER, cls.EMAIL, cls.PHONE}

    @classmethod
    def no_option_types(cls):
        return {
            cls.SHORT_ANSWER, cls.LONG_ANSWER, cls.UPLOAD,
            cls.DATE, cls.TIME, cls.EMAIL, cls.PHONE,
        }


class EventFormQuestion(models.Model):

    form = models.ForeignKey('events.EventForm', on_delete=models.CASCADE, related_name='questions')
    question_title = models.CharField(max_length=255)
    question_body = models.TextField()
    question_type = models.CharField(
        max_length=32,
        choices=EventFormQuestionTypeChoices.choices,
        default=EventFormQuestionTypeChoices.SHORT_ANSWER,
    )
    required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    max_value = models.IntegerField(blank=True, null=True)
    min_value = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['form', 'order'],
                name='unique_form_question_order_per_form',
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]

    def __str__(self):
        return f"FormQuestion {self.id} for Form {self.form_id}"

    def __repr__(self):
        return f"<EventFormQuestion {self.id} - {self.question_title}>"

    def clean(self):
        super().clean()
        qt = self.question_type
        range_types = EventFormQuestionTypeChoices.range_types()
        choice_types = EventFormQuestionTypeChoices.choice_types()
        no_option_types = EventFormQuestionTypeChoices.no_option_types()

        if qt in range_types:
            if self.min_value is None or self.max_value is None:
                raise ValidationError(f"{self.get_question_type_display()} questions require min_value and max_value.")
            if self.min_value >= self.max_value:
                raise ValidationError("min_value must be less than max_value.")

        if qt in no_option_types:
            if self.min_value is not None or self.max_value is not None:
                raise ValidationError("This question type does not support min/max values.")

        if qt in choice_types:
            if not self.pk:
                return  # options not yet created
            if not self.options.exists():
                raise ValidationError("Choice questions must have at least one option.")
        else:
            if self.pk and self.options.exists():
                raise ValidationError("This question type does not support options.")

    def validate_answer(self, answer):
        qt = self.question_type
        T = EventFormQuestionTypeChoices

        if qt in T.range_types():
            try:
                value = int(answer)
            except (ValueError, TypeError):
                raise ValidationError("Answer must be an integer for this question type.")
            if self.min_value is not None and value < self.min_value:
                raise ValidationError(f"Answer must be at least {self.min_value}.")
            if self.max_value is not None and value > self.max_value:
                raise ValidationError(f"Answer must be at most {self.max_value}.")

        elif qt in {T.SHORT_ANSWER, T.LONG_ANSWER, T.EMAIL, T.PHONE}:
            if not isinstance(answer, str):
                raise ValidationError("Answer must be a string for this question type.")

        elif qt == T.DATE:
            import re
            if not isinstance(answer, str) or not re.match(r'^\d{4}-\d{2}-\d{2}$', answer):
                raise ValidationError("Answer must be a date string in YYYY-MM-DD format.")

        elif qt == T.TIME:
            import re
            if not isinstance(answer, str) or not re.match(r'^\d{2}:\d{2}(:\d{2})?$', answer):
                raise ValidationError("Answer must be a time string in HH:MM or HH:MM:SS format.")


class EventFormQuestionOption(models.Model):

    question = models.ForeignKey(EventFormQuestion, on_delete=models.CASCADE, related_name='options')
    option_text = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['question', 'order'], name='unique_form_option_order_per_question'),
            models.UniqueConstraint(
                fields=['question', 'option_text'],
                name='unique_form_option_text_per_question',
            ),
        ]

    def __str__(self):
        return f"Option {self.id} for FormQuestion {self.question_id}"

    def __repr__(self):
        return f"<EventFormQuestionOption {self.id} - {self.option_text}>"
