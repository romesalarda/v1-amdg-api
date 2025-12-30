from django.db import models
from django.core import validators, exceptions
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError

from djmoney.models.fields import MoneyField
from djmoney.money import Money

from django.conf import settings

from core.utils.display import try_generate_unique_display_code
from apps.common.models.verification import RequiresVerificationModel

from .product import ProductVariant

import uuid
from decimal import Decimal

ORDER_STATUS_TRANSITIONS = {
    'draft': ['pending'],
    'pending': ['processing', 'cancelled'],
    'processing': ['completed', 'refunded'],
    'completed': ['refunded'],
    'cancelled': [],
    'refunded': [],
}
class OrderStatusChoices(models.TextChoices):
    DRAFT = 'draft', 'Draft' # initial state, not yet confirmed basically a cart
    PENDING = 'pending', 'Pending' # awaiting processing, has been submitted by user
    PROCESSING = 'processing', 'Processing' # being processed (payment being confirmed, items being prepared)
    COMPLETED = 'completed', 'Completed' # successfully completed
    CANCELLED = 'cancelled', 'Cancelled' # cancelled by user or admin
    PENDING_REFUND = 'pending_refund', 'Pending Refund' # refund requested, awaiting processing
    REFUNDED = 'refunded', 'Refunded' # refunded to user

# 1. User adds products to order (cart) -> Order in 'draft' status
# 2. User submits order -> Order status changes to 'pending'
# 3. Admin processes order -> Order status changes to 'processing'
#  4. Once fulfilled, order status changes to 'completed'
#  If cancelled at any point before completion, status changes to 'cancelled'

