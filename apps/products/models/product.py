from django.db import models
from django.core import validators, exceptions
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from djmoney.models.fields import MoneyField

from datetime import datetime

from django.conf import settings

from apps.payments.mixins import PayableModel
# from apps.common.mixins import HasResourceMixin, HasAvailabilityMixin
from apps.payments.mixins import PaymentMixin

from apps.common.models.resource import Resource
from core.utils.display import try_generate_unique_display_code

from colorfield.fields import ColorField

import uuid

User = get_user_model()

class ProductMetaClass(PayableModel, PaymentMixin):
    '''
    Abstract base class for Product and ProductVariant to share common fields.
    '''
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='%(class)s_created'
    )

    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_updated'
    )    

    verified = models.BooleanField(default=False) # whether purchase requires verification before being public
    is_active = models.BooleanField(default=True)# whether the product/variant is available for purchase

    class Meta:
        abstract = True

class Product(ProductMetaClass): # discounts, resources and availability all apply
    '''
    Product model representing a purchasable item within an event.
    '''
    product_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='products'
    )
    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.UniqueConstraint(fields=['title', 'event'], name='unique_product_title_per_event')
        ]

    def clean(self):
        if not self.can_publish and self.is_active:
            raise exceptions.ValidationError("Product cannot be published (made active) as it is not verified.")
        
        self.title = self.title.strip().title()

    def save(self, *args, **kwargs):
        self.clean()
        if not self.pk: # only generate on creation
            try:
                self.display_code = try_generate_unique_display_code(
                    model_class=Product,
                    length=20,
                    prefix='PROD',
                    args=[self.event.code],
                    max_attempts=5
                )
            except ValueError:
                raise exceptions.ValidationError("Could not generate a unique display code. Please try again.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Product({self.id}) - {self.title}"
    
    def __repr__(self):
        return f"<Product id={self.id} product_id={self.product_id} title={self.title} verified={self.verified} is_active={self.is_active}>"
    
class ProductSizeChoices(models.TextChoices):

    EXTRA_SMALL = 'XS', 'Extra Small'
    SMALL = 'SM', 'Small'
    MEDIUM = 'MD', 'Medium'
    LARGE = 'LG', 'Large'
    XLARGE = 'XL', 'Extra Large'
    ONE_SIZE = 'OS', 'One Size'
    NOT_APPLICABLE = 'NA', 'Not Applicable'            

class ProductVariant(ProductMetaClass): # same as product but different size/color/stock
    '''
    ProductVariant model to handle different variants of a product, such as size and color.
    '''
    variant_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants'
    ) # the variant inherits the product's price

    size = models.CharField(max_length=2, choices=ProductSizeChoices.choices, default=ProductSizeChoices.NOT_APPLICABLE)
    color = ColorField(default='#FFFFFF')

    stock_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.UniqueConstraint(fields=['product', 'size', 'color'], name='unique_product_variant_per_product_size_color')
        ]

    def __str__(self):
        return f"ProductVariant({self.id}) - {self.product.title} - Size: {self.size} - Color: {self.color}"
    
    def __repr__(self):
        return f"<ProductVariant id={self.id} variant_id={self.variant_id} product={self.product.title} size={self.size} color={self.color} stock_quantity={self.stock_quantity} active={self.active}>"
    
    def clean(self):

        self.base_amount = self.product.base_amount # MUST match product price
        super().clean() # call PayableModel clean

        if self.stock_quantity < 0:
            raise exceptions.ValidationError("Stock quantity cannot be negative.")
        if not self.product:
            raise exceptions.ValidationError("ProductVariant must be associated with a Product.")

        self.color = self.color.upper()
        self.size = self.size.strip().upper()

        self.product.clean()
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def event(self):
        return self.product.event