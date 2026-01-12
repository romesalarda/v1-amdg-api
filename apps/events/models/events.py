from django.db import models
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, MaxLengthValidator

from django.conf import settings

from django.contrib.contenttypes.models import ContentType
from timezone_field import TimeZoneField
from django.utils import timezone

import uuid

from apps.common.models import SoftDeleteModel, AvailabilityWindow, Resource
from apps.common.mixins import LandingImageMixin, HasAvailabilityMixin

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
    '''
    EventType model to categorize events.
    '''
    title = models.CharField(max_length=100)
    code = models.CharField(max_length=MAX_EVENT_CODE_LENGTH, unique=True) # e.g. CONF
    description = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='event_types_created', null=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        if self.title is None or self.title.strip() == '':
            raise ValidationError("EventType must have a title.")
    
    def save(self, *args, **kwargs):
        if self.title:
            self.title = self.title.strip()
        if self.code is None or self.code.strip() == '':
            self.code = slugify(self.title).upper()[:MAX_EVENT_CODE_LENGTH]
        else:
            self.code = slugify(self.code).upper()[:MAX_EVENT_CODE_LENGTH]

        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.title

class Event(SoftDeleteModel, LandingImageMixin, HasAvailabilityMixin):
    '''
    Event model to represent events within the system.
    An event can have multiple products, donations, and participants associated with it.
    Events have various statuses to represent their lifecycle, from drafting to completion.
    
    '''

    # identifier fields
    event_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) # uuid for URLS
    display_code = models.CharField(max_length=10, unique=True, validators=[
        MinLengthValidator(3),
        MaxLengthValidator(10)
    ]) # human-friendly unique code
    display_identifier = models.CharField(max_length=20, unique=True, blank=True,
                                          validators=[
                                                MinLengthValidator(6),
                                                MaxLengthValidator(20)
                                              ]) # short identifier for display
    
    # admin fields
    status = models.CharField(max_length=20, choices=EventStatusChoices.choices, default=EventStatusChoices.DRAFTING)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_events', blank=False, null=True)
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

    organisation = models.ForeignKey( # adminregister
        'organisations.Organisation', 
        on_delete=models.CASCADE, 
        related_name='events',
        verbose_name=_("Organisation"),
        help_text=_("The organisation hosting this event."),
        null=True,
        )
        
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
        self.full_clean()
        if self.title:
            self.title = self.title.strip()
            self.url_safe_title = slugify(self.title)   
            
        if self.display_identifier is None or self.display_identifier == '':
            self.display_identifier = str(str(self.display_code) + str(self.event_type.code) + str(uuid.uuid4())[:6]).upper()

        super().save(*args, **kwargs)
        
    def __str__(self):
        return self.title
    
    def __repr__(self):
        return f"<Event {self.display_code} - {self.title}>"
                
    def clean(self):
        if self.start_datetime is None or self.end_datetime is None:
            raise ValidationError("Event must have both start_datetime and end_datetime defined.")

        if self.start_datetime >= self.end_datetime:
            raise ValidationError("Event start_datetime must be before end_datetime.")
        
        if self.start_datetime == self.end_datetime:
            raise ValidationError("Event start_datetime and end_datetime cannot be the same.")            
        if self.created_by is None:
            raise ValidationError("Event must have a created_by user.")
        
            
    def latest_authorisation(self):
        return (
            self.authorizations
            .order_by('-reviewed_at')
            .first()
        )
    
    @property
    def start_date_tzaware(self):
        # timezone-aware date
        return self.start_datetime.astimezone(self.timezone).date()
    
    @property
    def end_date_tzaware(self):
        # timezone-aware date
        return self.end_datetime.astimezone(self.timezone).date()
    
    @property
    def duration_days(self):
        delta = self.end_date_tzaware - self.start_date_tzaware
        return delta.days + 1  # inclusive of start and end date
    
    @property
    def is_ongoing(self):
        now = timezone.now().astimezone(self.timezone)
        return self.start_datetime.astimezone(self.timezone) <= now <= self.end_datetime.astimezone(self.timezone)
    
    @property
    def is_approved(self):
        from apps.events.models.authorization import EventAuthorizationStatusChoices
        auth = self.latest_authorisation() 
        return auth and auth.status == EventAuthorizationStatusChoices.APPROVED

    @property
    def can_participants_register(self):
        print(self.status, self.is_approved, self.max_capacity_reached)
        return (
            self.status == EventStatusChoices.OPEN and 
            self.is_approved and 
            not self.max_capacity_reached
            )

    @property
    def can_event_be_published(self) -> bool:
        return self.is_approved and self.status in [
            EventStatusChoices.DRAFTING,
            EventStatusChoices.POSTPONED,
            EventStatusChoices.CANCELLED
        ]
    
    @property
    def max_capacity_reached(self) -> bool:
        """
        Check if maximum capacity has been reached, considering both
        confirmed attendees and pending booking intents.
        """
        if self.maximum_attendance is None:
            return False
        return self.available_capacity <= 0
    
    @property
    def number_of_attendees(self) -> int:
        return self.attendees.count()
    
    @property
    def pending_intent_capacity(self) -> int:
        """
        Calculate the number of spots currently reserved by pending booking intents.
        This prevents race conditions when multiple users are booking at capacity.
        """
        from apps.bookings.models import BookingIntent, BookingIntentStatusChoices
        from django.db.models import Sum
        from django.utils import timezone
        
        pending_intents = BookingIntent.objects.filter(
            event=self,
            status=BookingIntentStatusChoices.PENDING,
            expires_at__gt=timezone.now()
        )
        
        reserved = pending_intents.aggregate(
            total=Sum('intended_ticket_count')
        )['total'] or 0
        
        return reserved
    
    @property
    def available_capacity(self) -> int:
        """
        Calculate available capacity considering both confirmed attendees
        and pending booking intents.
        
        Returns:
            int: Number of spots available for new bookings
        """
        if self.maximum_attendance is None:
            return float('inf')  # Unlimited capacity
        
        used_capacity = self.number_of_attendees + self.pending_intent_capacity
        return max(0, self.maximum_attendance - used_capacity)

