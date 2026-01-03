from django.db import models
from django.contrib.auth import get_user_model
from apps.payments.mixins import PayableModel, PaymentMixin
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from apps.bookings.models.ticket import TicketType

import uuid

from apps.payments.models.discounts import DiscountRuleTypeChoices

class BookingPackage(PayableModel):
    """
    Model representing a displayable booking package for an event.
    Inherits from PayableModel to include payment-related fields and discounts
    # I.e. standard, early bird, VIP packages etc.
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='booking_packages'
    )
    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.PROTECT,
        related_name='booking_packages'
    ) # scope to a specific ticket type
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_booking_packages'
    )
    
    def __str__(self):
        return f"{self.name} ({self.event.title})"
    
    def __repr__(self):
        return f"<BookingPackage id={self.id} name={self.name} event={self.event.id}>"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Booking Package'
        verbose_name_plural = 'Booking Packages'
        constraints = [
            models.UniqueConstraint( # unique per event
                fields=['event', 'name'],
                name='unique_booking_package_name_per_event'
            )
        ] 
        
    def __str__(self):
        return f"BookingPackage {self.name} for {self.event}"
    
    def __repr__(self):
        return f"<BookingPackage id={self.id} name={self.name} event={self.event.id}>"
    
    def clean(self):
        super().clean()
        if self.ticket_type and self.ticket_type.event_id != self.event_id:
            raise ValidationError({
                'ticket_type': 'Ticket type must belong to the same event as the booking package.'
            })
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def can_use_package(self, user, attendee) -> bool:
        """
        Check if the given attendee can use this booking package based on its rules.
        Intended to be called before saving a booking with this package.

        Uses attendee's pricing context for evaluation.
        
        @param user: User instance making the booking
        @param attendee: Attendee instance for whom the booking is being made (need personal data like age)
        @return: bool indicating if the package can be used
        """
        from apps.bookings.evaluator import payment_package_applies, PaymentPackageContext
        
        context = attendee.pricing_context()
        
        package_context = PaymentPackageContext(
            user=user,
            event=self.event,
            metadata=context.metadata
        )
        
        return payment_package_applies(self, package_context)
    
    @property
    def associated_products(self):
        """
        Retrieve all products associated with this booking package.
        """
        return self.package_products.select_related('product').all()
    
# system flow Create attendee(s) -> create booking -> create tickets linked to booking and attendees
    
class Booking(models.Model, PaymentMixin):
    """
    Model representing a booking intent made by a user for an event.
    Represents a moment in time when a user has booked tickets for an event. This can be for one or more attendees.
    """
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='bookings'
    )
    booking_reference = models.CharField(max_length=50, unique=True)
    booked_at = models.DateTimeField(auto_now_add=True)
    
    made_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='made_bookings'
    )
        
    def __str__(self):
        return f"Booking {self.booking_reference} by {self.made_by}"
    
    def __repr__(self):
        return f"<Booking id={self.id} reference={self.booking_reference} user={self.made_by}>"
    
    def clean(self):
        if not self.booking_reference or not self.booking_reference.strip():
            raise ValidationError({
                'booking_reference': 'Booking reference cannot be empty.'
            })
        
        # Validate that all attendees belong to the same event as the booking
        if self.pk and self.event:
            mismatched_attendees = self.attendees.exclude(event=self.event)
            if mismatched_attendees.exists():
                raise ValidationError({
                    'event': f'{mismatched_attendees.count()} attendee(s) belong to a different event than this booking.'
                })
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def get_metadata(self):

        attendee_metadata = []
        for attendee in self.attendees.all():
            attendee_metadata.append(attendee.get_metadata())

        return {
            'booking_id': str(self.id),
            'booking_reference': self.booking_reference,
            'event_id': str(self.event.id),
            'attendees': attendee_metadata,
        }    
    class Meta:
        ordering = ['-booked_at']
        verbose_name = 'Booking'
        verbose_name_plural = 'Bookings'
        
# so we can have a package, only southeast people can see, but only have discount if over 18
        
class PackageRuleTypeChoices(models.TextChoices):
    
    IS_EVENT_STAFF = 'IS_EVENT_STAFF', _('Is Event Staff') # for staff discounts
    IS_AGE_LT = 'IS_AGE_LT', _('Is Age Less Than') # for age based discounts
    IS_AGE_GT = 'IS_AGE_GT', _('Is Age Greater Than') # for age based discounts
    ORGANISATION_MATCHES = 'ORGANISATION_MATCHES', _('Organisation Matches') # for organisation based discounts
    VALUE_MATCHES = 'VALUE_MATCHES', _('Value Matches') # for discount codes etc.
    EVENT_STAFF_ROLE_MATCHES = 'EVENT_STAFF_ROLE_MATCHES', _('Event Staff Role Matches') # for specific staff role discounts
    NAME_MATCHES = 'NAME_MATCHES', _('Name Matches') # for name based discounts
    LOCATION_MATCHES = 'LOCATION_MATCHES', _('Location Matches') # for location based discounts
    CODE_MATCHES = 'CODE_MATCHES', _('Code Matches') # for code based discounts
        
class BookingPackageRule(models.Model):
    '''
    Model representing rules for applying discounts.
    '''
    rule_id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    rule_type = models.CharField(
        max_length=30,
        choices=PackageRuleTypeChoices.choices,
        default=PackageRuleTypeChoices.IS_EVENT_STAFF
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    booking_package = models.ForeignKey(BookingPackage, on_delete=models.CASCADE, related_name='rules')
    value = models.CharField(max_length=255, help_text="Value associated with the rule (e.g. age limit, organisation name, etc.)", blank=True, null=True)
    
    active = models.BooleanField(default=True)
    
    added_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        if self.rule_type in [
            PackageRuleTypeChoices.IS_AGE_LT,
            PackageRuleTypeChoices.IS_AGE_GT,
            PackageRuleTypeChoices.ORGANISATION_MATCHES,
            PackageRuleTypeChoices.VALUE_MATCHES,
            PackageRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES,
            PackageRuleTypeChoices.NAME_MATCHES,
            PackageRuleTypeChoices.LOCATION_MATCHES,
        ] and not self.value:
            raise ValidationError(f"Rule type {self.rule_type} requires a value.")
        
        if self.rule_type in [
            PackageRuleTypeChoices.IS_AGE_GT, 
            PackageRuleTypeChoices.IS_AGE_LT
        ]:
            try:
                int(self.value)
            except (TypeError, ValueError):
                raise ValidationError(f"Rule type {self.rule_type} requires an integer value.")
    
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<DiscountRule {self.name} (ID: {self.rule_id})>"
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)