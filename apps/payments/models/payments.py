from decimal import Decimal
from apps.payments.mixins import PayableModel
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from djmoney.money import Money

from core.utils.display import generate_human_readable_id, generate_alphanumeric_id
from core.utils.data import save_with_unique_field

from apps.payments.models.methods import PaymentMethod, PaymentMethodTypeChoices

import uuid

User = get_user_model()

class PaymentStatusChoices(models.TextChoices):
    DRAFTING = 'DRAFTING', 'Drafting'
    PENDING = 'PENDING', 'Pending'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    FAILED = 'FAILED', 'Failed'
    PENDING_REFUND = 'PENDING_REFUND', 'Pending Refund'
    REFUNDED = 'REFUNDED', 'Refunded'
    
ALLOWED_STATUS_TRANSITIONS = {
    PaymentStatusChoices.DRAFTING: [
        PaymentStatusChoices.PENDING,
    ],
    PaymentStatusChoices.PENDING: [
        PaymentStatusChoices.COMPLETED,
        PaymentStatusChoices.FAILED,
        PaymentStatusChoices.CANCELLED,
    ],
    PaymentStatusChoices.COMPLETED: [
        PaymentStatusChoices.PENDING_REFUND, # pending full refund
    ],
    PaymentStatusChoices.PENDING_REFUND: [
        PaymentStatusChoices.REFUNDED, # full refund completed
    ],
}

MAX_PAYMENT_GENERATION_ATTEMPTS = 5
MAX_LENGTH_BANK_REF = 12

class Payment(PayableModel):
    
    payment_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    payment_reference = models.CharField(max_length=30, unique=True, blank=True)
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='paid by'
    )
    
    description = models.TextField(blank=True, null=True)
    
    stripe_payment_intent = models.CharField(max_length=255, blank=True, null=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True, null=True)
    bank_transfer_reference = models.CharField(max_length=255, blank=True, null=True)
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
    target_id = models.PositiveIntegerField(null=True, blank=True)
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
    
    def save(self, *args, **kwargs):
        
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
            except IntegrityError:
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
        super().clean()

    def absolute_amount(self) -> Money:
        '''
        Returns the absolute amount of the payment, ignoring any modifiers.
        '''
        return Decimal(self.base_amount.amount).quantize(Decimal('0.01'))

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