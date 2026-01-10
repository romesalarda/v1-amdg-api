from django.db import models
from django.core.exceptions import ValidationError

import uuid

class EventQuestionTypeChoices(models.TextChoices):
    
    SHORT_ANSWER = 'short_answer', 'Short Answer'
    LONG_ANSWER = 'long_answer', 'Long Answer'
    UPLOAD = 'upload', 'Upload'
    MULTIPLE_CHOICE = 'multiple_choice', 'Multiple Choice'
    SINGLE_CHOICE = 'single_choice', 'Single Choice'
    SLIDER = 'slider', 'Slider'
    
class EventQuestion(models.Model):
    
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='questions')
    question_title = models.CharField(max_length=255)
    question_body = models.TextField()
    question_type = models.CharField(max_length=32, choices=EventQuestionTypeChoices.choices, default=EventQuestionTypeChoices.SHORT_ANSWER)
    
    required = models.BooleanField(default=False)
    public = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    
    max_value = models.IntegerField(blank=True, null=True)
    min_value = models.IntegerField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['order', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['event', 'order'], name='unique_question_order_per_event'),
        ]
            
    
    def __str__(self):
        return f"Question {self.id} for Event {self.event.id}"
    
    def __repr__(self):
        return f"<EventQuestion {self.id} - {self.question_title}>"
    
    def clean(self):
        super().clean()

        if self.question_type == EventQuestionTypeChoices.SLIDER:
            if self.min_value is None or self.max_value is None:
                raise ValidationError("Slider questions require min_value and max_value.")
            if self.min_value >= self.max_value:
                raise ValidationError("min_value must be less than max_value.")

        if self.question_type in {
            EventQuestionTypeChoices.SHORT_ANSWER,
            EventQuestionTypeChoices.LONG_ANSWER,
            EventQuestionTypeChoices.UPLOAD,
        }:
            if self.min_value is not None or self.max_value is not None:
                raise ValidationError("This question type does not support min/max values.")
        if self.question_type in {
            EventQuestionTypeChoices.MULTIPLE_CHOICE,
            EventQuestionTypeChoices.SINGLE_CHOICE,
        }:
            if not self.pk:
                return  # options not yet created
            if not self.options.exists():
                raise ValidationError("Choice questions must have at least one option.")
        else:
            if self.pk and self.options.exists():
                raise ValidationError("This question type does not support options.")
            
    def validate_answer(self, answer):
        
        if self.question_type == EventQuestionTypeChoices.SLIDER:
            try:
                value = int(answer)
            except ValueError:
                raise ValidationError("Answer must be an integer for slider questions.")
            if self.min_value is not None and value < self.min_value:
                raise ValidationError(f"Answer must be at least {self.min_value}.")
            if self.max_value is not None and value > self.max_value:
                raise ValidationError(f"Answer must be at most {self.max_value}.")
        elif self.question_type in {
            EventQuestionTypeChoices.SHORT_ANSWER,
            EventQuestionTypeChoices.LONG_ANSWER,
            EventQuestionTypeChoices.UPLOAD,
        }:
            if not isinstance(answer, str):
                raise ValidationError("Answer must be a string for this question type.")
        
class EventQuestionOption(models.Model):
    
    question = models.ForeignKey(EventQuestion, on_delete=models.CASCADE, related_name='options')
    option_text = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['question', 'order'], name='unique_option_order_per_question'),
            models.UniqueConstraint(
                fields=['question', 'option_text'],
                name='unique_option_text_per_question',
            )
        ]
    
    def __str__(self):
        return f"Option {self.id} for Question {self.question.id}"
    
    def __repr__(self):
        return f"<EventQuestionOption {self.id} - {self.option_text}>"
    
class EventQuestionAnswer(models.Model):
    
    question = models.ForeignKey(EventQuestion, on_delete=models.CASCADE, related_name='answers')
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='question_answers')
    answer_text = models.TextField()
    
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('question', 'attendee')
        ordering = ['-submitted_at']
    
    def __str__(self):
        return f"Answer {self.id} for Question {self.question.id} by Attendee {self.attendee.id}"
    
    def __repr__(self):
        return f"<EventQuestionAnswer {self.id} - Question {self.question.id} - Attendee {self.attendee.id}>"
    
    def clean(self):
        super().clean()
        self.question.validate_answer(self.answer_text)
        
        if self.question.required and not self.answer_text and not self.selected_options.exists():
            raise ValidationError("This question requires an answer.")

class EventQuestionAnswerChoice(models.Model):
    
    answer = models.ForeignKey(EventQuestionAnswer, on_delete=models.CASCADE, related_name='selected_options')
    option = models.ForeignKey(EventQuestionOption, on_delete=models.CASCADE, related_name='selected_in_answers')

    selected_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('answer', 'option')
    
    def __str__(self):
        return f"Choice {self.id} for Answer {self.answer.id}"
    
    def __repr__(self):
        return f"<EventQuestionAnswerChoice {self.id} - Answer {self.answer.id} - Option {self.option.id}>"
    
    def clean(self):
        super().clean()
        if self.option.question_id != self.answer.question_id:
            raise ValidationError("Selected option does not belong to this question.")
