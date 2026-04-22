from decimal import Decimal
import logging
from apps.payments.mixins import PayableModel
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core import validators
from django.db import IntegrityError, transaction
from djmoney.money import Money
from djmoney.models.fields import MoneyField

from core.utils.display import generate_human_readable_id, generate_alphanumeric_id
from core.utils.data import save_with_unique_field

from apps.payments.models.methods import PaymentMethod, PaymentMethodTypeChoices

import uuid

User = get_user_model()

logger = logging.getLogger(__name__)

class PaymentStatusChoices(models.TextChoices):
    DRAFTING = 'DRAFTING', 'Drafting'
    PENDING = 'PENDING', 'Pending'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    FAILED = 'FAILED', 'Failed'
    PENDING_REFUND = 'PENDING_REFUND', 'Pending Refund'
    REFUNDED = 'REFUNDED', 'Refunded'
    PARTIALLY_REFUNDED = 'PARTIALLY_REFUNDED', 'Partially Refunded'
    
ALLOWED_STATUS_TRANSITIONS = {
    PaymentStatusChoices.DRAFTING: [
        PaymentStatusChoices.PENDING,
    ],
    PaymentStatusChoices.PENDING: [
        PaymentStatusChoices.DRAFTING,
        PaymentStatusChoices.COMPLETED,
        PaymentStatusChoices.FAILED,
        PaymentStatusChoices.CANCELLED,
    ],
    PaymentStatusChoices.COMPLETED: [
        PaymentStatusChoices.REFUNDED, # full refund
        PaymentStatusChoices.PENDING_REFUND, # pending full refund
        PaymentStatusChoices.PARTIALLY_REFUNDED, # pending partial refund
    ],
    PaymentStatusChoices.PENDING_REFUND: [
        PaymentStatusChoices.REFUNDED, # full refund completed
        PaymentStatusChoices.PARTIALLY_REFUNDED
    ],
    PaymentStatusChoices.PARTIALLY_REFUNDED: [
        PaymentStatusChoices.REFUNDED, # full refund completed
    ],
}

MAX_PAYMENT_GENERATION_ATTEMPTS = 5
MAX_LENGTH_BANK_REF = 6