class EventSettings(models.Model):
    '''
    Settings model to manage payment and registration settings for an event.
    '''

    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='settings')

    payment_enabled = models.BooleanField(
        default=False,
        help_text="Whether payment processing is enabled for this event. Note that disabling this will also disable donations, refunds, and product selling."
    ) # whether payment processing is enabled for this event - if false, no payments can be made for products, donations, etc. 
      # Ensures events can be free if needed.

    products_require_approval = models.BooleanField(
        default=False,
        help_text="Whether products for this event require admin approval before being purchasable."    
    ) # products added to this event require admin approval before being purchasable
    
    product_publication_requires_verification = models.BooleanField(
        default=False,
        help_text="Whether products for this event require verification before being purchasable."  
    ) # products added to this event require verification before being purchasable
    product_selling_enabled = models.BooleanField(
        default=False,
        help_text="Whether selling products is enabled for this event."
    ) # whether selling products is enabled for this event
    
    orders_require_approval = models.BooleanField(
        default=True,
        help_text="Whether orders for this event require manual approval before being auto-processed on payment completion. "
                  "If False, orders will automatically transition to PROCESSING status when payment completes."
    ) # whether orders require manual approval before processing

    donation_enabled = models.BooleanField(
        default=False,
        help_text="Whether donations are enabled for this event."
    ) # whether donations are enabled for this event
    refunds_enabled = models.BooleanField(
        default=False,
        help_text="Whether refunds are enabled for this event."
    ) # whether refunds are enabled for this event
    accepting_sponsorships_enabled = models.BooleanField(
        default=False,
        help_text="Whether accepting sponsorships is enabled for this event."
    ) # whether accepting sponsorships is enabled for this event

    participants_registration_require_verification = models.BooleanField(
        default=False,
        help_text="Whether participants for this event require manual event staff verification before being fully registered."
    ) # participants registering for this event require manual verification by event staff before being fully registered

    default_timezone = TimeZoneField(default=settings.TIME_ZONE)

    class Meta:
        verbose_name = "Event Setting"
        verbose_name_plural = "Event Settings"
    
    def __str__(self):
        return f"Settings for {self.event.title}"
    
    def __repr__(self):
        return f"<EventSettings event={self.event.display_code} payment_enabled={self.payment_enabled}>"
    
    def clean(self):
        if self.event is None:
            raise ValidationError("EventSettings must be associated with an Event.")
        
        if self.payment_enabled is False:
            if self.donation_enabled:
                raise ValidationError("Donations cannot be enabled if payment processing is disabled.")
            
            if self.refunds_enabled:
                raise ValidationError("Refunds cannot be enabled if payment processing is disabled.")
            
            if self.product_selling_enabled:
                raise ValidationError("Product selling cannot be enabled if payment processing is disabled.")           
        
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)   

    def enable_payments(self):
        '''
        Enable payment-related features for the event.
        
        :param self: Description
        '''
        self.payment_enabled = True
        self.save()

    def disable_payments(self):
        '''
        Disable all payment-related features for the event.
        
        :param self: Description
        '''
        self.payment_enabled = False
        self.donation_enabled = False
        self.refunds_enabled = False
        self.product_selling_enabled = False
        self.save()

    