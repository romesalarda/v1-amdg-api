from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from apps.common.models import RequiresVerificationModel
from apps.payments.mixins import DiscountMixin, PayableModel

from djmoney.models.fields import MoneyField

from django.contrib.auth import get_user_model

import uuid

User = get_user_model()

# i.e. stardard registration may come with the event t-shirt and a mug
# 1. standard package: t-shirt + mug (£15) with registration costing £10 and T-shirt costing £10 so £5 discount on package
# 2. standard package standalone: no products (£10)

class PackageProduct(PayableModel): # discounts can be applied to package products # needs to be added to admin
    '''
    Model representing products included in a booking package.
    '''

    base_amount = MoneyField(
        max_digits=10,
        decimal_places=2,
        default_currency='GBP',
        editable=False,
        verbose_name=_("Base Amount")
        ), # takes its value from product price * quantity_per_attendee
    
    booking_package = models.ForeignKey(
        'bookings.BookingPackage',
        on_delete=models.CASCADE,
        related_name='package_products',
        verbose_name=_("Booking Package")
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='booking_packages',
        verbose_name=_("Product")
    )
    quantity_per_attendee = models.PositiveIntegerField(default=1, verbose_name=_("Quantity Per Attendee"))
    added_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Added At"))
    added_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='added_package_products',
        verbose_name=_("Added By")
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))


    class Meta:
        verbose_name = _("Package Product")
        verbose_name_plural = _("Package Products")
        unique_together = ('booking_package', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.booking_package} - {self.product} (x{self.quantity})"
    
    def __repr__(self):
        return f"<PackageProducts(booking_package={self.booking_package}, product={self.product}, quantity={self.quantity})>"
    
    def save(self, *args, **kwargs):
        self.full_clean()
        # base_amount is the product's base price, not multiplied by quantity
        # quantity_per_attendee defines the max purchasable, not a price multiplier
        self.base_amount = self.product.base_amount
        super().save(*args, **kwargs)

    def clean(self):
        if self.quantity_per_attendee < 1:
            raise ValidationError("Quantity per attendee must be at least 1.")
        if self.product_id is None:
            raise ValidationError("Product must be set.")
        
        if self.booking_package_id is None:
            raise ValidationError("Booking package must be set.")
        
        if self.booking_package and self.product and self.booking_package.event_id != self.product.event_id:
            raise ValidationError("Product must belong to the same event as the booking package.")
    
    def total_amount_with_variant(self, variant, context):
        """
        Calculate the total amount for this package product with a specific variant selection.
        
        Pricing calculation order:
        1. Start with variant's modified_amount (product base + variant modifier)
        2. Apply package bundle discount (PackageProduct.percentage_modifier)
        3. Apply discounts from Discount model using context
        
        This respects the tested ProductVariant pricing methods and the generic Discount system.
        
        :param variant: ProductVariant instance selected by the user
        :param context: DiscountContext for evaluating discounts
        :return: Money representing the total amount after all modifiers and discounts
        """
        from djmoney.money import Money
        from decimal import Decimal
        
        if not variant:
            raise ValidationError("Variant must be provided to calculate total.")
        
        if variant.product_id != self.product_id:
            raise ValidationError("Variant must belong to the associated product.")
        
        # Step 1: Get variant's modified_amount (product base + variant modifier, NO discounts)
        # This uses the variant's tested property that applies its percentage_modifier
        variant_modified_price = variant.modified_amount
        
        # Step 2: Apply package bundle discount on top of variant price
        # e.g., £15 variant price * (1 + (-10/100)) = £15 * 0.9 = £13.50
        package_modifier = self.percentage_modifier / Decimal('100')
        bundled_price = variant_modified_price * (Decimal('1') + package_modifier)
        
        # Step 3: Apply discounts from the generic Discount model
        # This uses the tested discount system with rules and context
        discount_amount = self.calculate_total_discounts(
            discount_base=bundled_price,
            context=context
        )
        
        # Calculate final total and ensure non-negative
        final_total = bundled_price - discount_amount
        zero = Money(0, bundled_price.currency)
        result = max(final_total, zero)
        
        # Ensure result has exactly 2 decimal places (required by MoneyField)
        from decimal import Decimal, ROUND_HALF_UP
        rounded_amount = result.amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return Money(rounded_amount, result.currency)
