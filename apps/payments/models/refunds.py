from django.db import models
from django.core import validators, exceptions
from django.contrib.auth import get_user_model
from djmoney.models.fields import MoneyField

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from djmoney.money import Money

from django.conf import settings

from apps.common.models.verification import RequiresVerificationModel, VerificationStatus
from apps.common.mixins import HasAvailabilityMixin

from core.utils.display import try_generate_unique_code
from decimal import Decimal
import uuid

User = get_user_model()

# refund process
# 1. User requests refund -> RefundRequest created with status 'pending'
# 2. Admin reviews request -> marks as 'verified' or 'rejected'
# 3. If 'verified', admin processes refund externally -> marks as 'processed'

REFUND_TARGET_ID = 'refund_amount'  # The property/method name to get refunded amount from associated objects
class RefundRequest(RequiresVerificationModel): # inherits verification fields 
    '''
    RefundRequest model to handle refund requests for payments.

    Processing Steps:
    1. User requests a refund, creating a RefundRequest with status 'pending'.
    2. An admin reviews the request and marks it as 'verified' or 'rejected'.
    3. If marked 'verified', the admin processes the refund externally and marks it as 'processed'.

    '''

    refund_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) # Public identifier
    tracking_reference = models.CharField(max_length=100, unique=True) # e.g., participant reference or order number

    payment = models.ForeignKey(
        'payments.Payment',
        on_delete=models.CASCADE,
        related_name='refund_requests'
    )
    amount = MoneyField(max_digits=10, decimal_places=2, default_currency='GBP')
    reason = models.TextField(validators=[validators.MaxLengthValidator(1000), validators.MinLengthValidator(10)])

    requested_at = models.DateTimeField(auto_now_add=True)
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='refund_requests_made'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='refund_requests_processed'
    )

    metadata = models.JSONField(default=dict, blank=True) # contains stripe_refund_id etc.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'Refund Request'
        verbose_name_plural = 'Refund Requests'
        constraints = [
            models.UniqueConstraint(fields=['payment', 'is_active'], name='unique_active_refund_per_payment', condition=models.Q(is_active=True))
        ]

    def __str__(self):
        return f"RefundRequest({self.id}) - {self.verification_status}"
    
    def __repr__(self):
        return f"<RefundRequest id={self.id} status={self.verification_status} amount={self.amount}>"
    
    def save(self, *args, **kwargs):
        self.clean()
        try:
            self.tracking_reference = try_generate_unique_code(
                model_class=RefundRequest,
                length=10,
                max_attempts=settings.MAX_ID_GENERATION_ATTEMPTS,
                lookup_field='tracking_reference'
            )
        except ValueError:
            raise exceptions.ValidationError("Could not generate a unique acceptance code. Please try again.")
        if not self.amount or self.amount.amount == 0:
            self.amount = Money(self.get_refund_amount(), self.payment.amount.currency)

        super().save(*args, **kwargs)
    
    def clean(self):
        if self.amount.amount <= 0:
            raise exceptions.ValidationError("Refund amount must be greater than zero.")
        if self.amount > self.payment.base_amount:
            raise exceptions.ValidationError("Refund amount cannot exceed the original payment amount.")
        
    def associate_with(self, obj, amount, metadata=None):
        '''
        Associate this refund request with another entity with a FROZEN amount.
        
        SECURITY: Amount must come from payment.metadata (frozen at payment time)
        to prevent dynamic recalculation vulnerabilities.

        @param obj: The object to associate with (must be a model instance).
        @param amount: Money object - FROZEN amount from payment metadata
        @param metadata: Optional dict with frozen pricing details from payment metadata
        @return: RefundAssociation instance linking the refund request to the object.
        '''
        if not isinstance(obj, models.Model):
            raise ValueError("Can only associate with Django model instances.")
        
        if not isinstance(amount, Money):
            raise ValueError("Amount must be a Money object.")
        
        if amount.amount <= 0:
            raise ValueError("Refund amount must be greater than zero.")

        # Check if total refunds would exceed payment amount
        current_refunded = self.get_refund_amount()
        if amount > (self.payment.base_amount - current_refunded):
            raise ValueError(
                f"Cannot associate refund: total refunds ({current_refunded + amount}) "
                f"would exceed payment amount ({self.payment.base_amount})."
            )

        refund = RefundAssociation.objects.create(
            refund_request=self,
            target_object=obj,
            target_type=ContentType.objects.get_for_model(obj),
            target_id=obj.pk,
            amount=amount,  # Store frozen amount
            metadata=metadata or {}
        )
        return refund
    
    def get_refund_amount(self):
        '''
        Returns the total amount refunded across all associated entities.
        Uses FROZEN amounts stored in RefundAssociation, never recalculates.

        @return: Total refunded amount as a Money object.
        '''
        total = Money(0, self.payment.base_amount.currency)
        associations = self.associations.all()
        for assoc in associations:
            total += assoc.amount  # Use frozen amount from association

        return total
    
    def absolute_amount(self) -> Money:
        '''
        Returns the absolute amount of the refund request.

        @return: Absolute amount as a Money object.
        '''
        # 2 d.p
        return Decimal(self.amount.amount).quantize(Decimal('0.01'))

    
    @property
    def is_partial(self):
        '''
        Check if the refund request is for a partial amount.

        @return: True if partial refund, False if full refund.
        '''
        return self.amount < self.payment.base_amount
    
    @property
    def is_full(self):
        '''
        Check if the refund request is for the full amount.

        @return: True if full refund, False if partial refund.
        '''
        return self.amount == self.payment.base_amount
    
    def is_refundable(self, datetime: timezone.datetime) -> bool: # TODO: Test me
        '''
        Check if the payment is eligible for a refund within the event's refund window.

        @return: True if refundable, False otherwise.
        '''
        from apps.common.models import AvailabilityTypeChoices
        from apps.payments.models.payments import PaymentStatusChoices

        if not self.payment.status == PaymentStatusChoices.COMPLETED or not self.payment.event.settings.refunds_enabled:
            return False
        
        return self.payment.event.is_within_availability_window(
            AvailabilityTypeChoices.REFUNDS, datetime,
            true_if_non_existent=True
            )
    
    def mark_verified(self, verifier):
        """
        Mark refund as verified and automatically trigger Stripe refund.
        
        Args:
            verifier: User who verified the refund
            
        Raises:
            ValidationError: If Stripe refund fails
        """
        self.is_active
        
        # Trigger Stripe refund if payment has Stripe PaymentIntent
        if self.payment.stripe_payment_intent:
            from apps.payments.services.stripe.refunds import RefundService
            from apps.payments.services.stripe.exceptions import StripeServiceError
            from django.core.exceptions import ValidationError
            import logging
            
            logger = logging.getLogger(__name__)
            
            try:
                # Create Stripe refund
                stripe_refund = RefundService.create(
                    payment_intent_id=self.payment.stripe_payment_intent,
                    amount=self.amount,
                    reason=RefundService.REASON_REQUESTED_BY_CUSTOMER,
                    metadata={
                        'refund_id': str(self.refund_id),
                        'tracking_reference': self.tracking_reference,
                        'payment_reference': self.payment.payment_reference,
                    },
                    refund_reference=self.tracking_reference
                )
                
                # Store Stripe refund ID
                if not self.metadata:
                    self.metadata = {}
                self.metadata['stripe_refund_id'] = stripe_refund.id
                self.metadata['stripe_refund_status'] = stripe_refund.status
                self.metadata['stripe_refund_created_at'] = str(stripe_refund.created)
                
                logger.info(
                    f"Created Stripe refund {stripe_refund.id} for RefundRequest {self.tracking_reference}"
                )
                
            except StripeServiceError as e:
                logger.error(f"Failed to create Stripe refund: {e.message}")
                raise ValidationError(
                    f"Stripe refund failed: {e.user_message}. "
                    "Please verify the refund manually or try again."
                )
        
        return super().mark_verified(verifier)
    
    def mark_processed(self, processor=None):
        self.is_active = False
        return super().mark_processed(processor)
    
    def mark_rejected(self, verifier):
        self.is_active = False
        return super().mark_rejected(verifier)
        
