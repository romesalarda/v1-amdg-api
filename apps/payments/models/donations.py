from decimal import Decimal
from django.db import models
from django.core import validators, exceptions
from django.contrib.auth import get_user_model
from djmoney.models.fields import MoneyField
from djmoney.money import Money

from django.conf import settings
from apps.common.models.verification import RequiresVerificationModel

from core.utils.display import try_generate_unique_code

import uuid

User = get_user_model()
class Donation(RequiresVerificationModel): # don't inherit from PayableModel as discounts, fine-grain money manipulation etc. don't apply
    '''
    Donation model to handle donations.
    
    Donation Processing Steps:
    1. User makes a donation, creating a Donation with status 'pending'.
    2. An admin reviews the donation and marks it as 'verified' or 'rejected'.
    3. If marked 'verified', the donation is processed and marked as 'processed'.
    '''

    donation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) # Public identifier
    tracking_reference = models.CharField(max_length=50, unique=True) # e.g., participant reference or order number
    amount = MoneyField(max_digits=10, decimal_places=2, default_currency='GBP')

    donated_at = models.DateTimeField(auto_now_add=True)
    donated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='donations_made'
    )

    payment = models.ForeignKey(
        'payments.Payment',
        on_delete=models.CASCADE,
        related_name='donations',
        null=True,
        blank=True
    )

    def __str__(self):
        return f"Donation({self.id}) - {self.payment.status if self.payment else 'No Payment'} - {self.amount} by {self.donated_by.username if self.donated_by else 'Anonymous'}"
    
    def __repr__(self):
        return f"<Donation id={self.id} donation_id={self.donation_id} amount={self.amount} status={self.verification_status}>"
    
    def save(self, *args, **kwargs):
        self.clean()
        try:
            if not self.tracking_reference:
                self.tracking_reference = try_generate_unique_code(
                    model_class=Donation,
                    length=10,
                    max_attempts=settings.MAX_ID_GENERATION_ATTEMPTS,
                    lookup_field='tracking_reference'
                )
        except ValueError:
            raise exceptions.ValidationError("Could not generate a unique acceptance code. Please try again.")
        
        super().save(*args, **kwargs)
    
    def clean(self):
        if not self.amount:
            raise exceptions.ValidationError("Donation amount is required.")
        
        if not isinstance(self.amount, Money):
            raise exceptions.ValidationError("Donation amount must be a Money instance.")
        
        if Decimal(self.amount.amount) <= Decimal('0.00'):
            raise exceptions.ValidationError("Donation amount must be greater than zero.")