class Order(RequiresVerificationModel): # orders may require verification before processing
    '''
    Order model to handle customer orders for products.
    '''
    order_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) # Public identifier
    order_reference_id = models.CharField(max_length=25, unique=True) # e.g., human readable order number

    customer = models.ForeignKey( # verified user who made the order
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders'
    )
    attendee = models.ForeignKey( # user attached to the order
        'attendee.Attendee',
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders'
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatusChoices.choices,
        default=OrderStatusChoices.DRAFT
    )

    total_amount = MoneyField(max_digits=10, decimal_places=2, default_currency='GBP') # db only, computed at order creation

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders_created'
    ) # relation in case an admin creates an order on behalf of a user

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders_updated'
    )
    payment = models.ForeignKey(
        'payments.Payment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders'
    ) # payment associated with the order, if any, fast lookup  

    def save(self, *args, **kwargs):
        self.clean()
        if not self.order_reference_id:
            try:
                self.order_reference_id = try_generate_unique_display_code(
                    model_class=Order,
                    length=25,
                    prefix='ORD',
                    args=[self.event.display_code],
                    lookup_field='order_reference_id',
                    max_attempts=settings.MAX_ID_GENERATION_ATTEMPTS
                )
            except ValueError:
                raise exceptions.ValidationError("Could not generate a unique order reference ID. Please try again.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order({self.id}) - {self.status}"
    
    def __repr__(self):
        return f"<Order id={self.id} order_id={self.order_id} total_amount={self.total_amount} status={self.status}>"
    
    def clean(self):
        if self.total_amount.amount < 0:
            raise exceptions.ValidationError("Total amount cannot be negative.")
        
        if not self.attendee and not self.customer:
            raise exceptions.ValidationError("Order must be associated with either a customer or an attendee.")
        
        # Validate that stored total matches calculated total (prevents price manipulation)
        if self.pk:  # Only validate if order exists (has items)
            calculated_total = self.get_total_amount()
            if self.total_amount != calculated_total:
                raise exceptions.ValidationError(
                    f"Order total amount ({self.total_amount}) does not match calculated total ({calculated_total}). "
                    "Please recalculate the order total."
                )
        
    @property
    def event(self):
        '''
        Returns the event associated with the order via the attendee.
        '''
        if self.attendee:
            return self.attendee.event
        return None
    
    @property
    def can_add_products(self) -> bool:
        if self.status != OrderStatusChoices.PENDING:
            return False
        return True

    # validate transitions
    def can_transition_to(self, new_status: str) -> bool:
        '''
        Checks if the order can transition to the specified new status.

        @param new_status: The target status to transition to.
        @return: True if the transition is valid, False otherwise.
        '''
        allowed_transitions = ORDER_STATUS_TRANSITIONS.get(self.status, [])
        return new_status in allowed_transitions
    
    def transition_to(self, new_status: str):
        '''
        Transitions the order to the specified new status if valid.
        Restores stock if transitioning to cancelled or refunded status.

        @param new_status: The target status to transition to.
        Raises ValidationError if the transition is not allowed.
        '''
        if not self.can_transition_to(new_status):
            raise exceptions.ValidationError(f"Cannot transition from {self.status} to {new_status}.")
        
        old_status = self.status
        self.status = new_status
        
        # Restore stock when cancelling or refunding an order
        if new_status in [OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED]:
            for item in self.order_items.all():
                if item.product_variant:
                    try:
                        item.product_variant.increment_stock(item.quantity)
                    except exceptions.ValidationError:
                        # If stock restoration fails (e.g., would exceed max), log but don't block cancellation
                        pass
        
        self.save()

    def get_total_amount(self) -> Money:
        '''
        Calculates the total amount of the order by summing up the total prices of all order items.

        @return: The total amount as a Money instance.
        '''
        total = Money(0, 'GBP')
        for item in self.order_items.all():
            total += item.total_price
        return total
    
    def recalculate_total_amount(self):
        '''
        Recalculates and updates the total amount of the order based on its order items.
        '''
        self.total_amount = self.get_total_amount()
        self.save()

    def add_order_item(self, product_variant: 'ProductVariant', quantity: int) -> 'OrderItem':
        '''
        Adds an OrderItem to the order.

        @param product_variant: The ProductVariant instance to add to the order.
        @param quantity: The quantity of the product variant to add.
        Returns the created OrderItem instance.
        '''
        from apps.products.models.product import ProductVariant
        from apps.attendee.models.attendee import Attendee
        self.attendee: Attendee  # type: ignore

        if not isinstance(product_variant, ProductVariant):
            raise exceptions.ValidationError("The provided product_variant is not a valid ProductVariant instance.")
        if quantity <= 0:
            raise exceptions.ValidationError("Quantity must be at least 1.")
        
        if not self.can_add_products:
            raise exceptions.ValidationError("Cannot add products to an order that is not in 'pending' status.")
        

        with transaction.atomic():
            # 1. check if attendee can purchase the product variant (permissions)
            # 2. check if enough stock is available for attendee (quantity)
            # 3. calculate unit price for attendee (with discounts applied)
            # 4. create order item (with total price)
            # 5. decrement stock (product variant)
            # 6. update order total amount (order)
            # 7. save all changes

            if not product_variant.can_attendee_purchase(self.attendee):
                raise exceptions.ValidationError("The attendee is not eligible to purchase the selected product variant.")
            
            product_variant.can_attendee_purchase_quantity(self.attendee, quantity, raise_exception=True) # raises if not enough stock
            
            unit_price: Decimal = product_variant.get_attendee_final_price(
                context=self.attendee.get_base_context() if self.attendee else {}
            ).amount # with discounts applied
            total_price = (unit_price * Decimal(quantity)).quantize(Decimal("0.01"))

            order_item = OrderItem(
                order=self,
                product_variant=product_variant,
                quantity=quantity,
                unit_price=unit_price,
                total_price=total_price
            )
            order_item.clean()
            order_item.save()

            product_variant.decrement_stock(quantity) # adjust stock

            # Recalculate and save order total within transaction for consistency
            self.total_amount = self.get_total_amount()
            self.full_clean()
            self.save() # persist changes

        return order_item

class OrderItem(models.Model):
    '''
    OrderItem model to represent individual items within an order.
    '''
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='order_items'
    )
    product_variant = models.ForeignKey(
        'products.ProductVariant',
        on_delete=models.SET_NULL,
        null=True,
        related_name='order_items'
    )

    quantity = models.PositiveIntegerField(validators=[validators.MinValueValidator(1)])
    unit_price = MoneyField(max_digits=10, decimal_places=2, default_currency='GBP') # price per unit at time of order
    total_price = MoneyField(max_digits=10, decimal_places=2, default_currency='GBP') # unit_price * quantity

    def __str__(self):
        return f"OrderItem({self.id}) - {self.product_variant} x {self.quantity}"
    
    def __repr__(self):
        return f"<OrderItem id={self.id} order_id={self.order.id} product_variant={self.product_variant} quantity={self.quantity} total_price={self.total_price}>"
    
    def clean(self):
        if self.quantity <= 0:
            raise exceptions.ValidationError("Quantity must be at least 1.")
        if self.unit_price.amount < 0:
            raise exceptions.ValidationError("Unit price cannot be negative.")
        if self.total_price.amount != self.unit_price.amount * self.quantity:
            raise exceptions.ValidationError("Total price must equal unit price multiplied by quantity.")
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    