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
    def payments(self):
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
        # if completed_only:
        #     qs = qs.filter(
        #         status=PaymentStatusChoices.COMPLETED
        #     )
        return qs
    
    @property
    def payment(self):
        """
        Returns the first associated Payment object, or None if none exist.
        Assumes a GenericForeignKey relationship.
        """
        payments = self.payments.filter()
        if payments.count() > 1:
            # Log a warning if multiple payments exist
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Multiple payments found for {self.__class__.__name__} id={self.pk}. Returning the first one."
            )
        return payments.first() if payments.exists() else None


    def add_payment(self, payment):
        """
        Associates a Payment object with this instance.
        Assumes a GenericForeignKey relationship.
        """
        payment.target_type = ContentType.objects.get_for_model(self.__class__)
        payment.target_id = self.pk
        payment.full_clean()
        payment.save(
            update_fields=['target_type', 'target_id']
        )
        return payment
        
    def remove_payment(self, payment):
        """
        Removes the association of a Payment object from this instance.
        Assumes a GenericForeignKey relationship.
        """
        for p in self.payments.filter(payment_id=payment.payment_id):
            p.delete()

class PayableModel(models.Model, DiscountMixin, PaymentMixin):
    """
    Abstract model mixin that provides payable functionality with base amount,
    percentage modifier, and discount calculations.

    Assumes a GenericForeignKey relationship for discounts.
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
        help_text="Percentage adjustment applied to the base amount (1.1 for +1%, -2.5 for -2.5%)"
    ) # products for a specific object variant (e.g., size/color) may have different prices.

    class Meta:
        abstract = True

    def clean(self, *args, **kwargs):
        if not kwargs.get('skip_base_amount_check', False):
            if self.base_amount is None:
                raise ValidationError('Base amount must be set.')
        
            if self.base_amount.amount < 0:
                raise ValidationError('Base amount must be non-negative.')

        if not Decimal('-100.00') <= self.percentage_modifier <= Decimal('100.00'):
            raise ValidationError('Modifier must be between -100 and 100.')

    @property
    def currency(self):
        return self.base_amount.currency.code

    @property
    def modified_amount(self):
        '''
        Calculate the modified amount after applying the percentage modifier to the base amount.
        
        :param self: Instance of PayableModel
        :return: Money representing the modified amount
        '''
        if not self.base_amount or self.percentage_modifier == 0:
            return self.base_amount
        
        return self.base_amount * (
            Decimal('1.00') + self.percentage_modifier / Decimal('100')
        )


    def total_amount_for_context(self, context) -> Money:
        '''
        Calculate the total amount payable after applying discounts based on the provided context.
        
        :param self: Instance of PayableModel
        :param context: ContextObject providing context for discount evaluation
        '''
        price = self.modified_amount

        discount = self.calculate_total_discounts(
            discount_base=price,
            context=context
        )

        total = price - discount
        zero = Money(0, price.currency)
        return max(total, zero)

    @property
    def is_free(self):
        '''
        Returns True if the base amount is zero. 
        Note: This does not consider discounts or context.
        '''
        return self.base_amount.amount == 0

    @property
    def is_positive(self):
        '''
        Returns True if the base amount is greater than zero.
        Note: This does not consider discounts or context.
        '''
        return self.base_amount.amount > 0
    
    def is_free_with_context(self, context):
        total = self.total_amount_for_context(context)
        return total.amount == 0
    
    def is_positive_with_context(self, context):
        total = self.total_amount_for_context(context)
        return total.amount > 0

    def __str__(self):
        return f"{self.total_amount} ({self.percentage_modifier}% modifier)"
    
    def __repr__(self):
        return f"<PayableModel base_amount={self.base_amount}, percentage_modifier={self.percentage_modifier}>"
    
    def calculate_total_discounts(self, discount_base, context) -> Money:
        '''
        Calculate the total discounts applicable to this payable model based on the provided context.
        Returns the minimum of the total discounts and the discount base to avoid negative totals.
        
        :param self: Instance of PayableModel
        :param discount_base: Money representing the amount before discounts
        :param context: ContextObject providing context for discount evaluation
        :return: Money representing total discounts applied
        '''
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
