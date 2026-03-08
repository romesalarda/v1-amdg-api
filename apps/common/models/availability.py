from django.db import models
from django.contrib.auth import get_user_model
from timezone_field import TimeZoneField
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils.translation import gettext_lazy as _
from django.conf import settings

import uuid

class AvailabilityTypeChoices(models.TextChoices):
    # event wide availability types
    REFUNDS = 'REFUND_WINDOW', _('Refund Window') # refunds on an event may have specific availability
    REGISTRATION = 'REGISTRATION_WINDOW', _('Registration Window') # registrations for an event
    MERCHANDISE = 'MERCHANDISE_WINDOW', _('Merchandise Window') # merchandise availability for events
    DONATION_WINDOW = 'DONATION_WINDOW', _('Donation Window') # donations related to events
    PAYMENT_WINDOW = 'PAYMENT_WINDOW', _('Payment Window')

    # specific product availability types
    PRODUCT = 'PRODUCT_WINDOW', _('Product Window') # defines when a product is available for purchase
    PRODUCT_PREVIEW_WINDOW = 'PRODUCT_PREVIEW_WINDOW', _('Product Preview Window') # product preview availability before actual product window opens

    DISCOUNT = 'DISCOUNT_WINDOW', _('Discount Window') # discount specific availability
    RESOURCE = 'RESOURCE_WINDOW', _('Resource Window') # resource specific availability

    PAYMENT_PACKAGE = 'PAYMENT_PACKAGE_WINDOW', _('Payment Package Window') # payment package specific availability
    PAYMENT_PACKAGE_PREVIEW_WINDOW = 'PAYMENT_PACKAGE_PREVIEW_WINDOW', _('Payment Package Preview Window') # payment package preview availability before actual package window opens
class AvailabilityWindow(models.Model):
    '''
    Model representing a generic availability window.
    '''
    availability_id = models.UUIDField(default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    availability_type = models.CharField(
        max_length=30,
        choices=AvailabilityTypeChoices.choices,
        default=AvailabilityTypeChoices.REGISTRATION
    )
    
    target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_id = models.PositiveIntegerField()
    target = GenericForeignKey('target_type', 'target_id')

    available_from = models.DateTimeField()
    available_to = models.DateTimeField()
    timezone = TimeZoneField(default=settings.TIME_ZONE)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        if self.available_from >= self.available_to:
            raise ValidationError("available_from must be earlier than available_to")
        
        # Check for overlapping windows of the same type on the same target
        if self.target_type_id and self.target_id:
            overlapping = AvailabilityWindow.objects.filter(
                target_type=self.target_type,
                target_id=self.target_id,
                availability_type=self.availability_type
            ).exclude(pk=self.pk if self.pk else None)
            
            for window in overlapping:
                # Check if there's any overlap
                if (self.available_from <= window.available_to and 
                    self.available_to >= window.available_from):
                    raise ValidationError(
                        f"This window overlaps with existing window '{window.name}' "
                        f"({window.available_from} to {window.available_to})"
                    )
                
    class Meta:
        indexes = [
            models.Index(fields=['availability_id']),
            models.Index(fields=['target_type', 'target_id']),
        ]
        
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<AvailabilityWindow {self.name} (ID: {self.availability_id})>"
    
    def within_window(self, check_datetime):
        '''
        Check if a given datetime is within the availability window.
        '''
        return self.available_from <= check_datetime <= self.available_to


class AvailabilityWindowTemplate(models.Model):
    '''
    Model representing a template for creating multiple availability windows.
    Supports both predefined system templates and custom organization templates.
    '''
    template_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    # Template type: predefined system templates or custom organization templates
    is_predefined = models.BooleanField(default=False)
    
    # If custom template, link to organization
    organisation = models.ForeignKey(
        'organisations.Organisation',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='availability_templates'
    )
    
    # JSON field storing the template configuration
    # Structure: [
    #   {
    #     "name": "Registration Window",
    #     "availability_type": "REGISTRATION_WINDOW",
    #     "offset_from_event_start": -30,  # days before event start
    #     "offset_to_event_start": -1,     # days before event start
    #     "description": "Early bird registration"
    #   }
    # ]
    windows_config = models.JSONField(default=list)
    
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_availability_templates'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['template_id']),
            models.Index(fields=['is_predefined']),
            models.Index(fields=['organisation']),
        ]
        ordering = ['is_predefined', '-created_at']
        
    def __str__(self):
        return f"{self.name} ({'Predefined' if self.is_predefined else 'Custom'})"
    
    def apply_to_event(self, event, timezone=None):
        '''
        Apply this template to an event, creating all configured availability windows.
        
        Args:
            event: Event instance to apply template to
            timezone: Optional timezone string, defaults to event's timezone
            
        Returns:
            List of created AvailabilityWindow instances
        '''
        from datetime import timedelta
        from django.utils import timezone as django_timezone
        
        created_windows = []
        event_timezone = timezone or event.timezone
        event_start = event.start_datetime
        
        for window_config in self.windows_config:
            # Calculate dates based on offsets from event start
            offset_from = window_config.get('offset_from_event_start', 0)
            offset_to = window_config.get('offset_to_event_start', 0)
            
            available_from = event_start + timedelta(days=offset_from)
            available_to = event_start + timedelta(days=offset_to)
            
            # Create the availability window
            window = AvailabilityWindow.objects.create(
                name=window_config.get('name', 'Unnamed Window'),
                description=window_config.get('description', ''),
                availability_type=window_config.get('availability_type', 'REGISTRATION_WINDOW'),
                target_type=ContentType.objects.get_for_model(event),
                target_id=event.id,
                available_from=available_from,
                available_to=available_to,
                timezone=event_timezone
            )
            created_windows.append(window)
        
        return created_windows
