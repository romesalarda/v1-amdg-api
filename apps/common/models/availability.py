from django.db import models
from django.contrib.auth import get_user_model
from timezone_field import TimeZoneField
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils.translation import gettext_lazy as _

import uuid

class AvailabilityTypeChoices(models.TextChoices):
    # event wide availability types
    REFUNDS = 'REFUND_WINDOW', _('Refund Window') # refunds on an event may have specific availability
    REGISTRATION = 'REGISTRATION_WINDOW', _('Registration Window') # registrations for an event
    MERCHANDISE = 'MERCHANDISE_WINDOW', _('Merchandise Window') # merchandise availability for events
    DONATION_WINDOW = 'DONATION_WINDOW', _('Donation Window') # donations related to events
    PAYMENT_WINDOW = 'PAYMENT_WINDOW', _('Payment Window')

    # specific product availability types
    PRODUCT = 'PRODUCT_WINDOW', _('Product Window') # product specific availability
    DISCOUNT = 'DISCOUNT_WINDOW', _('Discount Window') # discount specific availability
    RESOURCE = 'RESOURCE_WINDOW', _('Resource Window') # resource specific availability
    PAYMENT_PACKAGE = 'PAYMENT_PACKAGE_WINDOW', _('Payment Package Window') # payment package specific availability

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
    timezone = TimeZoneField(default='Europe/London')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        if self.available_from >= self.available_to:
            raise ValueError("available_from must be earlier than available_to")
                
    class Meta:
        indexes = [
            models.Index(fields=['availability_id']),
            models.Index(fields=['target_type', 'target_id']),
        ]
        
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<AvailabilityWindow {self.name} (ID: {self.availability_id})>"