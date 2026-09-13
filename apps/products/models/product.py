import typing
import uuid

from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import F
from django.contrib.auth.models import User as DjangoUser
from django.db.models import Sum

from rest_framework import exceptions


from djmoney.money import Money

from apps.payments.mixins import PayableModel
from apps.products.mixins import ProductMixin
from core.utils.display import try_generate_unique_display_code

from colorfield.fields import ColorField

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

class Product(ProductMetaClass): # discounts, resources and availability all apply
    '''
    Product model representing a purchasable item within an event.
    '''
    product_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    display_code = models.CharField(max_length=50, unique=True, blank=True) # human-readable public identifier

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='products'
    )
    max_purchase_quantity_per_order = models.PositiveIntegerField(null=True, blank=True)
    
    categories = models.ManyToManyField(
        'products.ProductCategory',
        through='products.EventProductCategory',
        related_name='category_products',
        blank=True
    )
    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.UniqueConstraint(fields=['title', 'event'], name='unique_product_title_per_event')
        ]

    def clean(self):
        super().clean() 
        if not self.can_publish and self.is_active:
            raise exceptions.ValidationError("Product cannot be published (made active) as it is not verified.")
        
        if self.is_active and not self.verified and self.requires_verification:
            raise exceptions.ValidationError("Unverified products that require verification cannot be published.")
        
        # check unique constraint manually to provide better error message
        existing_products = Product.objects.filter(
            title__iexact=self.title.strip(),
            event=self.event
        )
        if self.pk:
            existing_products = existing_products.exclude(pk=self.pk)

        if existing_products.exists():
            raise exceptions.ValidationError("A product with this title already exists for the event.")

        if self.max_purchase_quantity_per_order is not None and self.max_purchase_quantity_per_order <= 0:
            raise exceptions.ValidationError("Product max purchase quantity per attendee must be at least 1.")
        
        self.title = self.title.strip().title()

    def save(self, *args, **kwargs):
        self.clean()
        if not self.pk: # only generate on creation
            self.original_amount = self.base_amount
            try:
                self.display_code = try_generate_unique_display_code(
                    model_class=Product,
                    length=20,
                    prefix='PROD',
                    args=[self.event.display_code],
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
        return f"<ProductVariant id={self.id} variant_id={self.variant_id} product={self.product.title} size={self.size} color={self.color} stock_quantity={self.stock_quantity} active={self.is_active}>"
    
    @property
    def is_purchasable(self) -> bool:
        return super().is_purchasable and self.product.is_purchasable

    def clean(self):
        super().clean() # call PayableModel clean

        if self.stock_quantity < 0:
            raise exceptions.ValidationError("Stock quantity cannot be negative.")
        if not self.product:
            raise exceptions.ValidationError("ProductVariant must be associated with a Product.")

        if self.max_purchase_quantity_per_order <= 0:
            raise exceptions.ValidationError("Variant max purchase quantity per attendee must be at least 1.")
            
        # check unique constraint manually to provide better error message
        existing_variants = ProductVariant.objects.filter(
            product=self.product,
            size=self.size,
            color=self.color
        )
        if self.pk:
            existing_variants = existing_variants.exclude(pk=self.pk)

        if existing_variants.exists():
            raise exceptions.ValidationError("A ProductVariant with the same product, size, and color already exists.")

        self.color = self.color.upper()
        self.size = self.size.strip().upper()

        self.product.clean()

    def _set_base_amount_from_product(self):
        if not self.product_id:
            raise exceptions.ValidationError("Cannot set base amount: ProductVariant is not associated with a Product.")
        
        self.base_amount = self.product.base_amount
    
    def save(self, *args, **kwargs):
        self._set_base_amount_from_product()
        if not self.pk:
            self.original_amount = self.base_amount
            
        self.size = self.size.strip().upper()
        self.color = self.color.upper()

        self.full_clean()

        super().save(*args, **kwargs)

    @property
    def event(self):
        return self.product.event

    def _log_stock_change(
        self,
        *,
        old_quantity: int,
        new_quantity: int,
        change_amount: int,
        reason: str,
        actor: typing.Optional[DjangoUser] = None,
        order_id: typing.Optional[str] = None,
        payment_id: typing.Optional[str] = None,
        order_item_id: typing.Optional[str] = None,
        webhook_event_id: typing.Optional[str] = None,
        notes: typing.Optional[str] = None,
    ):
        from apps.products.models.audit import StockAuditLog

        StockAuditLog.objects.create(
            product_variant=self,
            old_quantity=old_quantity,
            new_quantity=new_quantity,
            change_amount=change_amount,
            change_reason=reason,
            actor=actor,
            order_id=order_id,
            payment_id=payment_id,
            order_item_id=order_item_id,
            webhook_event_id=webhook_event_id,
            notes=notes,
        )

    def increment_stock(
        self,
        amount: int,
        *,
        reason: str = 'manual_adjustment',
        actor: typing.Optional[DjangoUser] = None,
        order_id: typing.Optional[str] = None,
        payment_id: typing.Optional[str] = None,
        order_item_id: typing.Optional[str] = None,
        webhook_event_id: typing.Optional[str] = None,
        notes: typing.Optional[str] = None,
    ):
        '''
        Atomically increments the stock quantity of the product variant.
        
        Args:
            amount (int): The amount to increment the stock by. Must be positive.
            reason (str): The reason for the stock change.
            actor (User, optional): The user responsible for the change.
            order_id (str, optional): The associated order ID, if applicable.
            payment_id (str, optional): The associated payment ID, if applicable.
            order_item_id (str, optional): The associated order item ID, if applicable.
            webhook_event_id (str, optional): The associated webhook event ID, if applicable.
            notes (str, optional): Additional notes regarding the stock change.
        Raises:
            ValidationError: If the amount is not positive. 
        '''
        if amount <= 0:
            raise exceptions.ValidationError("Increment amount must be positive.")

        current = type(self).objects.filter(pk=self.pk).values('stock_quantity').first()
        if not current:
            raise exceptions.ValidationError("Product variant not found.")

        old_quantity = current['stock_quantity']

        updated = (type(self).objects.filter(pk=self.pk))
        if self.max_stock_quantity is not None: # enforce max stock if set
            updated = updated.filter(
                stock_quantity__lte=F('max_stock_quantity') - amount
            )

        updated = updated.update(
            stock_quantity=F('stock_quantity') + amount
        )
        if updated == 0:
            raise exceptions.ValidationError("Stock increment would exceed maximum capacity.")

        new_quantity = old_quantity + amount
        self._log_stock_change(
            old_quantity=old_quantity,
            new_quantity=new_quantity,
            change_amount=amount,
            reason=reason,
            actor=actor,
            order_id=order_id,
            payment_id=payment_id,
            order_item_id=order_item_id,
            webhook_event_id=webhook_event_id,
            notes=notes,
        )
        self.stock_quantity = new_quantity


    def decrement_stock(
        self,
        amount: int,
        *,
        reason: str = 'manual_adjustment',
        actor: typing.Optional[DjangoUser] = None,
        order_id: typing.Optional[str] = None,
        payment_id: typing.Optional[str] = None,
        order_item_id: typing.Optional[str] = None,
        webhook_event_id: typing.Optional[str] = None,
        notes: typing.Optional[str] = None,
    ):
        '''
        Atomically decrements the stock quantity of the product variant.
        
        Args:
            amount (int): Amount to decrement stock by.
            reason (str): Reason for the stock change.
            actor (User, optional): User who initiated the change.
            order_id (str, optional): Associated order ID.
            payment_id (str, optional): Associated payment ID.
            order_item_id (str, optional): Associated order item ID.
            webhook_event_id (str, optional): Associated webhook event ID.
            notes (str, optional): Additional notes for the stock change.
        Raises:
            ValidationError: If the decrement amount is not positive, if the product variant is not found, or if there is insufficient stock for the decrement.
        '''
        if amount <= 0:
            raise exceptions.ValidationError("Decrement amount must be positive.")

        current = type(self).objects.filter(pk=self.pk).values('stock_quantity').first()
        if not current:
            raise exceptions.ValidationError("Product variant not found.")

        old_quantity = current['stock_quantity']

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

        new_quantity = old_quantity - amount
        self._log_stock_change(
            old_quantity=old_quantity,
            new_quantity=new_quantity,
            change_amount=-amount,
            reason=reason,
            actor=actor,
            order_id=order_id,
            payment_id=payment_id,
            order_item_id=order_item_id,
            webhook_event_id=webhook_event_id,
            notes=notes,
        )
        self.stock_quantity = new_quantity


    def can_decrement_stock(self, amount: int) -> bool:
        """
        Advisory check for stock availability.
        NOT safe for enforcing business rules.

        args:
            amount (int): The amount to check for decrementing stock.
        returns:
            bool: True if the stock can be decremented by the specified amount, False otherwise.
        """
        if amount <= 0:
            return False
        return amount <= self.stock_quantity

    def get_attendee_purchase_quantity(self, attendee): # return the number of this variant the attendee has already purchased
        '''
        Returns the total quantity of this product variant purchased by the given attendee.
        Uses database aggregation for optimal performance.

        Args:
            attendee (Attendee): The attendee for whom to calculate the purchase quantity.
        
        Returns:
            int: The total quantity of this product variant purchased by the attendee.
        '''
        from apps.attendee.models.attendee import Attendee
        from apps.products.models.orders import OrderItem

        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError("The provided attendee is not a valid Attendee instance.")
        
        # Use aggregation to calculate total in a single query (fixes N+1 problem)
        from django.db.models import Sum
        result = OrderItem.objects.filter(
            order__attendee=attendee,
            product_variant=self,
            order__status__in=['draft', 'pending', 'processing', 'completed']  # count open and fulfilled non-cancelled orders
        ).aggregate(total_quantity=Sum('quantity'))
        
        return result['total_quantity'] or 0

    def get_attendee_product_purchase_quantity(self, attendee):
        '''
        Returns the total quantity of all variants of this product purchased by the attendee.

        Args:
            attendee (Attendee): The attendee for whom to calculate the purchase quantity.
        Returns:
            int: The total quantity of all variants of this product purchased by the attendee.
        '''
        from apps.attendee.models.attendee import Attendee
        from apps.products.models.orders import OrderItem

        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError("The provided attendee is not a valid Attendee instance.")

        result = OrderItem.objects.filter(
            order__attendee=attendee,
            product_variant__product=self.product,
            order__status__in=['draft', 'pending', 'processing', 'completed']
        ).aggregate(total_quantity=Sum('quantity'))

        return result['total_quantity'] or 0

    def get_effective_max_purchase_quantity_per_attendee(self) -> int:
        '''
        Effective cap uses the stricter limit when product-level cap is set.
        '''
        product_limit = self.product.max_purchase_quantity_per_order
        variant_limit = self.max_purchase_quantity_per_order
        if product_limit is None:
            return variant_limit
        return min(product_limit, variant_limit)

    def can_attendee_purchase(self, attendee) -> bool:
        '''
        Checks if the given attendee can purchase this product variant.
        Args:
            attendee (Attendee): The attendee to check.
        Returns:
            bool: True if the attendee can purchase, False otherwise.

        1. Product/variant must be active and available.
        2. Attendee must meet any purchase rules.
        3. Attendee's booking must not be cancelled.

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
        if getattr(attendee.booking, 'is_cancelled', False): # 3. attendee's booking is cancelled
            return False
        return True
    
    def can_attendee_purchase_quantity(self, attendee, desired_quantity: int, raise_exception=False) -> bool:
        '''
        Checks if the given attendee can purchase the desired quantity of this product variant.

        Args:
            attendee (Attendee): The attendee to check.
            desired_quantity (int): The desired quantity to purchase.
            raise_exception (bool): If True, raises a ValidationError with details if the purchase is not allowed.
        Returns:
            bool: True if the attendee can purchase the desired quantity, False otherwise.

        1. Product/variant must be active and available.
        2. Attendee must meet any purchase rules.
        3. Desired quantity must not exceed the effective max purchase quantity per attendee.   
        4. Desired quantity must not exceed available stock.
        5. Attendee's booking must not be cancelled.
        6. If raise_exception is True, raises a ValidationError with details if any of the above checks fail.

        '''
        from apps.attendee.models.attendee import Attendee
        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError({"message": "The provided attendee is not a valid Attendee instance.", "code": "invalid_attendee"})
        
        if desired_quantity <= 0:
            return False
        
        effective_limit = self.get_effective_max_purchase_quantity_per_attendee()
        product_purchased = self.get_attendee_product_purchase_quantity(attendee)
        if product_purchased + desired_quantity > effective_limit:
            if raise_exception: 
                raise exceptions.ValidationError({"message": f"Purchase quantity exceeds the maximum allowed per attendee. You have already purchased {product_purchased} of this product.", "code": "purchase_quantity_exceeded"})
            return False
        
        if not self.can_decrement_stock(desired_quantity):
            if raise_exception:
                raise exceptions.ValidationError({"message": "Insufficient stock for the selected product variant.", "code": "insufficient_stock"})
            return False
        
        if attendee.booking.is_cancelled:
            if raise_exception:
                raise exceptions.ValidationError({"message": "Cannot purchase: Attendee's booking is cancelled.", "code": "booking_cancelled"})
            return False
        
        return True

    def get_attendee_final_price(self, attendee) -> 'Money':
        '''
        Calculates the final price for the given attendee after applying any discounts or modifiers.

        Args:
            attendee (Attendee): The Attendee instance for whom to calculate the final price.
        Returns:
            Money: The final price as a Money instance.
        '''
        from apps.attendee.models.attendee import Attendee
        if not isinstance(attendee, Attendee):
            raise exceptions.ValidationError("The provided attendee is not a valid Attendee instance.")
        
        final_price = self.total_amount_for_context(
            context=attendee.pricing_context(),
        )
        return final_price
    