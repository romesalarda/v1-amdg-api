"""
Tests for high-priority architectural fixes.

This test suite verifies the following critical fixes:
1. Stock restoration on order cancellation/refund
2. Transaction boundaries in add_order_item
3. Order total validation
4. Optimized attendee purchase quantity queries
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction
from datetime import timedelta, date
from djmoney.money import Money

from apps.products.models import (
    Product, ProductVariant, ProductSizeChoices,
    Order, OrderStatusChoices, OrderItem
)
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.bookings.models import Booking

User = get_user_model()


class StockRestorationOnCancellationTest(TestCase):
    """Test that stock is restored when orders are cancelled or refunded"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='stocktest',
            email='stock@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Stock Test Event',
            display_code='STE2025',
            display_identifier='STE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-STOCK-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Stock',
            last_name='Tester',
            user=self.user,
            event=self.event,
            date_of_birth=date(1988, 6, 20),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        self.product = Product.objects.create(
            title='Test Product',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#FF0000',
            stock_quantity=100,
            max_stock_quantity=150,
            added_by=self.user,
            verified=True
        )
        
    def test_stock_restored_on_cancellation(self):
        """Test that stock is restored when order is cancelled"""
        initial_stock = self.variant.stock_quantity
        
        # Create and add items to order
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        
        order.add_order_item(self.variant, 5)
        
        # Verify stock was decremented
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock - 5)
        
        # Cancel order
        order.transition_to(OrderStatusChoices.CANCELLED)
        
        # Verify stock was restored
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock)
        
    def test_stock_restored_on_refund(self):
        """Test that stock is restored when order is refunded"""
        initial_stock = self.variant.stock_quantity
        
        # Create completed order
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        
        order.add_order_item(self.variant, 3)
        order.transition_to(OrderStatusChoices.PENDING) # submitted for processing
        order.transition_to(OrderStatusChoices.PROCESSING) # being verified
        order.transition_to(OrderStatusChoices.COMPLETED) # finalized
        
        # Verify stock was decremented
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock - 3)
        
        # Refund order
        order.transition_to(OrderStatusChoices.REFUNDED)
        
        # Verify stock was restored
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock)
        
    def test_stock_restoration_with_multiple_items(self):
        """Test stock restoration works with multiple order items"""
        product2 = Product.objects.create(
            title='Test Product 2',
            event=self.event,
            base_amount=Money(30, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        variant2 = ProductVariant.objects.create(
            product=product2,
            size=ProductSizeChoices.LARGE,
            color='#0000FF',
            stock_quantity=50,
            added_by=self.user,
            verified=True
        )
        
        initial_stock_1 = self.variant.stock_quantity
        initial_stock_2 = variant2.stock_quantity
        
        # Create order with multiple items
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        
        order.add_order_item(self.variant, 4)
        order.add_order_item(variant2, 2)
        
        # Verify stock decremented
        self.variant.refresh_from_db()
        variant2.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock_1 - 4)
        self.assertEqual(variant2.stock_quantity, initial_stock_2 - 2)
        
        # Cancel order
        order.transition_to(OrderStatusChoices.CANCELLED)
        
        # Verify both stocks restored
        self.variant.refresh_from_db()
        variant2.refresh_from_db()
        
        self.assertEqual(self.variant.stock_quantity, initial_stock_1)
        self.assertEqual(variant2.stock_quantity, initial_stock_2)


class TransactionBoundaryTest(TestCase):
    """Test that order operations maintain transactional integrity"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='transtest',
            email='trans@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Transaction Test Event',
            display_code='TTE2025',
            display_identifier='TTE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TRANS-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Trans',
            last_name='Tester',
            user=self.user,
            event=self.event,
            date_of_birth=date(1991, 9, 10),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        self.product = Product.objects.create(
            title='Transaction Product',
            event=self.event,
            base_amount=Money(50, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#00FF00',
            stock_quantity=20,
            added_by=self.user,
            verified=True
        )
        
    def test_order_total_updated_atomically(self):
        """Test that order total is updated within the same transaction as item creation"""
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        
        # Add item
        order.add_order_item(self.variant, 2)
        
        # Order total should be updated immediately
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Money(100, 'GBP'))
        
        # Order item should exist
        self.assertEqual(order.order_items.count(), 1)
        
        # Stock should be decremented
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 18)


class OrderTotalValidationTest(TestCase):
    """Test that order total validation prevents data inconsistencies"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='validtest',
            email='valid@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Validation Test Event',
            display_code='VTE2025',
            display_identifier='VTE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-VALID-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Valid',
            last_name='Tester',
            user=self.user,
            event=self.event,
            date_of_birth=date(1989, 12, 5),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        self.product = Product.objects.create(
            title='Validation Product',
            event=self.event,
            base_amount=Money(40, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=30,
            added_by=self.user,
            verified=True
        )
        
    def test_order_validation_rejects_mismatched_total(self):
        """Test that validation rejects orders where total doesn't match items"""
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        
        # Add items
        order.add_order_item(self.variant, 2)  # Should be £80
        
        # Manually corrupt the total (simulating price manipulation)
        order.total_amount = Money(50, 'GBP')  # Wrong total
        
        # Validation should fail
        with self.assertRaises(ValidationError) as context:
            order.full_clean()
        
        self.assertIn('does not match calculated total', str(context.exception).lower())
        
    def test_order_validation_accepts_correct_total(self):
        """Test that validation accepts orders with correct totals"""
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        
        # Add items
        order.add_order_item(self.variant, 3)  # £120
        
        # Validation should pass
        order.refresh_from_db()
        order.full_clean()  # Should not raise


class OptimizedQueryTest(TestCase):
    """Test that purchase quantity queries are optimized"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='querytest',
            email='query@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Query Test Event',
            display_code='QTE2025',
            display_identifier='QTE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-QUERY-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Query',
            last_name='Tester',
            user=self.user,
            event=self.event,
            date_of_birth=date(1993, 4, 18),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        self.product = Product.objects.create(
            title='Query Product',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.SMALL,
            color='#FF00FF',
            stock_quantity=100,
            added_by=self.user,
            verified=True,
            max_purchase_quantity_per_order=6 # max purchase limit per attendee per order
        )
        
    def test_get_attendee_purchase_quantity_returns_correct_total(self):
        """Test that purchase quantity calculation returns correct totals"""
        # Create multiple orders
        for i in range(3):
            order = Order.objects.create(
                attendee=self.attendee,
                status=OrderStatusChoices.DRAFT,
                total_amount=Money(0, 'GBP'),
                created_by=self.user,
                customer=self.user
            )
            order.add_order_item(self.variant, 2)
            order.transition_to(OrderStatusChoices.PENDING)
            order.transition_to(OrderStatusChoices.PROCESSING)
            order.transition_to(OrderStatusChoices.COMPLETED)
        
        # Should have purchased 6 total (3 orders x 2 quantity)
        total = self.variant.get_attendee_purchase_quantity(self.attendee)
        self.assertEqual(total, 6)
        
    def test_get_attendee_purchase_quantity_excludes_cancelled(self):
        """Test that cancelled orders are excluded from purchase quantity"""
        # Create completed order
        order1 = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        order1.add_order_item(self.variant, 3)
        order1.transition_to(OrderStatusChoices.PENDING)
        order1.transition_to(OrderStatusChoices.PROCESSING)
        order1.transition_to(OrderStatusChoices.COMPLETED)
        
        # Create cancelled order
        order2 = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        order2.add_order_item(self.variant, 2)
        order2.transition_to(OrderStatusChoices.CANCELLED)
        
        # Should only count completed order (3), not cancelled (2)
        total = self.variant.get_attendee_purchase_quantity(self.attendee)
        self.assertEqual(total, 3)
        
    def test_get_attendee_purchase_quantity_returns_zero_when_none(self):
        """Test that zero is returned when attendee has no purchases"""
        total = self.variant.get_attendee_purchase_quantity(self.attendee)
        self.assertEqual(total, 0)
