from django.db import models
from django.conf import settings

import uuid


class EventFormStatusChoices(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PUBLISHED = 'published', 'Published'
    CLOSED = 'closed', 'Closed'


class EventForm(models.Model):

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='forms')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=16,
        choices=EventFormStatusChoices.choices,
        default=EventFormStatusChoices.DRAFT,
        db_index=True,
    )
    required = models.BooleanField(
        default=False,
        help_text='Whether all attendees are required to complete this form.',
    )
    allow_response_editing = models.BooleanField(
        default=True,
        help_text='Allow attendees to edit their responses until the form is closed.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_event_forms',
    )
        
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Optional deadline for form submission. Ignored if the form is closed.',
    )
    deadline_message = models.CharField(
        max_length=255,
        blank=True,
        help_text='Optional message to display when the deadline has passed.',
    )
    opens_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Optional opening time for the form. Ignored if the form is published.',
    )
    pre_opens_message = models.CharField(
        max_length=255,
        blank=True,
        help_text='Optional message to display before the form opens.',
    )
    
    landing_image = models.ImageField(
        upload_to='event_forms/landing_images/',
        null=True,
        blank=True,
        help_text='Optional image to display on the form landing page.',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"EventForm '{self.title}' for Event {self.event_id}"

    def __repr__(self):
        return f"<EventForm {self.id} - {self.title} [{self.status}]>"

    def publish(self):
        self.status = EventFormStatusChoices.PUBLISHED
        self.save(update_fields=['status', 'updated_at'])

    def close(self):
        self.status = EventFormStatusChoices.CLOSED
        self.save(update_fields=['status', 'updated_at'])
