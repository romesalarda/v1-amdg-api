from django.db import models
from djmoney.models.fields import MoneyField, Money
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from decimal import Decimal

class DiscountMixin:
    
    @property
    def discounts(self, active=True):
        """
        Returns a queryset of Discount objects associated with this instance.
        Assumes a GenericForeignKey relationship.
        """
        from apps.payments.models.discounts import Discount
        
        content_type = ContentType.objects.get_for_model(self.__class__)
        return Discount.objects.filter(
            target_type=content_type,
            target_id=self.pk,
            active=active
        )
        
    def add_discount(self, discount):
        """
        Associates a Discount object with this instance.
        Assumes a GenericForeignKey relationship.
        """
        discount.target_type = ContentType.objects.get_for_model(self.__class__)
        discount.target_id = self.pk
        discount.clean()
        discount.save(
            update_fields=['target_type', 'target_id']
        )
        return discount
    
    def remove_discount(self, discount):
        """
        Removes the association of a Discount object from this instance.
        Assumes a GenericForeignKey relationship.
        """
        for d in self.discounts.filter(discount_id=discount.discount_id):
            d.delete()
            
class PaymentMixin:
    
    @property
    def payments(self, completed_only=True):
        """
        Returns a queryset of Payment objects associated with this instance.
        Assumes a GenericForeignKey relationship.
        """
        from apps.payments.models.payments import Payment, PaymentStatusChoices
        
        content_type = ContentType.objects.get_for_model(self.__class__)
        qs = Payment.objects.filter(
            target_type=content_type,
            target_id=self.pk,
        )
        if completed_only:
            qs = qs.filter(
                status=PaymentStatusChoices.COMPLETED
            )
        return qs

class PayableModel(models.Model, DiscountMixin, PaymentMixin):
    """
    Mixin for models that represent a payable monetary value.
    """
    base_amount = MoneyField(
        max_digits=14,
        decimal_places=2,
        default_currency='GBP'
    )

    percentage_modifier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Percentage adjustment applied to the base amount (e.g. -10 for 10% discount)."
    )

    class Meta:
        abstract = True

    def clean(self):
        super().clean()

        if self.base_amount.amount < 0:
            raise ValidationError({'base_amount': 'Base amount must be non-negative.'})

        if not Decimal('-100.00') <= self.percentage_modifier <= Decimal('100.00'):
            raise ValidationError({'percentage_modifier': 'Modifier must be between -100 and 100.'})

    @property
    def currency(self):
        return self.base_amount.currency.code

    @property
    def modified_amount(self):
        return self.base_amount * (
            Decimal('1.00') + self.percentage_modifier / Decimal('100')
        )


    def total_amount_for_context(self, context):
        price = self.modified_amount

        discount = self.calculate_total_discounts(
            discount_base=price,
            context=context
        )

        total = price - discount
        zero = Money(0, price.currency)
        return max(total, zero)


    def is_free(self):
        return self.total_amount.amount == 0

    def is_positive(self):
        return self.total_amount.amount > 0

    def __str__(self):
        return f"{self.total_amount} ({self.percentage_modifier}% modifier)"
    
    def __repr__(self):
        return f"<PayableModel base_amount={self.base_amount}, percentage_modifier={self.percentage_modifier}>"
    
    def calculate_total_discounts(self, discount_base, context):
        from apps.payments.models.discounts import DiscountType
        from apps.payments.evaluator import discount_applies
        from djmoney.money import Money
        
        percentage_total = Decimal('0.00')
        fixed_total = Money(0, discount_base.currency)

        for d in self.discounts:
            if not discount_applies(d, context):
                continue

            if d.discount_type == DiscountType.PERCENTAGE:
                percentage_total += d.percentage
            else:
                fixed_total += d.amount

        percentage_discount = discount_base * (percentage_total / Decimal('100'))
        total_discount = percentage_discount + fixed_total

        return min(total_discount, discount_base)
