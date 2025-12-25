from django.db import models
from djmoney.models.fields import MoneyField
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from django.contrib.auth import get_user_model

from django.core.exceptions import ValidationError
from decimal import Decimal

import uuid

User = get_user_model()

class DiscountApplicationChoices(models.TextChoices):
    
    REGISTRATION = 'REGISTRATION', 'Registration'
    PRODUCTS = 'PRODUCTS', 'Products'
    WORKSHOPS = 'WORKSHOPS', 'Workshops'
    
class DiscountType(models.TextChoices):
    PERCENTAGE = 'PERCENTAGE', 'Percentage'
    FIXED = 'FIXED', 'Fixed amount'

class Discount(models.Model):
    
    discount_id = models.UUIDField(editable=False, default=uuid.uuid4)
    discount_type = models.CharField(
        max_length=30,
        choices=DiscountApplicationChoices.choices,
        default=DiscountApplicationChoices.REGISTRATION
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Percentage discount to apply (e.g. 10 for 10% off)."
    )
    amount = MoneyField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default_currency='GBP',
        help_text="Fixed amount discount to apply."
    )
    
    discount_type = models.CharField(
        max_length=30,
        choices=DiscountType.choices,
        default=DiscountType.FIXED
    )
    
    target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_id = models.PositiveIntegerField()
    target = GenericForeignKey('target_type', 'target_id')
    
    active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['discount_id']),
            models.Index(fields=['target_type', 'target_id']),
        ]
        ordering = ['-created_at']
    
    def clean(self):
        super().clean()

        if self.discount_type == DiscountType.PERCENTAGE and self.percentage is None:
            raise ValidationError("Percentage discount requires percentage value.")

        if self.discount_type == DiscountType.FIXED and self.amount is None:
            raise ValidationError("Fixed discount requires amount.")

        if self.discount_type == DiscountType.PERCENTAGE and self.amount:
            raise ValidationError("Percentage discount must not define amount.")

        if self.discount_type == DiscountType.FIXED and self.percentage:
            raise ValidationError("Fixed discount must not define percentage.")

    def __str__(self):
        if self.discount_type == DiscountType.PERCENTAGE:
            return f"{self.percentage}% off"
        else:
            return f"{self.amount} off"
        
    def __repr__(self):
        return f"<Discount {self.discount_id} ({self.discount_type})>"
    
    @property
    def absolute_value(self):
        """
        Returns the absolute value of the discount. (e.g. 0.10 for 10% or Money amount for fixed)
        """
        if self.discount_type == DiscountType.PERCENTAGE:
            return self.percentage / Decimal('100.00')
        else:
            return self.amount
        
    @property
    def display_value(self):
        """
        Returns a human-readable representation of the discount.
        """
        if self.discount_type == DiscountType.PERCENTAGE:
            return f"{self.percentage}%"
        else:
            return str(self.amount)
        
class DiscountRuleTypeChoices(models.TextChoices):
    
    IS_EVENT_STAFF = 'IS_EVENT_STAFF', _('Is Event Staff') # for staff discounts
    IS_AGE_LT = 'IS_AGE_LT', _('Is Age Less Than') # for age based discounts
    IS_AGE_GT = 'IS_AGE_GT', _('Is Age Greater Than') # for age based discounts
    ORGANISATION_MATCHES = 'ORGANISATION_MATCHES', _('Organisation Matches') # for organisation based discounts
    VALUE_MATCHES = 'VALUE_MATCHES', _('Value Matches') # for discount codes etc.
    EVENT_STAFF_ROLE_MATCHES = 'EVENT_STAFF_ROLE_MATCHES', _('Event Staff Role Matches') # for specific staff role discounts
    NAME_MATCHES = 'NAME_MATCHES', _('Name Matches') # for name based discounts
    LOCATION_MATCHES = 'LOCATION_MATCHES', _('Location Matches') # for location based discounts
        
class DiscountRule(models.Model):
    '''
    Model representing rules for applying discounts.
    '''
    rule_id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    rule_type = models.CharField(
        max_length=30,
        choices=DiscountRuleTypeChoices.choices,
        default=DiscountRuleTypeChoices.IS_EVENT_STAFF
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    discount = models.ForeignKey(Discount, on_delete=models.CASCADE, related_name='rules')
    value = models.CharField(max_length=255, help_text="Value associated with the rule (e.g. age limit, organisation name, etc.)", blank=True, null=True)
    
    active = models.BooleanField(default=True)
    
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        if self.rule_type in [
            DiscountRuleTypeChoices.IS_AGE_LT,
            DiscountRuleTypeChoices.IS_AGE_GT,
            DiscountRuleTypeChoices.ORGANISATION_MATCHES,
            DiscountRuleTypeChoices.VALUE_MATCHES,
            DiscountRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES,
            DiscountRuleTypeChoices.NAME_MATCHES,
            DiscountRuleTypeChoices.LOCATION_MATCHES,
        ] and not self.value:
            raise ValidationError(f"Rule type {self.rule_type} requires a value.")
        
        if self.rule_type in [
            DiscountRuleTypeChoices.IS_AGE_GT, 
            DiscountRuleTypeChoices.IS_AGE_LT
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