class RefundAssociation(models.Model):
    '''
    Model to associate refunds with various entities like orders or bookings.
    Stores a frozen snapshot of the refund amount to prevent dynamic recalculation vulnerabilities.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    refund_request = models.ForeignKey(
        RefundRequest,
        on_delete=models.CASCADE,
        related_name='associations'
    )
    target_id = models.CharField(max_length=255)  # Support both integer and UUID IDs
    target_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='refund_association_targets'
    )
    target_object = GenericForeignKey('target_type', 'target_id')
    
    # Frozen amount from payment metadata - NEVER recalculated dynamically
    amount = MoneyField(
        max_digits=10,
        decimal_places=2,
        default_currency='GBP',
        help_text='Frozen refund amount from payment metadata at time of payment',
        default=Money(0, 'GBP')
    )

    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Frozen metadata snapshot from payment, including pricing breakdown'
    )

    class Meta:
        verbose_name = 'Refund Association'
        verbose_name_plural = 'Refund Associations'
        unique_together = ('refund_request', 'target_type', 'target_id')

    def __str__(self):
        return f"RefundAssociation(refund_request={self.refund_request.id}, object={self.target_object})"
    
    def __repr__(self):
        return f"<RefundAssociation refund_request={self.refund_request.id} object={self.target_object}>"
    
    def save(self, *args, **kwargs):
        self.clean()
        if not self.description:
            self.description = (
                f"Refund of {self.amount} for {self.target_object} "
                f"(Request: {self.refund_request.tracking_reference})"
            )
        super().save(*args, **kwargs)
    
    def clean(self):
        """Validate frozen amount is positive"""
        if hasattr(self, 'amount') and self.amount and self.amount.amount <= 0:
            raise exceptions.ValidationError("Refund association amount must be greater than zero.")
        
class RefundPolicyTypeChoices(models.TextChoices):
    FULL_REFUND = 'full_refund', 'Full Refund'
    PARTIAL_REFUND = 'partial_refund', 'Partial Refund'
    NON_REFUNDABLE = 'non_refundable', 'Non-Refundable'
class RefundPolicy(models.Model):
    '''
    Model to define refund policies for events.
    '''
    event = models.OneToOneField(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='refund_policy'
    )
    policy_type = models.CharField(
        max_length=20,
        choices=RefundPolicyTypeChoices.choices,
        default=RefundPolicyTypeChoices.FULL_REFUND
    )
    refundable_within_days = models.PositiveIntegerField(
        default=14,
        help_text='Number of days before event start date when full refunds are allowed.'
    )

    percentage_refund = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=100.00,
        help_text='Percentage of the original amount to refund for partial refunds.'
    )
    notes = models.TextField(
        blank=True,
        help_text='Additional notes regarding the refund policy.'
    )

    class Meta:
        verbose_name = 'Refund Policy'
        verbose_name_plural = 'Refund Policies'

    def __str__(self):
        return f"RefundPolicy(event={self.event.name})"
    
    def __repr__(self):
        return f"<RefundPolicy event={self.event.name}>"
    
    def is_refundable(self, request_date: timezone.datetime) -> bool:
        '''
        Check if a refund is allowed based on the request date.

        @param request_date: The date when the refund is requested.
        @return: True if refundable, False otherwise.
        '''
        timezone = self.event.timezone
        tz_aware_request_date = timezone.localize(request_date.replace(tzinfo=None))
        event_start_date = self.event.start_datetime.astimezone(timezone)
        days_before_event = (event_start_date - tz_aware_request_date).days
        if self.event.settings.refunds_enabled is False:
            return False
        
        if self.policy_type == RefundPolicyTypeChoices.NON_REFUNDABLE:
            return False
        elif self.policy_type == RefundPolicyTypeChoices.FULL_REFUND:
            return days_before_event >= self.refundable_within_days
        elif self.policy_type == RefundPolicyTypeChoices.PARTIAL_REFUND:
            return days_before_event >= 0  # Allow partial refunds up to event start
        
    def calculate_refund_amount(self, original_amount: Money) -> Money:
        '''
        Calculate the refund amount based on the policy.

        @param original_amount: The original payment amount.
        @return: The calculated refund amount as a Money object.
        '''
        if self.policy_type == RefundPolicyTypeChoices.NON_REFUNDABLE:
            return Money(0, original_amount.currency)
        elif self.policy_type == RefundPolicyTypeChoices.FULL_REFUND:
            return original_amount
        elif self.policy_type == RefundPolicyTypeChoices.PARTIAL_REFUND:
            refund_amount = (original_amount.amount * (self.percentage_refund / 100)).quantize(Decimal('0.01'))
            return Money(refund_amount, original_amount.currency)