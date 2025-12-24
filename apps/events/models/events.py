from django.db import models
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from django.contrib.contenttypes.models import ContentType
from timezone_field import TimeZoneField

import uuid

from apps.common.models import SoftDeleteModel, AvailabilityWindow, Resource
from apps.common.mixins import HasResourceMixin, HasAvailabilityMixin

User = get_user_model()

class EventStatusChoices(models.TextChoices):
    DRAFTING = 'DRAFTING', 'Drafting' # event is being created but not yet visible to users
    PUBLISHED = 'PUBLISHED', 'Published' # event is visible to users but not accepting registrations
    OPEN = 'OPEN', 'Open for Registration' # event is accepting registrations
    CLOSED = 'CLOSED', 'Closed' # event is no longer accepting registrations
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress' # event is currently happening
    COMPLETED = 'COMPLETED', 'Completed'# event has finished
    DELETED = 'DELETED', 'Deleted' # event is deleted/removed - soft
    CANCELLED = 'CANCELLED', 'Cancelled' # event is cancelled
    POSTPONED = 'POSTPONED', 'Postponed' # event is postponed
    ARCHIVED = 'ARCHIVED', 'Archived' # event is archived for record-keeping
    
MAX_EVENT_CODE_LENGTH = 5
    
class EventType(models.Model):
    
    title = models.CharField(max_length=100)
    code = models.CharField(max_length=MAX_EVENT_CODE_LENGTH, unique=True) # e.g. CONF
    description = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='event_types_created', null=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        if self.title:
            self.title = self.title.strip()
        if self.code is None:
            self.code = slugify(self.title)[:MAX_EVENT_CODE_LENGTH].upper()
        else:
            self.code = slugify(self.code)[:MAX_EVENT_CODE_LENGTH].upper()
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.title

class Event(SoftDeleteModel, HasResourceMixin, HasAvailabilityMixin):
    
    # identifier fields
    event_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) # uuid for URLS
    display_code = models.CharField(max_length=10, unique=True) # human-friendly unique code
    display_identifier = models.CharField(max_length=20, unique=True) # short identifier for display
    
    # admin fields
    status = models.CharField(max_length=20, choices=EventStatusChoices.choices, default=EventStatusChoices.DRAFTING)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_events')
    created_at = models.DateTimeField(auto_now_add=True)
    event_type = models.ForeignKey(EventType, on_delete=models.SET_NULL, null=True, related_name='events')
    timezone = TimeZoneField(default='Europe/London')

    title = models.CharField(max_length=200, help_text=_("display title")) # display title
    url_safe_title = models.CharField(max_length=200, blank=True, null=True, help_text=_("URL safe title")) # URL safe title
    
    short_description = models.TextField(blank=True, null=True)
    long_description = models.TextField(blank=True, null=True)
    what_to_bring = models.TextField(blank=True, null=True)
    important_information = models.TextField(blank=True, null=True)
    theme = models.CharField(max_length=100, blank=True, null=True)
    anchor_verse = models.CharField(max_length=200, blank=True, null=True)
    
    expected_attendance = models.PositiveIntegerField(blank=True, null=True)
    maximum_attendance = models.PositiveIntegerField(blank=True, null=True)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
        
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_id']),
            models.Index(fields=['display_code']),
            models.Index(fields=['display_identifier']),
        ]
        
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_datetime__lt=models.F('end_datetime')),
                name='check_start_before_end_datetime',
                violation_error_message="Event start_datetime must be before end_datetime."
            )
        ]
        
    def save(self, *args, **kwargs):
        self.clean()        
        super().save(*args, **kwargs)
        
    def __str__(self):
        return self.title
    
    def __repr__(self):
        return f"<Event {self.display_code} - {self.title}>"
                
    def clean(self):
        if self.start_datetime >= self.end_datetime:
            raise ValidationError("Event start_datetime must be before end_datetime.")
        if self.title:
            self.title = self.title.strip()
            self.url_safe_title = slugify(self.title)   
            
        if self.display_identifier is None:
            self.display_identifier = str(self.display_code) + str(self.event_type.code) + str(uuid.uuid4())[:6]
            
    def add_availability_window(self, window: AvailabilityWindow): # basically for extra validation
        '''
        Adds an availability window to the event.
        '''
        if window.available_from < self.start_datetime or window.available_to > self.end_datetime:
            raise ValidationError("Availability window must be within the event's start and end datetime.")
        if window.target_type != ContentType.objects.get_for_model(self):
            raise ValidationError("Availability window target must be the event itself.")
        
        window.target_id = self.id
        window.target_type = ContentType.objects.get_for_model(self)
        window.clean()
        window.save()
        return window
        
    def add_resource(self, resource: Resource): # basically for extra validation
        '''
        Adds a resource to the event.
        '''
        resource.target_id = self.id
        resource.target_type = ContentType.objects.get_for_model(self)
        resource.clean()
        resource.save()
        return resource
            
    def latest_authorisation(self):
        return (
            self.authorisations
            .order_by('-reviewed_at')
            .first()
        )
    
    @property
    def is_approved(self):
        from apps.events.models.authorization import EventAuthorizationStatusChoices
        auth = self.latest_authorisation() 
        return auth and auth.status == EventAuthorizationStatusChoices.APPROVED
