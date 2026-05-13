'''
contains ESTIMATED inflow model
'''
from datetime import date
from decimal import Decimal
import uuid

from django.conf import settings
from django.contrib.contenttypes import fields as content_fields
from django.contrib.contenttypes.models import ContentType
from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from djmoney.models.fields import MoneyField
from moneyed import Money

from apps.common.models.verification import RequiresVerificationModel


class DebitExpenseTypeChoices(models.TextChoices):
    DONATION = 'DONATION', 'Donation'
    TICKET_SALES = 'TICKET_SALES', 'Ticket Sales'
    MERCHANDISE_SALES = 'MERCHANDISE_SALES', 'Merchandise Sales'
    SPONSORSHIP = 'SPONSORSHIP', 'Sponsorship'
    GRANTS = 'GRANTS', 'Grants'
    OTHER = 'OTHER', 'Other'


class DebitExpense(RequiresVerificationModel):
    '''
    Tracks estimated monetary inflow for an event.

    quantity × unit_price = amount (auto-computed on save).

    The model intentionally keeps the generic relation read-only at the API layer.
    The backend may attach a target object when required, but clients must not
    write target_type or target_id directly.
    '''

    debit_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[validators.MinValueValidator(1)],
    )
    unit_price = MoneyField(max_digits=14, decimal_places=2, default_currency='GBP')
    # amount is auto-computed from quantity × unit_price; stored for queryability
    amount = MoneyField(max_digits=14, decimal_places=2, default_currency='GBP')
    description = models.TextField(
        validators=[
            validators.MinLengthValidator(10),
            validators.MaxLengthValidator(1000),
        ]
    )
    expense_type = models.CharField(
        max_length=100,
        choices=DebitExpenseTypeChoices.choices,
        default=DebitExpenseTypeChoices.OTHER,
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='debit_expenses',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='debits_created',
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
        verbose_name = 'Debit'
        verbose_name_plural = 'Debits'
        indexes = [
            models.Index(fields=['event', 'created_at']),
            models.Index(fields=['verification_status']),
            models.Index(fields=['is_settled']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f"Debit Expense: {self.description} - Amount: {self.amount}"

    def clean(self):
        super().clean()

        if self.unit_price is not None and self.unit_price.amount <= 0:
            raise ValidationError({'unit_price': 'Unit price must be greater than zero.'})

        if self.quantity is not None and self.quantity < 1:
            raise ValidationError({'quantity': 'Quantity must be at least 1.'})

        if self.paid_date and self.paid_date > date.today():
            raise ValidationError({'paid_date': 'Paid date cannot be in the future.'})

        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).only(
                'unit_price', 'unit_price_currency', 'quantity', 'verification_status'
            ).first()
            if previous and previous.verification_status in {'verified', 'processed'} and previous.unit_price:
                if (
                    previous.unit_price.amount != (self.unit_price.amount if self.unit_price else None)
                    or previous.unit_price.currency != (self.unit_price.currency if self.unit_price else None)
                    or previous.quantity != self.quantity
                ):
                    raise ValidationError({'unit_price': 'Amount cannot be changed after verification.'})

    def save(self, *args, **kwargs):
        # Auto-compute amount from quantity × unit_price
        if self.unit_price is not None and self.quantity is not None:
            self.amount = Money(
                Decimal(str(self.unit_price.amount)) * Decimal(str(self.quantity)),
                self.unit_price.currency,
            )
            self.amount_currency = self.unit_price.currency

        if self.verification_status == 'processed' and self.paid_date is None:
            self.paid_date = timezone.now().date()
        super().save(*args, **kwargs)

