from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from django.core import validators

import uuid
from core.utils.display import generate_human_readable_id, try_generate_unique_display_code
from core.utils.data import save_with_unique_field

class TicketScopeChoices(models.TextChoices):
    FULL_EVENT = 'FULL_EVENT', 'Full Event'
    SINGLE_DAY = 'SINGLE_DAY', 'Single Day'
    WORKSHOP_ONLY = 'WORKSHOP_ONLY', 'Workshop Only'

class TicketType(models.Model): # e.g. VIP, General Admission, Early Bird
    
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='ticket_types'
    )
    code = models.CharField(max_length=20, unique=True, blank=True)
    title = models.CharField(max_length=100)
    scope = models.CharField(
        max_length=20,
        choices=TicketScopeChoices.choices,
        default=TicketScopeChoices.FULL_EVENT
    )
    valid_from = models.DateTimeField(blank=True, null=True) # set based on event start date?
    valid_until = models.DateTimeField(blank=True, null=True) # need to be autoset based on event end date?
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ticket_types'
    )
    max_entries = models.PositiveIntegerField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.title} ({self.code})"
    
    def __repr__(self):
        return f"<TicketType id={self.id} code={self.code} title={self.title}>"
    
    def clean(self):
        super().clean()
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValidationError({
                'valid_until': 'Valid until date must be after valid from date.'
            })
        
    @property
    def can_delete(self) -> bool:
        '''
        A ticket type can only be deleted if there are no active tickets of this type.
        This prevents data integrity issues with existing tickets that reference this type.
        '''
        return not self.tickets.filter(status=TicketStatusChoices.ACTIVE).exists()
    
    @property
    def number_of_active_tickets(self) -> int:
        return self.tickets.filter(status=TicketStatusChoices.ACTIVE).count()
    
    @property
    def number_of_tickets(self) -> int:
        return self.tickets.count()
    
    def save(self, *args, **kwargs):
        
        if self.valid_from is None and self.event.start_datetime:
            self.valid_from = self.event.start_datetime

        if self.valid_until is None and self.event.end_datetime:
            self.valid_until = self.event.end_datetime

        if not self.code:
            try:
                self.code = try_generate_unique_display_code(
                    model_class=TicketType,
                    length=20,
                    prefix='TKT',
                    args=[self.event.display_code],
                    lookup_field='code',
                    max_attempts=5
                )
            except Exception:
                raise ValidationError("Could not generate unique ticket type code. Please try saving again.")
                
        self.clean()

        super().save(*args, **kwargs)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Ticket Type'
        verbose_name_plural = 'Ticket Types'
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'title'],
                name='unique_ticket_type_title_per_event'
            )
        ]
        
class TicketStatusChoices(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    CANCELLED = 'CANCELLED', 'Cancelled'
    USED = 'USED', 'Used'
        
class Ticket(models.Model):
    """
    Model representing a ticket for an event.
    Inherits from PayableModel to include payment-related fields and methods.
    """
    ticket_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket_type = models.ForeignKey( # is it one day pass, full event, workshop only etc.
        TicketType,
        on_delete=models.CASCADE,
        related_name='tickets'
    )
    ticket_code = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=20,
        choices=TicketStatusChoices.choices,
        default=TicketStatusChoices.ACTIVE
    )
    attendee = models.ForeignKey( # who owns/uses this ticket
        'attendee.Attendee',
        on_delete=models.CASCADE,
        related_name='tickets'
    )
    package = models.ForeignKey( # if purchased as part of a package i.e. early bird, standard
        'bookings.BookingPackage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
        help_text='The booking package used for pricing this ticket'
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    payment = models.ForeignKey( # payment associated with this ticket
        'payments.Payment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets'
    )
    uses = models.PositiveIntegerField(default=1)
    
    def __str__(self):
        return f"Ticket {self.ticket_id} for {self.attendee} - {self.ticket_type.title}"
    
    def __repr__(self):
        return f"<Ticket id={self.ticket_id} attendee={self.attendee} ticket_type={self.ticket_type}>"
    
    @property
    def booking(self):
        """Get the booking associated with this ticket through the attendee"""
        return self.attendee.booking if self.attendee else None
    
    class Meta:
        ordering = ['-issued_at']
        verbose_name = 'Ticket'
        verbose_name_plural = 'Tickets'
        constraints = [
            models.UniqueConstraint( # an attendee can have only one active ticket per ticket type
                fields=['attendee', 'ticket_type', 'status'],
                condition=models.Q(status=TicketStatusChoices.ACTIVE),
                name='unique_active_ticket_per_attendee_per_type'
            )
        ]
        indexes = [
            models.Index(fields=['ticket_code']),
            models.Index(fields=['status']),
        ]
        
    def save(self, *args, **kwargs):
        # Prevent recursion - only generate ticket_code on first save call
        skip_generation = kwargs.pop('_skip_generation', False)
        
        if not skip_generation:
            self.clean()
        
        if not self.ticket_code and not skip_generation: # todo: migrate to utility function
            # Generate unique ticket code
            for attempt in range(5):
                self.ticket_code = generate_human_readable_id(
                    50, 'TCK', str(self.attendee.attendee_display_id)[:20]
                )
                try:
                    # Try to save with generated code
                    super().save(*args, **kwargs)
                    return
                except Exception as e:
                    if attempt == 4:  # Last attempt
                        raise
                    # Reset ticket_code for next attempt
                    self.ticket_code = None
        else:
            super().save(*args, **kwargs)
        
    def clean(self):
        super().clean()
        # Validate that attendee's event matches ticket_type's event
        if self.attendee and self.ticket_type:
            if self.attendee.event_id != self.ticket_type.event_id:
                raise ValidationError({
                    'attendee': 'Attendee must belong to the same event as the ticket type.'
                })
        
        # Validate that package (if provided) matches ticket_type
        if self.package and self.ticket_type:
            if self.package.ticket_type_id != self.ticket_type.id:
                raise ValidationError({
                    'package': 'Package must be for the same ticket type as this ticket.'
                })
            
    @property
    def is_valid(self) -> bool:
        '''
        Check if the ticket is valid for use based on its status and uses remaining.
        
        :return: True if the ticket is active and has remaining uses, False otherwise.
        :rtype: bool
        '''
        if not (self.status == TicketStatusChoices.ACTIVE and self.uses > 0):
            return False

        # Two-phase invalidation: verified active refunds temporarily block ticket usage
        # before final process status transitions are applied.
        from apps.common.models import VerificationStatus
        from apps.payments.models.refunds import RefundAssociation

        ticket_type = ContentType.objects.get_for_model(Ticket)
        has_verified_refund_block = RefundAssociation.objects.filter(
            target_type=ticket_type,
            target_id=str(self.ticket_id),
            refund_request__verification_status=VerificationStatus.VERIFIED,
            refund_request__is_active=True,
        ).exists()
        return not has_verified_refund_block
        
    def use_ticket(self):
        '''
        Mark the ticket as used by decrementing the uses count.
        
        :param self: Description
        '''
        if self.status != TicketStatusChoices.ACTIVE:
            raise ValidationError("Only active tickets can be used.")
        if self.uses <= 0:
            raise ValidationError("No remaining uses on this ticket.")
        
        self.uses -= 1
        if self.uses == 0:
            self.status = TicketStatusChoices.USED
        self.save()
        
