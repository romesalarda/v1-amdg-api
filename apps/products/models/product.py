from django.db import models
from django.core import validators, exceptions
from django.contrib.auth import get_user_model

from django.db.models import F
from django.db import transaction

from djmoney.money import Money

from datetime import datetime

from django.conf import settings

from apps.payments.mixins import PayableModel
from apps.products.mixins import ProductMixin
from core.utils.display import try_generate_unique_display_code

from colorfield.fields import ColorField
import uuid

User = get_user_model()

class ProductMetaClass(PayableModel, ProductMixin):
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

'''
Staff Process:
1. Admin creates Product with base price, description, etc.
2. Admin can add ProductVariants for different sizes/colors with stock quantities.
3. Products and Variants can be marked verified/unverified.

User process:
1. User browses products within an event.
2. User selects a product 
3. User selects a variant (if applicable) to purchase.
4. User adds product to cart and proceeds to checkout.
5. Upon successful payment, the product is marked as purchased for the user and a payment record is created.
'''

class Product(ProductMetaClass): # discounts, resources and availability all apply #TODO: admin register
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

class ProductVariant(ProductMetaClass): # same as product but different size/color/stock #TODO: admin register
    '''
    ProductVariant model to handle different variants of a product, such as size and color.
    This is what the user actually purchases as opposed to the base Product.
    1. Each ProductVariant is linked to a Product.
    2. Variants can have different stock quantities.
    3. Variants inherit the base price from the Product. (but a percentage modifer can be set)
    4. Variants can be marked active/inactive independently of the Product.
    5. Variants can be created for different sizes and colors.
    6. Stock management methods are provided to increment/decrement stock.
    7. Variants must always have a valid Product associated.

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
    max_stock_quantity = models.PositiveIntegerField(null=True, blank=True) # optional cap on stock
    max_purchase_quantity_per_order = models.PositiveIntegerField(default=5) # cap per order

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

        self.base_amount = self.product.base_amount # MUST match product price, otherwise we would have two base_amounts conflicting
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

    def increment_stock(self, amount: int):
        '''
        Atomically increments the stock quantity of the product variant.
        
        :param self: The ProductVariant instance.
        :param amount: Amount to increment stock by
        :type amount: int
        '''
        if amount <= 0:
            raise exceptions.ValidationError("Increment amount must be positive.")

        updated = (
            type(self).objects
            .filter(
                pk=self.pk,
                stock_quantity__lte=F('max_stock_quantity') - amount
            )
            .update(
                stock_quantity=F('stock_quantity') + amount
            )
        )

        if updated == 0:
            raise exceptions.ValidationError("Stock increment would exceed maximum capacity.")


    def decrement_stock(self, amount: int):
        '''
        Atomically decrements the stock quantity of the product variant.
        
        :param self: The ProductVariant instance.
        :param amount: Amount to decrement stock by
        :type amount: int
        '''
        if amount <= 0:
            raise exceptions.ValidationError("Decrement amount must be positive.")

        updated = (
            type(self).objects
            .filter(
                pk=self.pk,
                stock_quantity__gte=amount
            )
            .update(
                stock_quantity=F('stock_quantity') - amount
            )
        )

        if updated == 0:
            raise exceptions.ValidationError("Insufficient stock for the selected product variant.")


    def can_decrement_stock(self, amount: int) -> bool:
        """
        Advisory check for stock availability.
        NOT safe for enforcing business rules.
        """
        if amount <= 0:
            return False
        return amount <= self.stock_quantity

    def get_attendee_purchase_quantity(self, attendee): # return the number of this variant the attendee has already purchased
        '''
        Returns the total quantity of this product variant purchased by the given attendee.

        @param attendee: The Attendee instance whose purchases to check.
        @return: Total quantity purchased by the attendee.
        '''
        from apps.attendee.models.attendee import Attendee

        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError("The provided attendee is not a valid Attendee instance.")
        
        total_purchased = 0
        orders = attendee.orders.filter(
            order_items__product_variant=self,
            status__in=['processing', 'completed', 'pending'] # only consider non-cancelled orders
        ).distinct()

        for order in orders:
            order_items = order.order_items.filter(product_variant=self)
            for item in order_items:
                total_purchased += item.quantity
        
        return total_purchased

    def can_attendee_purchase(self, attendee) -> bool:
        '''
        Checks if the given attendee can purchase this product variant.
        '''
        from apps.attendee.models.attendee import Attendee
        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError("The provided attendee is not a valid Attendee instance.")
        
        if not self.is_purchasable: # 1. product/variant is not active or available
            return False
        if not self.evaluate_rules( # 2. attendee does not meet any purchase rules
            context=attendee.get_base_context(),
        ):
            return False
        return True
    
    def can_attendee_purchase_quantity(self, attendee, desired_quantity: int, raise_exception=False) -> bool:
        '''
        Checks if the given attendee can purchase the desired quantity of this product variant.

        @param attendee: The Attendee instance attempting the purchase.
        @param desired_quantity: The desired quantity to purchase.
        @return: True if the attendee can purchase the desired quantity, False otherwise.
        '''
        from apps.attendee.models.attendee import Attendee
        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError("The provided attendee is not a valid Attendee instance.")
        
        if desired_quantity <= 0:
            return False
        
        already_purchased = self.get_attendee_purchase_quantity(attendee)
        if already_purchased + desired_quantity > self.max_purchase_quantity_per_order:
            if raise_exception: 
                raise exceptions.ValidationError("Purchase would exceed maximum allowed quantity per attendee for this product variant.")
            return False
        
        if not self.can_decrement_stock(desired_quantity):
            if raise_exception:
                raise exceptions.ValidationError("Insufficient stock for the selected product variant.")
            return False
        
        return True

    def get_attendee_final_price(self, attendee) -> 'Money':
        '''
        Calculates the final price for the given attendee after applying any discounts or modifiers.

        @param attendee: The Attendee instance for whom to calculate the final price.
        @return: The final price as a Money instance.
        '''
        from apps.attendee.models.attendee import Attendee
        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError("The provided attendee is not a valid Attendee instance.")
        
        final_price = self.total_amount_for_context(
            context=attendee.get_base_context(),
        )
        return final_price
    