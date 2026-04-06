from datetime import timedelta
import uuid

from django.conf import settings
from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from djmoney.models.fields import MoneyField

from apps.common.models.verification import RequiresVerificationModel


MAX_BANK_TRANSFER_EVIDENCE_SIZE = 10 * 1024 * 1024


def validate_evidence_file_size(uploaded_file):
    if uploaded_file and uploaded_file.size > MAX_BANK_TRANSFER_EVIDENCE_SIZE:
        raise ValidationError('Evidence file must be 10MB or smaller.')


class BankTransferEvidence(RequiresVerificationModel):
    '''
    Stores proof of bank transfer activity and links it to a payment when available.

    Evidence records are retained for audit purposes even if payment linkage is
    later removed, so the payment relation is nullable.
    '''

    bank_transfer_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    transfer_id = models.CharField(max_length=255, unique=True)
    evidence_file = models.FileField(
        upload_to='bank_transfer_evidence/',
        validators=[
            validators.FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png']),
            validate_evidence_file_size,
        ],
    )
    payer_name = models.CharField(max_length=255, null=True, blank=True)
    payer_account_last4 = models.CharField(
        max_length=4,
        null=True,
        blank=True,
        validators=[validators.RegexValidator(r'^\d{4}$', message='payer_account_last4 must be exactly 4 digits.')],
    )
    amount_on_evidence = MoneyField(max_digits=14, decimal_places=2, default_currency='GBP', null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    auto_expiry_date = models.DateField(null=True, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    payment = models.ForeignKey(
        'payments.Payment',
        on_delete=models.SET_NULL,
        related_name='bank_transfer_evidence',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Bank Transfer Evidence'
        verbose_name_plural = 'Bank Transfer Evidence'
        indexes = [
            models.Index(fields=['transfer_id']),
            models.Index(fields=['verification_status']),
            models.Index(fields=['uploaded_at']),
            models.Index(fields=['payment']),
        ]

    def __str__(self):
        return f"Evidence for Transfer ID: {self.transfer_id}"

    def clean(self):
        super().clean()

        if not self.transfer_id:
            raise ValidationError({'transfer_id': 'Transfer ID is required.'})

        if self.payer_account_last4 and len(self.payer_account_last4) != 4:
            raise ValidationError({'payer_account_last4': 'payer_account_last4 must be exactly 4 digits.'})

        if self.amount_on_evidence is not None and self.amount_on_evidence.amount <= 0:
            raise ValidationError({'amount_on_evidence': 'Evidence amount must be greater than zero.'})

        if self.payment and self.amount_on_evidence and self.payment.base_amount:
            if self.amount_on_evidence.currency != self.payment.base_amount.currency:
                raise ValidationError({'amount_on_evidence': 'Evidence amount currency must match the linked payment.'})
            if self.amount_on_evidence.amount != self.payment.base_amount.amount:
                raise ValidationError({'amount_on_evidence': 'Evidence amount must match the linked payment amount.'})

    def save(self, *args, **kwargs):
        self.full_clean()

        if not self.auto_expiry_date:
            self.auto_expiry_date = (timezone.now().date() + timedelta(days=365 * 7))

        super().save(*args, **kwargs)