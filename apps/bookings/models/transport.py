from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.common.models import RequiresVerificationModel
from django.utils.translation import gettext_lazy as _  
from django.utils import timezone
import uuid

from core.utils.display import try_generate_unique_display_code


class TransportBooking(RequiresVerificationModel):
    '''
    Model representing a booking for a transport option. This can include details about the user who made the booking, the transport option they booked, and any additional information related to the booking.
    '''
    transport_booking_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transport_option = models.ForeignKey('events.EventTransportOption', on_delete=models.CASCADE, related_name='bookings')
    booking_reference = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text=_("Unique reference code for the transport booking. This will be auto-generated if not provided."))
    attendee = models.ForeignKey(
        'attendee.Attendee', on_delete=models.CASCADE, related_name='transport_bookings',
        help_text=_("The attendee who the booking is for")
        
        )

    booked_at = models.DateTimeField(auto_now_add=True)
    made_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transport_bookings_made',
        help_text=_("User who made the transport booking. This can be the attendee themselves or an admin/staff member making the booking on behalf of the attendee.")
    )
    additional_info = models.TextField(blank=True, null=True, help_text=_("Any additional information related to the transport booking (e.g., special requirements).")) 
    
    expiry_datetime = models.DateTimeField(blank=True, null=True, help_text=_("Date and time when the transport booking expires (if applicable)."))
    is_valid = models.BooleanField(default=False, help_text=_("Whether the transport booking is valid. This can be used to automatically invalidate bookings that have passed their expiry date."))
    is_cancelled = models.BooleanField(default=False, help_text=_("Whether the transport booking has been cancelled."))

    class Meta:
        verbose_name = "Transport Booking"
        verbose_name_plural = "Transport Bookings"

    def __str__(self):
        return f"Booking for {self.transport_option} by {self.attendee}"
    
    def __repr__(self):
        return f"<TransportBooking {self.booking_reference} for {self.transport_option} by {self.attendee}>"
    
    def clean(self):
        # Ensure that the transport option is valid for booking
        if not self.transport_option:
            raise ValidationError({'transport_option': 'Transport option must be specified for a transport booking.'})
        
        # Ensure that the attendee is valid
        if not self.attendee:
            raise ValidationError({'attendee': 'Attendee must be specified for a transport booking.'})
        
        # If expiry_datetime is set, ensure it's in the future
        if self.expiry_datetime and self.expiry_datetime < timezone.now():
            raise ValidationError({'expiry_datetime': 'Expiry date and time must be in the future.'})
    
    @property
    def event(self):
        '''proxied from transport option for easy access to the event associated with this booking'''
        return self.transport_option.event
    
    def save(self, *args, **kwargs):
        if not self.booking_reference:
            try:
                self.booking_reference = try_generate_unique_display_code(
                    model_class=TransportBooking,
                    length=35,
                    prefix='TBK-',
                    args=[str(self.transport_option.display_code)],
                    lookup_field='booking_reference',
                    max_attempts=5
                ).lower()
            except ValueError as e:
                raise ValidationError({'booking_reference': 'Could not generate unique transport booking reference.'})
        super().save(*args, **kwargs)
        
    def is_valid_booking(self):
        '''
        Determines if the booking is currently valid based on its validity flag and expiry date.
        '''
        if self.is_cancelled:
            return False
        if self.expiry_datetime and self.expiry_datetime < timezone.now():
            return False
        return self.is_valid
    
    def invalidate(self):
        self.is_valid = False
        self.save()

