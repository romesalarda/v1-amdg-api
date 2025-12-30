from django.db import models
from django.core import validators, exceptions
from django.contrib.auth import get_user_model
from djmoney.models.fields import MoneyField
from django.conf import settings

from apps.common.models.verification import RequiresVerificationModel

from core.utils.display import try_generate_unique_code

import uuid

User = get_user_model()

# refund process
# 1. User requests refund -> RefundRequest created with status 'pending'
# 2. Admin reviews request -> marks as 'verified' or 'rejected'
# 3. If 'verified', admin processes refund externally -> marks as 'processed'

class RefundRequest(RequiresVerificationModel):
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
        return f"RefundRequest({self.id}) - {self.status}"
    
    def __repr__(self):
        return f"<RefundRequest id={self.id} status={self.status} amount={self.amount}>"
    
    def save(self, *args, **kwargs):
        self.clean()
        try:
            self.tracking_reference = try_generate_unique_code(
                model_class=RefundRequest,
                length=10,
                max_attempts=settings.MAX_ID_GENERATION_ATTEMPTS
            )
        except ValueError:
            raise exceptions.ValidationError("Could not generate a unique acceptance code. Please try again.")
        
        super().save(*args, **kwargs)
    
    def clean(self):
        if self.amount <= 0:
            raise exceptions.ValidationError("Refund amount must be greater than zero.")
        if self.amount > self.payment.amount:
            raise exceptions.ValidationError("Refund amount cannot exceed the original payment amount.")
