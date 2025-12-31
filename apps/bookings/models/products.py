from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from apps.common.models import RequiresVerificationModel
from apps.payments.mixins import DiscountMixin

import uuid

# i.e. stardard registration may come with the event t-shirt and a mug
# 1. standard package: t-shirt + mug (£15) with registration costing £10 and T-shirt costing £10 so £5 discount on package
# 2. standard package standalone: no products (£10)

class PackageProduct(RequiresVerificationModel, DiscountMixin): # discounts can be applied to package products
    '''
    Model representing products included in a booking package.
    '''

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
        'auth.User',
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
        
