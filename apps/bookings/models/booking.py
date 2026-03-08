from django.db import models
from django.contrib.auth import get_user_model
from apps.payments.mixins import PayableModel, PaymentMixin
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.conf import settings
from apps.bookings.models.ticket import TicketType
from django.utils import timezone
import uuid

from apps.common.models import SoftDeleteModel
from apps.common.mixins import HasAvailabilityMixin

class BookingIntentStatusChoices(models.TextChoices):
    """Status choices for booking intents."""
    PENDING = 'PENDING', _('Pending')
    COMPLETED = 'COMPLETED', _('Completed')
    EXPIRED = 'EXPIRED', _('Expired')
    CANCELLED = 'CANCELLED', _('Cancelled')

class BookingPackage(PayableModel, HasAvailabilityMixin):
    """
    Model representing a displayable booking package for an event.
    Inherits from PayableModel to include payment-related fields and discounts
    Inherits from HasAvailabilityMixin to support availability windows
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

class BookingIntent(SoftDeleteModel): # intents delete after expiry
    """
    Model representing a booking intent made by a user for an event.
    Represents a moment in time when a user has initiated a booking process.
    This is distinct from a confirmed Booking which occurs after payment.
    
    Booking intents reserve capacity to prevent race conditions during checkout.
    They expire after 20 minutes and are soft-deleted, then hard-deleted after
    a configurable number of days.
    """
    booking_intent_id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='booking_intents'
    )
    intended_ticket_count = models.PositiveIntegerField(default=1)
    
    status = models.CharField(
        max_length=20,
        choices=BookingIntentStatusChoices.choices,
        default=BookingIntentStatusChoices.PENDING
    )
    
    made_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='made_booking_intents'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    complete_delete_at = models.DateTimeField(null=True, blank=True)
        
    def __str__(self):
        return f"BookingIntent {self.booking_intent_id} by {self.made_by}"
    
    def __repr__(self):
        return f"<BookingIntent id={self.id} reference={self.booking_intent_id} user={self.made_by}>"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Booking Intent'
        verbose_name_plural = 'Booking Intents'

    def save(self, *args, **kwargs):
        # Set expiry times on creation
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(minutes=20)
        if not self.complete_delete_at:
            self.complete_delete_at = self.expires_at + timezone.timedelta(days=settings.FULL_DELETE_BOOKING_INTENTS)
        
        self.clean()
        super().save(*args, **kwargs)

    def clean(self):
        if self.intended_ticket_count < 1:
            raise ValidationError({
                'intended_ticket_count': 'Intended ticket count must be at least 1.'
            })
        
        # Only validate capacity on creation (when status is PENDING)
        if self.status == BookingIntentStatusChoices.PENDING and not self._state.adding:
            # Check if we're creating a new intent
            pass
        
        if self._state.adding and self.status == BookingIntentStatusChoices.PENDING:
            # Check capacity on creation
            if not self._can_reserve_capacity():
                raise ValidationError(
                    'Cannot create booking intent: insufficient capacity available.'
                )

    @property
    def is_expired(self) -> bool:
        """Check if the booking intent has expired."""
        if self.status in [BookingIntentStatusChoices.EXPIRED, BookingIntentStatusChoices.CANCELLED, BookingIntentStatusChoices.COMPLETED]:
            return True
        if self.expires_at and timezone.now() > self.expires_at:
            return True
        if self.deleted_at:
            return True
        return False
    
    @property
    def is_active(self) -> bool:
        """Check if the booking intent is active (can be used)."""
        return self.status == BookingIntentStatusChoices.PENDING and not self.is_expired
    
    def _can_reserve_capacity(self) -> bool:
        """Check if there is capacity available for this intent."""
        # Count pending intents for this event (excluding this one)
        from django.db.models import Sum
        pending_intents = BookingIntent.objects.filter(
            event=self.event,
            status=BookingIntentStatusChoices.PENDING,
            expires_at__gt=timezone.now()
        ).exclude(booking_intent_id=self.booking_intent_id)
        
        reserved_by_intents = pending_intents.aggregate(
            total=Sum('intended_ticket_count')
        )['total'] or 0

        if self.event.maximum_attendance is None:
            return True
        available_capacity = self.event.maximum_attendance - self.event.number_of_attendees - reserved_by_intents
        return available_capacity >= self.intended_ticket_count
    
    def can_create_booking(self) -> bool:
        """
        Determine if a booking can be created from this intent.
        Booking can be created if the intent is active and event allows registration.
        """
        if not self.is_active:
            return False
        
        if not self.event.can_participants_register:
            return False
        
        # Final capacity check
        if self.event.maximum_attendance is not None:
            if self.event.available_capacity < self.intended_ticket_count:
                return False
        
        return True
    
    def mark_expired(self, save=True):
        """Mark this intent as expired."""
        if self.status == BookingIntentStatusChoices.PENDING:
            self.status = BookingIntentStatusChoices.EXPIRED
            if save:
                self.save(update_fields=['status'])
    
    def mark_completed(self, save=True):
        """Mark this intent as completed (booking created)."""
        if self.status == BookingIntentStatusChoices.PENDING:
            self.status = BookingIntentStatusChoices.COMPLETED
            if save:
                self.save(update_fields=['status'])
    
    def cancel(self, save=True):
        """Cancel this intent, releasing the reserved capacity."""
        if self.status == BookingIntentStatusChoices.PENDING:
            self.status = BookingIntentStatusChoices.CANCELLED
            if save:
                self.save(update_fields=['status'])
    

    
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
    booking_reference = models.CharField(max_length=50, unique=True, blank=True)
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
        # Validate that all attendees belong to the same event as the booking
        if self.pk and self.event:
            mismatched_attendees = self.attendees.exclude(event=self.event)
            if mismatched_attendees.exists():
                raise ValidationError({
                    'event': f'{mismatched_attendees.count()} attendee(s) belong to a different event than this booking.'
                })
    
    def save(self, *args, **kwargs):
        if not self.booking_reference:
            from core.utils.display import try_generate_unique_display_code
            try:
                self.booking_reference = try_generate_unique_display_code(
                    model_class=Booking,
                    length=50,
                    prefix='BK',
                    args=[str(self.event.display_code)],
                    lookup_field='booking_reference',
                    max_attempts=5
                )
            except ValueError as e:
                raise ValidationError({'booking_reference': 'Could not generate unique booking reference.'})
        self.clean()
        super().save(*args, **kwargs)
    
    @property
    def total_amount(self):
        """
        Calculate total amount for this booking.
        Returns payment total_amount if payment exists (single source of truth),
        otherwise returns zero.
        """
        from djmoney.money import Money
        if self.payment:
            return self.payment.total_amount
        return Money(0, 'GBP')

    def get_metadata(self, include_ticket_pricing=False, ticket_prices=None):
        """
        Get booking metadata including attendees and frozen ticket pricing.
        
        @param include_ticket_pricing: If True, includes ticket pricing breakdown.
                                       Use when creating payments to freeze refund amounts.
        @param ticket_prices: Dict mapping ticket_id -> Money amount for frozen pricing.
                             If not provided and include_ticket_pricing=True, you must
                             manually add amounts to the metadata after ticket creation.
        @return: Dict with booking details and optionally frozen ticket pricing
        """
        attendee_metadata = []
        ticket_breakdown = {}
        
        for attendee in self.attendees.all():
            attendee_data = attendee.get_metadata()
            
            # If requested, include ticket pricing information
            if include_ticket_pricing:
                # Get tickets for this attendee
                attendee_tickets = attendee.tickets.filter(
                    status='ACTIVE'  # Only active tickets
                ).select_related('package', 'ticket_type')
                
                for ticket in attendee_tickets:
                    ticket_id = str(ticket.ticket_id)
                    
                    # Get frozen amount from provided ticket_prices dict
                    frozen_amount = None
                    if ticket_prices and ticket_id in ticket_prices:
                        amount = ticket_prices[ticket_id]
                        frozen_amount = str(amount.amount)
                        currency = amount.currency.code
                    
                    ticket_breakdown[ticket_id] = {
                        'ticket_id': ticket_id,
                        'attendee_id': str(attendee.attendee_id),
                        'attendee_name': attendee.full_name,
                        'ticket_type': ticket.ticket_type.title if ticket.ticket_type else 'Unknown',
                        'ticket_type_code': ticket.ticket_type.code if ticket.ticket_type else None,
                        'package': ticket.package.name if ticket.package else None,
                        'amount': frozen_amount,
                        'currency': currency if frozen_amount else 'GBP',
                    }
            
            attendee_metadata.append(attendee_data)

        metadata = {
            'booking_id': str(self.id),
            'booking_reference': self.booking_reference,
            'event_id': str(self.event.id),
            'attendees': attendee_metadata,
            'payment_type': 'booking_tickets',
        }
        
        if include_ticket_pricing:
            metadata['ticket_breakdown'] = ticket_breakdown
        
        return metadata
    
    def get_related_orders(self):
        """
        Get all Orders related to this Booking via booking_package relationships.
        
        When a user books a package that includes products, orders are created
        with booking_package FK linking back to the package. This helper finds
        all such orders.
        
        @return: QuerySet of Order objects linked to this booking's packages
        """
        from apps.products.models import Order
        from apps.bookings.models import Ticket
        
        # Get all booking packages from tickets belonging to this booking's attendees
        package_ids = Ticket.objects.filter(
            attendee__booking=self
        ).exclude(
            package__isnull=True
        ).values_list('package_id', flat=True).distinct()
        
        # Find orders that reference these packages
        return Order.objects.filter(
            booking_package_id__in=package_ids
        ).select_related('attendee', 'booking_package', 'payment')
    
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