class Payment(PayableModel):
    '''
    Centralised payment model to track all payments across the system, linked to specific events and users, with support for multiple payment methods and integration with Stripe. 
    Payment records are immutable once completed to ensure data integrity, with a separate PaymentHistoryAction model to track any changes or actions taken on payments for audit purposes.
    '''
    payment_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    payment_reference = models.CharField(max_length=30, unique=True, blank=True)
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='paid by'
    )
    
    description = models.TextField(blank=True, null=True)
    
    # Stripe integration fields
    stripe_payment_intent = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True, db_index=True, help_text='Stripe customer ID for recurring payments')
    bank_transfer_reference = models.CharField(max_length=255, blank=True, null=True)
    bank_transfer_required_immediately = models.BooleanField(
        default=False,
        help_text='Snapshot of payment method policy at payment creation time.'
    )
    metadata = models.JSONField(blank=True, null=True) # data of info when the payment was made (ABSOLUTE)
    
    status = models.CharField(
        max_length=20,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.DRAFTING
    )
    
    target_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    target_id = models.CharField(max_length=255, null=True, blank=True)
    target = GenericForeignKey('target_type', 'target_id')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.PROTECT,
        related_name='payments'
    )
    method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name='payments',
        null=True,
        blank=True
    )

    base_amount = MoneyField(
        max_digits=14,
        decimal_places=2,
        default_currency='GBP',
        null=True,
        blank=True,
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        indexes = [
            models.Index(fields=['payment_reference']),
            models.Index(fields=['payment_id']),
            models.Index(fields=['status']),
            models.Index(fields=['target_type', 'target_id']),
        ]
        
    def __str__(self):
        return f"Payment {self.payment_reference} by {self.user}"
    
    def __repr__(self):
        return f"<Payment id={self.payment_id} reference={self.payment_reference} user={self.user}>"

    @property
    def final_amount(self) -> Money:
        '''
        Returns the final amount of the payment after applying percentage modifiers, but before refunds.
        '''
        amount = self.modified_amount or Money(0, 'GBP')
        if self.total_refunded_amount:
            amount -= Money(self.total_refunded_amount, self.modified_amount.currency)

        return amount

    @property
    def total_refunded_amount(self) -> float:
        '''
        Calculate the total refunded amount for this payment by summing all related refunds.
        '''
        return self.refund_requests.aggregate(total=models.Sum('amount'))['total']

    @property
    def outstanding_bank_transfer_evidence(self) -> bool:
        '''
        Check if there is outstanding bank transfer evidence that has not been verified for this payment. Only applicable for bank transfer payments.
        '''
        if self.method and self.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
            return not self.bank_transfer_evidence.filter(verification_status='verified').exists()
        return False

    @property
    def is_partially_refunded(self) -> bool:
        return self.status == PaymentStatusChoices.PARTIALLY_REFUNDED
    
    @property
    def is_refunded(self) -> bool:
        return self.status == PaymentStatusChoices.REFUNDED
    
    def save(self, *args, **kwargs):

        if not self.pk:
            # Set original amount only on creation
            if self.base_amount is not None:
                self.original_amount = self.base_amount

            if self.method:
                self.bank_transfer_required_immediately = bool(
                    self.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER
                    and self.method.bank_transfer_required_immediately
                )
        
        for _ in range(MAX_PAYMENT_GENERATION_ATTEMPTS): # extra safety loop as payments are critical
            if not self.payment_reference:
                self.payment_reference = generate_human_readable_id(
                    30, 'PAY', str(self.user.id)[:8], str(self.event.id)[:8]
                )

            if (
                self.method
                and self.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER
                and not self.bank_transfer_reference
            ):
                #! must generate bank transfer reference only if payment method is bank transfer
                self.bank_transfer_reference = generate_alphanumeric_id(MAX_LENGTH_BANK_REF) # TODO: change this to make it somewhat obvious incase someone needs to type it instead of copy/paste

            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as e:
                logger.warning(
                    f"IntegrityError when saving Payment. Likely due to duplicate payment_reference or bank_transfer"
                    f"_reference. Retrying generation. PaymentReference: {self.payment_reference}, "
                    f"BankTransferReference: {self.bank_transfer_reference}"
                )
                logger.error(e)
                # reset fields that must be regenerated
                self.payment_reference = None
                self.bank_transfer_reference = None

        raise RuntimeError("Unable to generate unique payment identifiers")
    
    def clean(self):
        
        if self.method and self.method.event_id != self.event_id:
            raise ValidationError("Payment method does not belong to the same event as the payment.")
        
        if self.pk:
            old_payment = Payment.objects.get(pk=self.pk)
            if old_payment.status != self.status:
                allowed_transitions = ALLOWED_STATUS_TRANSITIONS.get(old_payment.status, [])
                if self.status not in allowed_transitions:
                    raise ValidationError(
                        f"Invalid status transition from {old_payment.status} to {self.status}."
                    )
        if self.percentage_modifier != 0:
            raise ValidationError("Payments cannot have percentage modifiers.")
        super().clean(skip_base_amount_check=False)

    def absolute_amount(self) -> Money:
        '''
        Returns the absolute amount of the payment, ignoring any modifiers.
        '''
        return Decimal(self.base_amount.amount).quantize(Decimal('0.01'))
    
    def transition_to(self, new_status: str) -> None:
        """
        Transition payment to a new status with validation.
        
        Args:
            new_status: Target status from PaymentStatusChoices
            
        Raises:
            ValidationError: If transition is not allowed
        """
        if self.status == new_status:
            return  # Already in target status (idempotent)

        # Bank transfer payments must have verified evidence before completion.
        if (
            new_status == PaymentStatusChoices.COMPLETED
            and self.method
            and self.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER
            and not self.bank_transfer_evidence.filter(verification_status='verified').exists()
        ):
            raise ValidationError(
                "Cannot complete bank transfer payment without verified bank transfer evidence."
            )
        
        allowed_transitions = ALLOWED_STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed_transitions:
            raise ValidationError(
                f"Invalid status transition from {self.status} to {new_status}. "
                f"Allowed transitions: {', '.join(allowed_transitions) or 'none'}"
            )
        
        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])
    
    def prepare_stripe_metadata(self) -> dict:
        """
        Prepare metadata for Stripe PaymentIntent in Stripe's format.
        
        Flattens nested order/booking data to comply with Stripe limits:
        - Max 50 keys
        - Max 500 characters per value
        - Only strings, numbers, booleans allowed
        
        Returns:
            dict: Flattened metadata for Stripe
        """
        metadata = {
            'payment_id': str(self.payment_id),
            'payment_reference': self.payment_reference,
            'event_id': str(self.event_id),
            'event_title': self.event.title[:500],  # Truncate to Stripe limit
            'user_id': str(self.user_id),
            'user_email': self.user.email[:500],
        }
        
        # Add target-specific metadata
        if self.target:
            target = self.target
            metadata['target_type'] = self.target_type.model
            metadata['target_id'] = str(self.target_id)
            
            # Order-specific metadata
            if hasattr(target, 'order_reference_id'):
                metadata['order_reference'] = target.order_reference_id[:500]
                metadata['order_status'] = target.status
                
                # Add order items summary (limited keys)
                if hasattr(target, 'order_items'):
                    items = target.order_items.all()[:10]  # Limit to first 10 items
                    metadata['item_count'] = str(len(items))
                    for idx, item in enumerate(items, 1):
                        prefix = f'item_{idx}'
                        metadata[f'{prefix}_title'] = item.product_variant.product.title[:100]
                        metadata[f'{prefix}_quantity'] = str(item.quantity)
                        metadata[f'{prefix}_price'] = str(item.total_price.amount)
            
            # Booking-specific metadata
            elif hasattr(target, 'booking_reference'):
                metadata['booking_reference'] = target.booking_reference[:500]
                
                # Add attendee count
                if hasattr(target, 'attendees'):
                    metadata['attendee_count'] = str(target.attendees.count())
        
        return metadata

class PaymentHistoryAction(models.Model):
    '''
    Model representing an action taken on a payment for history tracking.
    '''
    action_id = models.UUIDField(default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='history_actions'
    )
    description = models.TextField()
    metadata = models.JSONField(blank=True, null=True, default=dict) # extra data about the action
    action = models.CharField(max_length=100) # e.g., 'STATUS_CHANGED',
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_history_actions'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Payment History Action'
        verbose_name_plural = 'Payment History Actions'
        
    def __str__(self):
        return f"PaymentHistoryAction {self.action} on Payment {self.payment.payment_reference}"
    
    def __repr__(self):
        return f"<PaymentHistoryAction id={self.id} action={self.action} payment={self.payment.payment_reference}>"