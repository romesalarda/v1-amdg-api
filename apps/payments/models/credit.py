from datetime import date
import uuid

from django.conf import settings
from django.contrib.contenttypes import fields as content_fields
from django.contrib.contenttypes.models import ContentType
from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from djmoney.models.fields import MoneyField

from apps.common.models.verification import RequiresVerificationModel


class CreditExpenseTypeChoices(models.TextChoices):
    VENUE_COST = 'VENUE_COST', 'Venue Cost'
    FOOD_COST = 'FOOD_COST', 'Food Cost'
    CLERGY_COST = 'CLERGY_COST', 'Clergy Cost'
    CONSECRATED_RELIGIOUS_COST = 'CONSECRATED_RELIGIOUS_COST', 'Consecrated Religious Cost'
    LOGISTICS_COST = 'LOGISTICS_COST', 'Logistics Cost'
    TRANSPORT_COST = 'TRANSPORT_COST', 'Transport Cost'
    STAFF_COST = 'STAFF_COST', 'Staff Cost'
    CREATIVES_COST = 'CREATIVES_COST', 'Creatives Cost'
    TECHNICAL_COST = 'TECHNICAL_COST', 'Technical Cost'
    STIPEND = 'STIPEND', 'Stipend'
    OTHER = 'OTHER', 'Other'


class CreditExpense(RequiresVerificationModel):
    '''
    Tracks outgoing monetary value from an event.

    The model intentionally keeps the generic relation read-only at the API layer.
    The backend may attach a target object when required, but clients must not
    write target_type or target_id directly.
    '''

    credit_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    amount = MoneyField(max_digits=14, decimal_places=2, default_currency='GBP')
    description = models.TextField(
        validators=[
            validators.MinLengthValidator(10),
            validators.MaxLengthValidator(1000),
        ]
    )
    expense_type = models.CharField(
        max_length=100,
        choices=CreditExpenseTypeChoices.choices,
        default=CreditExpenseTypeChoices.OTHER,
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='credit_expenses',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='credits_created',
        null=True,
        blank=True,
    )
    paid_date = models.DateField(null=True, blank=True)
    is_settled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    target = content_fields.GenericForeignKey('target_type', 'target_id')
    target_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    target_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Credit'
        verbose_name_plural = 'Credits'
        indexes = [
            models.Index(fields=['event', 'created_at']),
            models.Index(fields=['verification_status']),
            models.Index(fields=['is_settled']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f"Credit Expense: {self.description} - Amount: {self.amount}"

    def clean(self):
        super().clean()

        if self.amount is not None and self.amount.amount <= 0:
            raise ValidationError({'amount': 'Credit amount must be greater than zero.'})

        if self.paid_date and self.paid_date > date.today():
            raise ValidationError({'paid_date': 'Paid date cannot be in the future.'})

        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).only(
                'amount', 'amount_currency', 'verification_status'
            ).first()
            if previous and previous.verification_status in {'verified', 'processed'} and previous.amount:
                previous_amount = previous.amount.amount
                previous_currency = previous.amount.currency
                current_amount = self.amount.amount if self.amount else None
                current_currency = self.amount.currency if self.amount else None
                if previous_amount != current_amount or previous_currency != current_currency:
                    raise ValidationError({'amount': 'Amount cannot be changed after verification.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.verification_status == 'processed' and self.paid_date is None:
            self.paid_date = timezone.now().date()
        super().save(*args, **kwargs)