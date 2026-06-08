from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

import uuid


class EventFormResponse(models.Model):

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    form = models.ForeignKey('events.EventForm', on_delete=models.CASCADE, related_name='responses')
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='form_responses')
    is_complete = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['form', 'attendee'],
                name='unique_form_response_per_attendee',
            ),
        ]
        ordering = ['-submitted_at']

    def __str__(self):
        return f"FormResponse {self.id} for Form {self.form_id} by Attendee {self.attendee_id}"

    def __repr__(self):
        return f"<EventFormResponse {self.id} - Form {self.form_id} - Attendee {self.attendee_id}>"


def _form_response_upload_path(instance, filename):
    return f"form_responses/{instance.response.form_id}/{instance.response_id}/{filename}"


class EventFormResponseAnswer(models.Model):

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    response = models.ForeignKey(EventFormResponse, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey('events.EventFormQuestion', on_delete=models.CASCADE, related_name='answers')
    answer_text = models.TextField(blank=True)
    answer_file = models.FileField(
        upload_to=_form_response_upload_path,
        storage='core.storage_backends.MediaStorage',
        blank=True,
        null=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['response', 'question'],
                name='unique_form_answer_per_question_per_response',
            ),
        ]
        ordering = ['-submitted_at']

    def __str__(self):
        return f"FormAnswer {self.id} for Question {self.question_id}"

    def __repr__(self):
        return f"<EventFormResponseAnswer {self.id} - Question {self.question_id}>"

    def clean(self):
        super().clean()
        from apps.events.models.forms.questions import EventFormQuestionTypeChoices

        qt = self.question.question_type
        T = EventFormQuestionTypeChoices

        # File-only answer types
        if qt == T.UPLOAD:
            if not self.answer_file and not self.pk:
                raise ValidationError("An uploaded file is required for upload questions.")
            return

        # Skip text validation for choice types — handled via EventFormResponseAnswerChoice
        if qt in T.choice_types():
            return

        # Validate text answer for all other types
        if self.answer_text:
            self.question.validate_answer(self.answer_text)

        if self.question.required and not self.answer_text and not self.answer_file:
            raise ValidationError("This question requires an answer.")


class EventFormResponseAnswerChoice(models.Model):

    answer = models.ForeignKey(EventFormResponseAnswer, on_delete=models.CASCADE, related_name='selected_options')
    option = models.ForeignKey('events.EventFormQuestionOption', on_delete=models.CASCADE, related_name='selected_in_answers')
    selected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('answer', 'option')

    def __str__(self):
        return f"Choice {self.id} for Answer {self.answer_id}"

    def __repr__(self):
        return f"<EventFormResponseAnswerChoice {self.id} - Answer {self.answer_id} - Option {self.option_id}>"

    def clean(self):
        super().clean()
        if self.option.question_id != self.answer.question_id:
            raise ValidationError("Selected option does not belong to this question.")


class EventFormDelegateToken(models.Model):

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    response = models.ForeignKey(EventFormResponse, on_delete=models.CASCADE, related_name='delegate_tokens')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_form_delegate_tokens',
    )
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"DelegateToken {self.token} for Response {self.response_id}"

    def __repr__(self):
        return f"<EventFormDelegateToken {self.id} - used={self.is_used}>"

    @property
    def is_valid(self):
        return not self.is_used and self.expires_at > timezone.now()
