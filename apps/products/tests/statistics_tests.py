"""
Product Statistics Tests

Comprehensive test suite for product statistics functionality testing:
- Core statistics calculation functions
- API endpoints with raw and ECharts formats
- Event and organization filtering capabilities
- Soft-delete handling
- Revenue calculations with status-specific logic
- Edge cases and data accuracy
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q, Sum
from rest_framework.test import APIClient
from rest_framework import status as http_status
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money

from apps.products.models.product import Product, ProductVariant, ProductSizeChoices
from apps.products.models.orders import Order, OrderItem, OrderStatusChoices
from apps.products.models.category import ProductCategory, EventProductCategory
from apps.products import statistics
from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.bookings.models import BookingPackage, PackageProduct
from apps.bookings.models.ticket import TicketType

User = get_user_model()


class ProductStatisticsBaseTestCase(TestCase):
    """Base test case with comprehensive setup for product statistics tests."""
    
    def setUp(self):
        """Set up comprehensive test data for statistics testing."""
        self.client = APIClient()
        
        # ==================== STEP 1: Create Users ====================
        self.regular_user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.admin_user = User.objects.create_user(
            username='adminuser',
            email='admin@example.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        # ==================== STEP 2: Create Organizations ====================
        self.org1 = Organisation.objects.create(
            title='Test Organisation 1',
            description='First test organization',
            created_by=self.admin_user
        )
        
        self.org2 = Organisation.objects.create(
            title='Test Organisation 2',
            description='Second test organization',
            created_by=self.admin_user
        )
        
        # ==================== STEP 3: Create EventType ====================
        self.event_type = EventType.objects.create(
            title='Workshop',
            code='WORK',
            created_by=self.admin_user
        )
        
        # ==================== STEP 4: Create Events ====================
        now = timezone.now()
        
        self.event1 = Event.objects.create(
            title='Workshop 2026',
            display_code='WORK2026',
            display_identifier='WORK2026TEST1',
            created_by=self.admin_user,
            event_type=self.event_type,
            start_datetime=now + timedelta(days=30),
            end_datetime=now + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.org1
        )
        
        self.event2 = Event.objects.create(
            title='Conference 2026',
            display_code='CONF2026',
            display_identifier='CONF2026TEST2',
            created_by=self.admin_user,
            event_type=self.event_type,
            start_datetime=now + timedelta(days=60),
            end_datetime=now + timedelta(days=62),
            status=EventStatusChoices.COMPLETED,
            organisation=self.org1
        )
        
        self.event3 = Event.objects.create(
            title='Summit 2026',
            display_code='SUMM2026',
            display_identifier='SUMM2026TEST3',
            created_by=self.admin_user,
            event_type=self.event_type,
            start_datetime=now + timedelta(days=90),
            end_datetime=now + timedelta(days=92),
            status=EventStatusChoices.OPEN,
            organisation=self.org2
        )
        
        # ==================== STEP 5: Create Product Categories ====================
        self.category_apparel = ProductCategory.objects.create(
            name='Apparel',
            description='Clothing and wearables'
        )
        
        self.category_food = ProductCategory.objects.create(
            name='Food',
            description='Food and beverages'
        )
        
        self.category_merchandise = ProductCategory.objects.create(
            name='Merchandise',
            description='General merchandise'
        )
        
        # ==================== STEP 6: Create EventProductCategories ====================
        # Link categories to events (initially without products)
        self.event1_cat_apparel = EventProductCategory.objects.create(
            event=self.event1,
            category=self.category_apparel,
            product=None
        )
        
        self.event1_cat_food = EventProductCategory.objects.create(
            event=self.event1,
            category=self.category_food,
            product=None
        )
        
        self.event1_cat_merchandise = EventProductCategory.objects.create(
            event=self.event1,
            category=self.category_merchandise,
            product=None
        )
        
        self.event2_cat_apparel = EventProductCategory.objects.create(
            event=self.event2,
            category=self.category_apparel,
            product=None
        )
        
        self.event2_cat_food = EventProductCategory.objects.create(
            event=self.event2,
            category=self.category_food,
            product=None
        )
        
        # ==================== STEP 7: Create Products with Variants ====================
        # Event1 Products (6 products)
        self.event1_products = []
        self.event1_variants = []
        
        # Product 1: T-Shirt (active, verified) - Apparel
        product1, variants1 = self._create_product_with_variants(
            title='Event T-Shirt',
            event=self.event1,
            category=self.category_apparel,
            base_amount=Money(25, 'GBP'),
            is_active=True,
            verified=True,
            created_days_ago=50,
            variants_config=[
                {'size': 'SM', 'color': '#FF0000', 'stock': 20},
                {'size': 'MD', 'color': '#FF0000', 'stock': 30},
                {'size': 'LG', 'color': '#0000FF', 'stock': 15},
                {'size': 'XL', 'color': '#0000FF', 'stock': 5},
            ]
        )
        self.event1_products.append(product1)
        self.event1_variants.extend(variants1)
        
        # Product 2: Hoodie (active, verified) - Apparel
        product2, variants2 = self._create_product_with_variants(
            title='Event Hoodie',
            event=self.event1,
            category=self.category_apparel,
            base_amount=Money(45, 'GBP'),
            is_active=True,
            verified=True,
            created_days_ago=45,
            variants_config=[
                {'size': 'MD', 'color': '#00FF00', 'stock': 10},
                {'size': 'LG', 'color': '#00FF00', 'stock': 8},
                {'size': 'XS', 'color': '#000000', 'stock': 0},  # Out of stock
            ]
        )
        self.event1_products.append(product2)
        self.event1_variants.extend(variants2)
        
        # Product 3: Water Bottle (active, verified) - Merchandise
        product3, variants3 = self._create_product_with_variants(
            title='Reusable Water Bottle',
            event=self.event1,
            category=self.category_merchandise,
            base_amount=Money(15, 'GBP'),
            is_active=True,
            verified=True,
            created_days_ago=40,
            variants_config=[
                {'size': 'OS', 'color': '#FFFFFF', 'stock': 50},
                {'size': 'OS', 'color': '#0000FF', 'stock': 60},
            ]
        )
        self.event1_products.append(product3)
        self.event1_variants.extend(variants3)
        
        # Product 4: Lunch Package (active, verified) - Food
        product4, variants4 = self._create_product_with_variants(
            title='Lunch Package',
            event=self.event1,
            category=self.category_food,
            base_amount=Money(12, 'GBP'),
            is_active=True,
            verified=True,
            created_days_ago=35,
            variants_config=[
                {'size': 'NA', 'color': '#FFFF00', 'stock': 100},
            ]
        )
        self.event1_products.append(product4)
        self.event1_variants.extend(variants4)
        
        # Product 5: Notebook (inactive, verified) - Merchandise
        product5, variants5 = self._create_product_with_variants(
            title='Event Notebook',
            event=self.event1,
            category=self.category_merchandise,
            base_amount=Money(8, 'GBP'),
            is_active=False,
            verified=True,
            created_days_ago=30,
            variants_config=[
                {'size': 'NA', 'color': '#FF00FF', 'stock': 25},
            ]
        )
        self.event1_products.append(product5)
        self.event1_variants.extend(variants5)
        
        # Product 6: Cap (active, unverified) - Apparel
        product6, variants6 = self._create_product_with_variants(
            title='Event Cap',
            event=self.event1,
            category=self.category_apparel,
            base_amount=Money(18, 'GBP'),
            is_active=True,
            verified=False,
            created_days_ago=25,
            variants_config=[
                {'size': 'OS', 'color': '#000000', 'stock': 40},
                {'size': 'OS', 'color': '#FFFFFF', 'stock': 1},  # Low stock
            ]
        )
        self.event1_products.append(product6)
        self.event1_variants.extend(variants6)
        
        # Event2 Products (4 products)
        self.event2_products = []
        self.event2_variants = []
        
        # Product 7: Conference T-Shirt (active, verified) - Apparel
        product7, variants7 = self._create_product_with_variants(
            title='Conference T-Shirt',
            event=self.event2,
            category=self.category_apparel,
            base_amount=Money(28, 'GBP'),
            is_active=True,
            verified=True,
            created_days_ago=20,
            variants_config=[
                {'size': 'SM', 'color': '#FF0000', 'stock': 150},
                {'size': 'MD', 'color': '#FF0000', 'stock': 200},
                {'size': 'LG', 'color': '#FF0000', 'stock': 120},
            ]
        )
        self.event2_products.append(product7)
        self.event2_variants.extend(variants7)
        
        # Product 8: Coffee Mug (active, verified) - Merchandise
        product8, variants8 = self._create_product_with_variants(
            title='Coffee Mug',
            event=self.event2,
            category=self.category_merchandise,
            base_amount=Money(10, 'GBP'),
            is_active=True,
            verified=True,
            created_days_ago=18,
            variants_config=[
                {'size': 'NA', 'color': '#FFFFFF', 'stock': 80},
                {'size': 'NA', 'color': '#000000', 'stock': 3},  # Low stock
            ]
        )
        self.event2_products.append(product8)
        self.event2_variants.extend(variants8)
        
        # Product 9: Snack Box (inactive, verified) - Food
        product9, variants9 = self._create_product_with_variants(
            title='Snack Box',
            event=self.event2,
            category=self.category_food,
            base_amount=Money(6, 'GBP'),
            is_active=False,
            verified=True,
            created_days_ago=15,
            variants_config=[
                {'size': 'NA', 'color': '#FFFF00', 'stock': 0},  # Out of stock
            ]
        )
        self.event2_products.append(product9)
        self.event2_variants.extend(variants9)
        
        # Product 10: Backpack (active, unverified) - Merchandise
        product10, variants10 = self._create_product_with_variants(
            title='Event Backpack',
            event=self.event2,
            category=self.category_merchandise,
            base_amount=Money(35, 'GBP'),
            is_active=True,
            verified=False,
            created_days_ago=10,
            variants_config=[
                {'size': 'OS', 'color': '#000000', 'stock': 5},  # Low stock
            ]
        )
        self.event2_products.append(product10)
        self.event2_variants.extend(variants10)
        
        # Event3 Products (2 products)
        self.event3_products = []
        self.event3_variants = []
        
        # Product 11: Summit Polo (active, verified)
        product11, variants11 = self._create_product_with_variants(
            title='Summit Polo Shirt',
            event=self.event3,
            category=self.category_apparel,
            base_amount=Money(32, 'GBP'),
            is_active=True,
            verified=True,
            created_days_ago=5,
            variants_config=[
                {'size': 'MD', 'color': '#0000FF', 'stock': 30},
            ]
        )
        self.event3_products.append(product11)
        self.event3_variants.extend(variants11)
        
        # Product 12: Summit Bag (inactive, unverified)
        product12, variants12 = self._create_product_with_variants(
            title='Summit Tote Bag',
            event=self.event3,
            category=self.category_merchandise,
            base_amount=Money(20, 'GBP'),
            is_active=False,
            verified=False,
            created_days_ago=3,
            variants_config=[
                {'size': 'NA', 'color': '#00FF00', 'stock': 10},
            ]
        )
        self.event3_products.append(product12)
        self.event3_variants.extend(variants12)
        
        # ==================== STEP 9: Create Attendees ====================
        self.attendees = []
        
        for i in range(5):
            attendee = Attendee.objects.create(
                first_name=f'Attendee{i+1}',
                last_name=f'Test{i+1}',
                email=f'attendee{i+1}@example.com',
                event=self.event1,
                date_of_birth=date(1990 + i, 1, 1),
                gender='MALE' if i % 2 == 0 else 'FEMALE',
                relationship_to_user=AttendeeRelationship.SELF if i == 0 else AttendeeRelationship.FRIEND,
                defined_by=self.regular_user,
                user=self.regular_user if i == 0 else None
            )
            self.attendees.append(attendee)
        
        # ==================== STEP 10: Create Booking Packages ====================
        # Create ticket type first (required for BookingPackage)
        self.ticket_type1 = TicketType.objects.create(
            event=self.event1,
            title='Standard',
            code='STD',
            created_by=self.admin_user
        )
        
        self.ticket_type2 = TicketType.objects.create(
            event=self.event2,
            title='VIP',
            code='VIP',
            created_by=self.admin_user
        )
        
        self.package1 = BookingPackage.objects.create(
            name='Standard Package',
            event=self.event1,
            ticket_type=self.ticket_type1,
            base_amount=Money(150, 'GBP'),
            created_by=self.admin_user
        )
        
        self.package2 = BookingPackage.objects.create(
            name='Premium Package',
            event=self.event2,
            ticket_type=self.ticket_type2,
            base_amount=Money(250, 'GBP'),
            created_by=self.admin_user
        )
        
        # ==================== STEP 11: Create PackageProducts ====================
        # Link some products to packages
        self.package_product1 = PackageProduct.objects.create(
            booking_package=self.package1,
            product=self.event1_products[0],  # T-Shirt
            quantity_per_attendee=1,
            added_by=self.admin_user
        )
        
        self.package_product2 = PackageProduct.objects.create(
            booking_package=self.package1,
            product=self.event1_products[2],  # Water Bottle
            quantity_per_attendee=1,
            added_by=self.admin_user
        )
        
        self.package_product3 = PackageProduct.objects.create(
            booking_package=self.package2,
            product=self.event2_products[0],  # Conference T-Shirt
            quantity_per_attendee=2,
            added_by=self.admin_user
        )
        
        # ==================== STEP 12: Create Orders ====================
        self.orders = []
        
        # Completed orders (6 orders) - These count for revenue
        self._create_order_with_items(
            customer=self.regular_user,
            status=OrderStatusChoices.COMPLETED,
            total_amount=50.00,
            created_days_ago=45,
            items_config=[
                {'variant': self.event1_variants[0], 'quantity': 2, 'unit_price': 25.00},
            ]
        )
        
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[0],
            status=OrderStatusChoices.COMPLETED,
            total_amount=90.00,
            created_days_ago=40,
            items_config=[
                {'variant': self.event1_variants[1], 'quantity': 2, 'unit_price': 25.00},
                {'variant': self.event1_variants[4], 'quantity': 1, 'unit_price': 40.00},
            ]
        )
        
        self._create_order_with_items(
            attendee=self.attendees[0],
            status=OrderStatusChoices.COMPLETED,
            total_amount=30.00,
            created_days_ago=35,
            items_config=[
                {'variant': self.event1_variants[7], 'quantity': 2, 'unit_price': 15.00},
            ]
        )
        
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[1],
            status=OrderStatusChoices.COMPLETED,
            total_amount=100.00,
            created_days_ago=30,
            items_config=[
                {'variant': self.event2_variants[0], 'quantity': 2, 'unit_price': 28.00},
                {'variant': self.event2_variants[3], 'quantity': 1, 'unit_price': 10.00},
                {'variant': self.event2_variants[4], 'quantity': 3, 'unit_price': 10.00},
            ]
        )
        
        self._create_order_with_items(
            attendee=self.attendees[1],
            status=OrderStatusChoices.COMPLETED,
            total_amount=56.00,
            created_days_ago=25,
            items_config=[
                {'variant': self.event2_variants[1], 'quantity': 2, 'unit_price': 28.00},
            ]
        )
        
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[2],
            status=OrderStatusChoices.COMPLETED,
            total_amount=150.00,
            created_days_ago=20,
            items_config=[
                {'variant': self.event1_variants[0], 'quantity': 3, 'unit_price': 25.00},
                {'variant': self.event1_variants[2], 'quantity': 5, 'unit_price': 15.00},
            ]
        )
        
        # Draft orders (2 orders) - Don't count for revenue
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[0],
            status=OrderStatusChoices.DRAFT,
            total_amount=25.00,
            created_days_ago=10,
            items_config=[
                {'variant': self.event1_variants[0], 'quantity': 1, 'unit_price': 25.00},
            ]
        )
        
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[0],
            status=OrderStatusChoices.DRAFT,
            total_amount=45.00,
            created_days_ago=8,
            items_config=[
                {'variant': self.event1_variants[4], 'quantity': 1, 'unit_price': 45.00},
            ]
        )
        
        # Pending orders (2 orders) - Don't count for revenue
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[1],
            status=OrderStatusChoices.PENDING,
            total_amount=60.00,
            created_days_ago=15,
            items_config=[
                {'variant': self.event2_variants[0], 'quantity': 1, 'unit_price': 28.00},
                {'variant': self.event2_variants[1], 'quantity': 1, 'unit_price': 28.00},
            ]
        )
        
        self._create_order_with_items(
            attendee=self.attendees[2],
            status=OrderStatusChoices.PENDING,
            total_amount=15.00,
            created_days_ago=12,
            items_config=[
                {'variant': self.event1_variants[7], 'quantity': 1, 'unit_price': 15.00},
            ]
        )
        
        # Processing order (1 order) - Don't count for revenue
        self._create_order_with_items(
            customer=self.regular_user,
            status=OrderStatusChoices.PROCESSING,
            attendee=self.attendees[2], 
            total_amount=28.00,
            created_days_ago=5,
            items_config=[
                {'variant': self.event2_variants[0], 'quantity': 1, 'unit_price': 28.00},
            ]
        )
        
        # Cancelled order (1 order) - Don't count for revenue
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[3],
            status=OrderStatusChoices.CANCELLED,
            total_amount=50.00,
            created_days_ago=50,
            items_config=[
                {'variant': self.event1_variants[1], 'quantity': 2, 'unit_price': 25.00},
            ]
        )
        
        # Refunded order (1 order) - Don't count for revenue
        self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[3],
            status=OrderStatusChoices.REFUNDED,
            total_amount=90.00,
            created_days_ago=55,
            items_config=[
                {'variant': self.event1_variants[4], 'quantity': 2, 'unit_price': 45.00},
            ]
        )
        
        # Soft-deleted order (1 order) - Don't count for revenue
        deleted_order = self._create_order_with_items(
            customer=self.regular_user,
            attendee=self.attendees[4],
            status=OrderStatusChoices.COMPLETED,
            total_amount=25.00,
            created_days_ago=60,
            items_config=[
                {'variant': self.event1_variants[0], 'quantity': 1, 'unit_price': 25.00},
            ],
            soft_delete=True
        )
        
        # Authenticate client
        self.client.force_authenticate(user=self.regular_user)
    
    def _create_product_with_variants(
        self, title, event, category, base_amount=None, is_active=True, verified=True,
        created_days_ago=0, variants_config=None
    ):
        """
        Create product with variants and link to category.
        
        Args:
            title: Product title
            event: Event instance
            category: ProductCategory instance
            base_amount: Money instance for base price
            is_active: Whether product is active
            verified: Whether product is verified
            created_days_ago: Days ago product was created (for testing trends)
            variants_config: List of variant configs:
                [{'size': 'SM', 'color': '#FF0000', 'stock': 20}, ...]
        
        Returns:
            Tuple of (product, [variants])
        """
        if variants_config is None:
            variants_config = []
        
        if base_amount is None:
            base_amount = Money(10, 'GBP')
        
        # Create product
        product = Product.objects.create(
            title=title,
            event=event,
            base_amount=base_amount,
            is_active=is_active,
            verified=verified,
            added_by=self.admin_user
        )
        
        # Set created_at if needed
        if created_days_ago > 0:
            created_at = timezone.now() - timedelta(days=created_days_ago)
            Product.objects.filter(pk=product.pk).update(added_at=created_at)
            product.refresh_from_db()
        
        # Link to category via EventProductCategory
        EventProductCategory.objects.create(
            event=event,
            category=category,
            product=product
        )
        
        # Create variants
        variants = []
        for variant_config in variants_config:
            variant = ProductVariant.objects.create(
                product=product,
                size=variant_config['size'],
                color=variant_config['color'],
                stock_quantity=variant_config['stock'],
                added_by=self.admin_user
            )
            variants.append(variant)
        
        return product, variants
    
    def _create_order_with_items(
        self, customer=None, attendee=None, status='completed',
        total_amount=100.00, created_days_ago=0, items_config=None, soft_delete=False
    ):
        """
        Create order with items.
        
        Args:
            customer: User instance (optional, but one of customer/attendee required)
            attendee: Attendee instance (optional, but one of customer/attendee required)
            status: OrderStatusChoices value
            total_amount: Float for total amount in GBP
            created_days_ago: Days ago order was created
            items_config: List of item configs:
                [{'variant': variant_obj, 'quantity': 2, 'unit_price': 50.00}, ...]
            soft_delete: Whether to soft-delete the order
        
        Returns:
            Order instance
        """
        if items_config is None:
            items_config = []
        
        # Validate at least one of customer or attendee
        if not customer and not attendee:
            raise ValueError("Order must have at least one of customer or attendee")
        
        # Create order
        order = Order.objects.create(
            customer=customer,
            attendee=attendee,
            status=status,
            total_amount=Money(0, 'GBP'),  # Will be set after items
            created_by=customer if customer else attendee.defined_by
        )
        
        # Set created_at if needed
        if created_days_ago > 0:
            created_at = timezone.now() - timedelta(days=created_days_ago)
            Order.objects.filter(pk=order.pk).update(created_at=created_at)
            order.refresh_from_db()
        
        # Create order items
        calculated_total = Decimal('0.00')
        for item_config in items_config:
            variant = item_config['variant']
            quantity = item_config['quantity']
            unit_price = Decimal(str(item_config['unit_price']))
            total_price = unit_price * Decimal(quantity)
            
            OrderItem.objects.create(
                order=order,
                product_variant=variant,
                quantity=quantity,
                unit_price=Money(unit_price, 'GBP'),
                total_price=Money(total_price, 'GBP')
            )
            
            calculated_total += total_price
        
        # Update order total
        Order.objects.filter(pk=order.pk).update(
            total_amount=Money(calculated_total, 'GBP')
        )
        order.refresh_from_db()
        
        # Handle soft delete
        if soft_delete:
            Order.objects.filter(pk=order.pk).update(deleted_at=timezone.now())
            order.refresh_from_db()
        
        self.orders.append(order)
        return order


# ============================================================================
# PRODUCT STATISTICS TESTS
# ============================================================================

class ProductOverviewStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for product overview statistics."""
    
    def test_basic_overview(self):
        """Test basic product overview statistics."""
        result = statistics.calculate_product_overview()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_products', result)
        self.assertIn('active_products', result)
        self.assertIn('inactive_products', result)
        self.assertIn('verified_products', result)
        self.assertIn('unverified_products', result)
        
        # Total: 6 from event1 + 4 from event2 + 2 from event3 = 12 products
        self.assertEqual(result['total_products'], 12)
        self.assertEqual(result['active_products'], 9)
        self.assertEqual(result['inactive_products'], 3)
        self.assertEqual(result['verified_products'], 9)
        self.assertEqual(result['unverified_products'], 3)
    
    def test_overview_with_event_filter(self):
        """Test overview filtered by event."""
        result = statistics.calculate_product_overview(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total_products'], 6)
        self.assertEqual(result['active_products'], 5)
        self.assertEqual(result['inactive_products'], 1)
    
    def test_overview_with_organization_filter(self):
        """Test overview filtered by organization."""
        result = statistics.calculate_product_overview(
            organization_id=self.org1.id
        )
        
        # org1 has event1 (6 products) + event2 (4 products) = 10 products
        self.assertEqual(result['total_products'], 10)
    
    def test_overview_empty_event(self):
        """Test overview with non-existent event."""
        result = statistics.calculate_product_overview(
            event_id='00000000-0000-0000-0000-000000000000'
        )
        
        self.assertEqual(result['total_products'], 0)
        self.assertEqual(result['active_products'], 0)


class CategoryDistributionStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for product category distribution statistics."""
    
    def test_basic_distribution(self):
        """Test basic category distribution."""
        result = statistics.calculate_category_distribution()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_categories', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
        
        # Check categories are present
        category_names = [item['label'] for item in result['distribution']]
        self.assertIn('Apparel', category_names)
        self.assertIn('Food', category_names)
        self.assertIn('Merchandise', category_names)
    
    def test_distribution_percentages(self):
        """Test percentage calculations sum to 100."""
        result = statistics.calculate_category_distribution()
        
        total_pct = sum(item['percentage'] for item in result['distribution'])
        self.assertAlmostEqual(total_pct, 100.0, places=0)
    
    def test_distribution_with_event_filter(self):
        """Test category distribution filtered by event."""
        result = statistics.calculate_category_distribution(
            event_id=str(self.event1.event_id)
        )
        
        # event1 has products in all 3 categories
        self.assertEqual(result['total_categories'], 3)
    
    def test_distribution_counts(self):
        """Test category counts are accurate."""
        result = statistics.calculate_category_distribution()
        
        # Find Apparel category
        apparel = next(
            (item for item in result['distribution'] if item['label'] == 'Apparel'),
            None
        )
        self.assertIsNotNone(apparel)
        # Event1: 3 apparel, Event2: 1 apparel, Event3: 1 apparel = 5 total
        self.assertEqual(apparel['value'], 5)


class StatusDistributionStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for product status distribution statistics."""
    
    def test_basic_status_distribution(self):
        """Test basic status distribution."""
        result = statistics.calculate_status_distribution()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_products', result)

        #{'total_products': 12, 'distribution': [{'label': 'Active & Verified', 'value': 7, 'percentage': 58.33, 'code': 'active_verified'}, {'label': 'Active & Unverified', 'value': 2, 'percentage': 16.67, 'code': 'active_unverified'}, {'label': 'Inactive & Verified', 'value': 2, 'percentage': 16.67, 'code': 'inactive_verified'}, {'label': 'Inactive & Unverified', 'value': 1, 'percentage': 8.33, 'code': 'inactive_unverified'}], 'generated_at': '2026-03-10T17:18:45.045402+00:00'}
        # thus

        for item in result['distribution']:
            self.assertIn('label', item)
            self.assertIn('value', item)
            self.assertIn('percentage', item)
            self.assertIn('code', item)

        # check active_verified
        active_verified = next(
            (item for item in result['distribution'] if item['code'] == 'active_verified'),
            None
        )
        self.assertIsNotNone(active_verified)

        active_unverified = next(
            (item for item in result['distribution'] if item['code'] == 'active_unverified'),
            None
        )
        self.assertIsNotNone(active_unverified)

        inactive_verified = next(
            (item for item in result['distribution'] if item['code'] == 'inactive_verified'),
            None
        )
        self.assertIsNotNone(inactive_verified)

        inactive_unverified = next(
            (item for item in result['distribution'] if item['code'] == 'inactive_unverified'),
            None
        )
        self.assertIsNotNone(inactive_unverified)

    def test_status_with_event_filter(self):
        """Test status distribution filtered by event."""
        result = statistics.calculate_status_distribution(
            event_id=str(self.event2.event_id)
        )
        self.assertEqual(result['total_products'], 4)

        # TODO: fix these tests
        # self.assertEqual(result['active_count'], 2)
        # self.assertEqual(result['inactive_count'], 2)


class ProductTrendsStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for product creation trends statistics."""
    
    def test_basic_trends(self):
        """Test basic product trends."""
        result = statistics.calculate_product_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now())
        
        self.assertIsInstance(result, dict)
        self.assertIn('period_days', result)
        self.assertIn('total_products', result)
        self.assertIn('trends', result)
        
        self.assertEqual(result['period_days'], 60)
        self.assertGreater(result['total_products'], 0)
    
    def test_trends_grouping_day(self):
        """Test trends grouped by day."""
        result = statistics.calculate_product_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='day')
        
        self.assertIsInstance(result['trends'], list)
        if result['trends']:
            self.assertIn('date', result['trends'][0])
            self.assertIn('count', result['trends'][0])
    
    def test_trends_grouping_week(self):
        """Test trends grouped by week."""
        result = statistics.calculate_product_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='week')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_grouping_month(self):
        """Test trends grouped by month."""
        result = statistics.calculate_product_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='month')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_with_event_filter(self):
        """Test trends filtered by event."""
        result = statistics.calculate_product_trends(
            event_id=str(self.event1.event_id),
            date_from=timezone.now() - timedelta(days=60),
            date_to=timezone.now()
        )
        
        # event1 has 6 products created in last 60 days
        self.assertGreater(result['total_products'], 0)
    
    def test_trends_empty_period(self):
        """Test trends with period that has no products."""
        result = statistics.calculate_product_trends(date_from=timezone.now(), date_to=timezone.now())
        
        self.assertEqual(result['total_products'], 0)


# ============================================================================
# VARIANT STATISTICS TESTS
# ============================================================================

class VariantStockOverviewStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for variant stock overview statistics."""
    
    def test_basic_stock_overview(self):
        """Test basic stock overview."""
        result = statistics.calculate_variant_stock_overview()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_variants', result)
        self.assertIn('total_stock', result)
        self.assertIn('in_stock_count', result)
        self.assertIn('out_of_stock_count', result)
        self.assertIn('low_stock_count', result)
        
        self.assertGreater(result['total_variants'], 0)
        self.assertGreater(result['total_stock'], 0)
    
    def test_stock_overview_with_event_filter(self):
        """Test stock overview filtered by event."""
        result = statistics.calculate_variant_stock_overview(
            event_id=str(self.event1.event_id)
        )
        
        # event1 has multiple variants
        self.assertGreater(result['total_variants'], 0)
    
    def test_stock_classification(self):
        """Test stock classification is accurate."""
        result = statistics.calculate_variant_stock_overview()
        
        # We have variants with stock=0, stock=1-9, stock>10
        self.assertGreater(result['out_of_stock_count'], 0)
        self.assertGreater(result['low_stock_count'], 0)
        self.assertGreater(result['in_stock_count'], 0)


class SizeDistributionStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for variant size distribution statistics."""
    
    def test_basic_size_distribution(self):
        """Test basic size distribution."""
        result = statistics.calculate_size_distribution()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_variants', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_size_distribution_percentages(self):
        """Test size distribution percentages sum to 100."""
        result = statistics.calculate_size_distribution()
        
        if result['distribution']:
            total_pct = sum(item['percentage'] for item in result['distribution'])
            self.assertAlmostEqual(total_pct, 100.0, places=0)
    
    def test_size_distribution_has_all_sizes(self):
        """Test distribution includes all present size choices."""
        result = statistics.calculate_size_distribution()
        
        size_labels = [item['label'] for item in result['distribution']]
        
        # We created variants with various sizes
        self.assertIn('Small', size_labels)
        self.assertIn('Medium', size_labels)
        self.assertIn('Large', size_labels)
        self.assertIn('Extra Large', size_labels)
        self.assertIn('Not Applicable', size_labels)
    
    def test_size_distribution_with_event_filter(self):
        """Test size distribution filtered by event."""
        result = statistics.calculate_size_distribution(
            event_id=str(self.event1.event_id)
        )
        
        self.assertGreater(result['total_variants'], 0)


class ColorDistributionStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for variant color distribution statistics."""
    
    def test_basic_color_distribution(self):
        """Test basic color distribution."""
        result = statistics.calculate_color_distribution()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_variants', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_color_distribution_percentages(self):
        """Test color distribution percentages sum to 100."""
        result = statistics.calculate_color_distribution()
        
        if result['distribution']:
            total_pct = sum(item['percentage'] for item in result['distribution'])
            self.assertAlmostEqual(total_pct, 100.0, places=0)
    
    def test_color_distribution_with_event_filter(self):
        """Test color distribution filtered by event."""
        result = statistics.calculate_color_distribution(
            event_id=str(self.event2.event_id)
        )
        
        self.assertGreater(result['total_variants'], 0)


class StockLevelsStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for stock level distribution statistics."""
    
    def test_basic_stock_levels(self):
        """Test basic stock levels distribution."""
        result = statistics.calculate_stock_levels()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_variants', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_stock_level_ranges(self):
        """Test stock level ranges are present."""
        result = statistics.calculate_stock_levels()
        
        ranges = [item['label'] for item in result['distribution']]
        
        # Should have various stock ranges
        self.assertIn('Out of Stock (0)', ranges)  # Out of stock
        self.assertIn('Low Stock (1-10)', ranges)  # Low stock
    
    def test_stock_levels_percentages(self):
        """Test stock level percentages sum to 100."""
        result = statistics.calculate_stock_levels()
        
        if result['distribution']:
            total_pct = sum(item['percentage'] for item in result['distribution'])
            self.assertAlmostEqual(total_pct, 100.0, places=0)
    
    def test_stock_levels_with_event_filter(self):
        """Test stock levels filtered by event."""
        result = statistics.calculate_stock_levels(
            event_id=str(self.event1.event_id)
        )
        
        self.assertGreater(result['total_variants'], 0)


# ============================================================================
# ORDER STATISTICS TESTS
# ============================================================================

class OrderStatusDistributionStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for order status distribution statistics."""
    
    def test_basic_status_distribution(self):
        """Test basic order status distribution."""
        result = statistics.calculate_order_status_distribution()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_orders', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
        
        # Should exclude soft-deleted order
        self.assertEqual(result['total_orders'], 13)  # 15 created - 1 deleted
    
    def test_status_distribution_percentages(self):
        """Test status distribution percentages sum to 100."""
        result = statistics.calculate_order_status_distribution()
        
        total_pct = sum(item['percentage'] for item in result['distribution'])
        self.assertAlmostEqual(total_pct, 100.0, places=0)
    
    def test_status_distribution_has_all_statuses(self):
        """Test distribution includes all order statuses present."""
        result = statistics.calculate_order_status_distribution()
        
        statuses = [item['label'].upper() for item in result['distribution']]
        
        self.assertIn(OrderStatusChoices.COMPLETED.label.upper(), statuses)
        self.assertIn(OrderStatusChoices.DRAFT.label.upper(), statuses)
        self.assertIn(OrderStatusChoices.PENDING.label.upper(), statuses)
    
    def test_status_distribution_with_event_filter(self):
        """Test status distribution filtered by event."""
        result = statistics.calculate_order_status_distribution(
            event_id=str(self.event1.event_id)
        )
        
        self.assertGreater(result['total_orders'], 0)
    
    def test_status_distribution_include_deleted(self):
        """Test status distribution with deleted included."""
        result_without = statistics.calculate_order_status_distribution()
        result_with = statistics.calculate_order_status_distribution(include_deleted=True)
        print(result_without)
        print(result_with)
        self.assertEqual(result_without['total_orders'], 13)
        self.assertEqual(result_with['total_orders'], 14)


class OrderTrendsStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for order trends statistics."""
    
    def test_basic_order_trends(self):
        """Test basic order trends."""
        result = statistics.calculate_order_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now())
        
        self.assertIsInstance(result, dict)
        self.assertIn('period_days', result)
        self.assertIn('total_orders', result)
        self.assertIn('trends', result)
        
        self.assertEqual(result['period_days'], 60)
        self.assertGreater(result['total_orders'], 0)
    
    def test_trends_grouping_day(self):
        """Test order trends grouped by day."""
        result = statistics.calculate_order_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='day')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_grouping_week(self):
        """Test order trends grouped by week."""
        result = statistics.calculate_order_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='week')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_grouping_month(self):
        """Test order trends grouped by month."""
        result = statistics.calculate_order_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='month')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_cumulative(self):
        """Test cumulative order trends."""
        result = statistics.calculate_order_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), cumulative=True)
        
        self.assertIn('cumulative', result)
        self.assertTrue(result['cumulative'])
        
        # Cumulative counts should be non-decreasing
        if len(result['trends']) > 1:
            for i in range(1, len(result['trends'])):
                self.assertGreaterEqual(
                    result['trends'][i]['count'],
                    result['trends'][i-1]['count']
                )
    
    def test_trends_with_event_filter(self):
        """Test order trends filtered by event."""
        result = statistics.calculate_order_trends(
            event_id=str(self.event1.event_id),
            date_from=timezone.now() - timedelta(days=60),
            date_to=timezone.now()  
        )
        
        self.assertGreater(result['total_orders'], 0)


class OrdersByProductStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for orders by product statistics."""
    
    def test_basic_orders_by_product(self):
        """Test basic orders by product."""
        result = statistics.calculate_orders_by_product()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_products', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_orders_by_product_ordering(self):
        """Test products are ordered by order count descending."""
        result = statistics.calculate_orders_by_product()
        
        if len(result['distribution']) > 1:
            for i in range(1, len(result['distribution'])):
                self.assertLessEqual(
                    result['distribution'][i]['value'],
                    result['distribution'][i-1]['value']
                )
    
    def test_orders_by_product_limit(self):
        """Test limit parameter works."""
        result = statistics.calculate_orders_by_product(limit=5)
        
        self.assertLessEqual(len(result['distribution']), 5)
    
    def test_orders_by_product_with_event_filter(self):
        """Test orders by product filtered by event."""
        result = statistics.calculate_orders_by_product(
            event_id=str(self.event1.event_id)
        )
        
        # All products should be from event1
        # TODO: fix this
        # for product in result['distribution']:
        #     self.assertEqual(product['event_id'], str(self.event1.event_id))


class OrdersByCategoryStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for orders by category statistics."""
    
    def test_basic_orders_by_category(self):
        """Test basic orders by category."""
        result = statistics.calculate_orders_by_category()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_categories', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_orders_by_category_ordering(self):
        """Test categories are ordered by order count descending."""
        result = statistics.calculate_orders_by_category()
        
        if len(result['distribution']) > 1:
            for i in range(1, len(result['distribution'])):
                self.assertLessEqual(
                    result['distribution'][i]['value'],
                    result['distribution'][i-1]['value']
                )
    
    def test_orders_by_category_with_event_filter(self):
        """Test orders by category filtered by event."""
        result = statistics.calculate_orders_by_category(
            event_id=str(self.event1.event_id)
        )
        
        self.assertGreater(result['total_categories'], 0)


# ============================================================================
# REVENUE STATISTICS TESTS (CRITICAL)
# ============================================================================

class RevenueOverviewStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for revenue overview statistics - CRITICAL revenue calculation tests."""
    
    def test_only_completed_orders_counted(self):
        """CRITICAL: Verify only completed orders included in revenue."""
        result = statistics.calculate_revenue_overview()
        
        # Calculate expected revenue from completed orders only
        completed_orders = Order.objects.filter(
            status=OrderStatusChoices.COMPLETED,
            deleted_at__isnull=True
        )
        expected_revenue = sum(
            float(order.total_amount.amount) for order in completed_orders
        )
        
        self.assertAlmostEqual(
            result['total_revenue'],
            expected_revenue,
            places=2,
            msg="Revenue should only include completed orders"
        )
        
        # Verify count matches completed orders
        self.assertEqual(result['total_orders'], completed_orders.count())
        self.assertEqual(result['total_orders'], 6)  # We created 6 completed orders
        
        # Verify draft, pending, cancelled, refunded NOT included
        total_orders = Order.objects.filter(deleted_at__isnull=True).count()
        self.assertLess(result['total_orders'], total_orders)
    
    def test_revenue_overview_basic(self):
        """Test basic revenue overview structure."""
        result = statistics.calculate_revenue_overview()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_revenue', result)
        self.assertIn('total_orders', result)
        self.assertIn('average_order_value', result)
        
        self.assertGreater(result['total_revenue'], 0)
        self.assertGreater(result['total_orders'], 0)
        self.assertGreater(result['average_order_value'], 0)
    
    def test_revenue_average_calculation(self):
        """Test average order value is calculated correctly."""
        result = statistics.calculate_revenue_overview()
        
        expected_avg = result['total_revenue'] / result['total_orders']
        self.assertAlmostEqual(
            result['average_order_value'],
            expected_avg,
            places=2
        )
    
    def test_revenue_with_event_filter(self):
        """Test revenue overview filtered by event."""
        result = statistics.calculate_revenue_overview(
            event_id=str(self.event1.event_id)
        )
        
        # Only event1 completed orders should be counted
        self.assertGreater(result['total_revenue'], 0)
        
        # Verify only event1 data
        event1_completed = Order.objects.filter(
            status=OrderStatusChoices.COMPLETED,
        ).filter(
            Q(attendee__event=self.event1) 
        ).distinct()
        
        expected_revenue = sum(
            float(order.total_amount.amount) for order in event1_completed
        )
        self.assertAlmostEqual(
            result['total_revenue'],
            expected_revenue,
            places=2
        )
    
    def test_revenue_with_organization_filter(self):
        """Test revenue overview filtered by organization."""
        result = statistics.calculate_revenue_overview(
            organization_id=self.org1.id
        )
        
        # org1 has event1 and event2
        self.assertGreater(result['total_revenue'], 0)
    
    def test_revenue_include_deleted(self):
        """Test revenue with soft-deleted orders included."""
        result_without = statistics.calculate_revenue_overview()
        result_with = statistics.calculate_revenue_overview(include_deleted=True)
        
        # Deleted order was completed, so revenue should increase
        self.assertGreater(result_with['total_revenue'], result_without['total_revenue'])
        self.assertEqual(result_with['total_orders'], result_without['total_orders'] + 1)
    
    def test_revenue_zero_when_no_completed_orders(self):
        """Test revenue is 0 when no completed orders exist."""
        # Query for event with no completed orders
        result = statistics.calculate_revenue_overview(
            event_id=str(self.event3.event_id)
        )
        
        # Event3 has no orders at all
        self.assertEqual(result['total_revenue'], 0)
        self.assertEqual(result['total_orders'], 0)


class RevenueByProductStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for revenue by product statistics."""
    
    def test_only_completed_orders_counted(self):
        """CRITICAL: Verify only completed orders in product revenue."""
        result = statistics.calculate_revenue_by_product()
        
        # All products listed should have revenue only from completed orders
        for product_data in result['distribution']:
            # Verify by querying directly
            product_revenue = OrderItem.objects.filter(
                product_variant__product__title=product_data['label'],
                order__status=OrderStatusChoices.COMPLETED,
                order__deleted_at__isnull=True
            ).aggregate(
                total=Sum('total_price')
            )['total']
            
            if product_revenue:
                self.assertAlmostEqual(
                    product_data['value'],
                    float(product_revenue),
                    places=2
                )
    
    def test_basic_revenue_by_product(self):
        """Test basic revenue by product."""
        result = statistics.calculate_revenue_by_product()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_products', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_revenue_by_product_ordering(self):
        """Test products ordered by revenue descending."""
        result = statistics.calculate_revenue_by_product()
        
        if len(result['distribution']) > 1:
            for i in range(1, len(result['distribution'])):
                self.assertLessEqual(
                    result['distribution'][i]['value'],
                    result['distribution'][i-1]['value']
                )
    
    def test_revenue_by_product_limit(self):
        """Test limit parameter works."""
        result = statistics.calculate_revenue_by_product(limit=5)
        
        self.assertLessEqual(len(result['distribution']), 5)
    
    def test_revenue_by_product_with_event_filter(self):
        """Test revenue by product filtered by event."""
        result = statistics.calculate_revenue_by_product(
            event_id=str(self.event1.event_id)
        )
        
        # TODO: fix this


class RevenueByCategoryStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for revenue by category statistics."""
    
    def test_only_completed_orders_counted(self):
        """CRITICAL: Verify only completed orders in category revenue."""
        result = statistics.calculate_revenue_by_category()
        
        # All categories listed should have revenue only from completed orders
        for category_data in result['distribution']:
            # Verify by querying directly
            category_revenue = OrderItem.objects.filter(
                product_variant__product__event_product_categories__category__name=category_data['label'],
                order__status=OrderStatusChoices.COMPLETED,
                order__deleted_at__isnull=True
            ).aggregate(
                total=Sum('total_price')
            )['total']
            
            if category_revenue:
                self.assertAlmostEqual(
                    category_data['value'],
                    float(category_revenue),
                    places=2
                )
    
    def test_basic_revenue_by_category(self):
        """Test basic revenue by category."""
        result = statistics.calculate_revenue_by_category()
        
        self.assertIsInstance(result, dict)
        self.assertIn('total_categories', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_revenue_by_category_ordering(self):
        """Test categories ordered by revenue descending."""
        result = statistics.calculate_revenue_by_category()
        
        if len(result['distribution']) > 1:
            for i in range(1, len(result['distribution'])):
                self.assertLessEqual(
                    result['distribution'][i]['value'],
                    result['distribution'][i-1]['value']
                )
    
    def test_revenue_by_category_with_event_filter(self):
        """Test revenue by category filtered by event."""
        result = statistics.calculate_revenue_by_category(
            event_id=str(self.event1.event_id)
        )
        
        self.assertGreater(result['total_categories'], 0)


class RevenueTrendsStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for revenue trends statistics."""
    
    def test_only_completed_orders_counted(self):
        """CRITICAL: Verify only completed orders in revenue trends."""
        result = statistics.calculate_revenue_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now())
        
        # Total revenue should match completed orders only
        completed_orders = Order.objects.filter(
            status=OrderStatusChoices.COMPLETED,
            deleted_at__isnull=True,
            created_at__gte=timezone.now() - timedelta(days=60)
        )
        expected_revenue = sum(
            float(order.total_amount.amount) for order in completed_orders
        )
        
        self.assertAlmostEqual(
            result['total_revenue'],
            expected_revenue,
            places=2
        )
    
    def test_basic_revenue_trends(self):
        """Test basic revenue trends."""
        result = statistics.calculate_revenue_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now())
        
        self.assertIsInstance(result, dict)
        self.assertIn('period_days', result)
        self.assertIn('total_revenue', result)
        self.assertIn('trends', result)
        
        self.assertEqual(result['period_days'], 60)
        self.assertGreater(result['total_revenue'], 0)
    
    def test_trends_grouping_day(self):
        """Test revenue trends grouped by day."""
        result = statistics.calculate_revenue_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='day')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_grouping_week(self):
        """Test revenue trends grouped by week."""
        result = statistics.calculate_revenue_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='week')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_grouping_month(self):
        """Test revenue trends grouped by month."""
        result = statistics.calculate_revenue_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now(), group_by='month')
        
        self.assertIsInstance(result['trends'], list)
    
    def test_trends_order(self):
        """Test order revenue trends."""
        result = statistics.calculate_revenue_trends(date_from=timezone.now() - timedelta(days=60), date_to=timezone.now())
        print(result['trends'])
        if len(result['trends']) > 1:
            for i in range(1, len(result['trends'])):
                self.assertGreaterEqual(
                    result['trends'][i]['date'],
                    result['trends'][i-1]['date']
                )
    
    def test_trends_with_event_filter(self):
        """Test revenue trends filtered by event."""
        result = statistics.calculate_revenue_trends(
            date_from=timezone.now() - timedelta(days=60),
            date_to=timezone.now(),
            event_id=str(self.event1.event_id),
        )
        
        self.assertGreater(result['total_revenue'], 0)


class RevenueBreakdownStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for revenue breakdown statistics."""
    
    def test_only_completed_orders_counted(self):
        """CRITICAL: Verify only completed orders in revenue breakdown."""
        result = statistics.calculate_revenue_breakdown_by_source()
        
        # Calculate expected values from completed orders only
        completed_orders = Order.objects.filter(
            status=OrderStatusChoices.COMPLETED,
            deleted_at__isnull=True
        )
        
        expected_total = sum(
            float(order.total_amount.amount) for order in completed_orders
        )
        
        self.assertAlmostEqual(
            result['total_revenue'],
            expected_total,
            places=2
        )
    
    def test_basic_revenue_breakdown(self):
        """Test basic revenue breakdown."""
        result = statistics.calculate_revenue_breakdown_by_source()
        # {'total_revenue': 472.0, 'distribution': [{'label': 'Standalone Products', 'value': 472.0, 'percentage': 100.0, 'code': 'standalone'}, 
        # # {'label': 'Package-Linked Products', 'value': 0.0, 'percentage': 0.0, 'code': 'package'}], 'generated_at': '2026-03-10T17:18:15.777205+00:00'}
        self.assertIsInstance(result, dict)
        self.assertIn('total_revenue', result)
        self.assertIn('distribution', result)
        self.assertIsInstance(result['distribution'], list)
    
    def test_breakdown_totals_match(self):
        """Test breakdown totals match overall total."""
        result = statistics.calculate_revenue_breakdown_by_source()
        
        # Sum of product revenues should equal total revenue
        product_total = sum(p['value'] for p in result['distribution'])
        self.assertAlmostEqual(
            product_total,
            result['total_revenue'],
            places=2
        )
    
    def test_breakdown_with_event_filter(self):
        """Test revenue breakdown filtered by event."""
        result = statistics.calculate_revenue_breakdown_by_source(
            event_id=str(self.event1.event_id)
        )
        
        # TODO: fix this
        # # All breakdowns should be for event1 only
        # for event_data in result['distribution']:
        #     self.assertEqual(event_data['event_id'], str(self.event1.event_id))


# ============================================================================
# OVERVIEW STATISTICS TESTS
# ============================================================================

class OverviewStatisticsTests(ProductStatisticsBaseTestCase):
    """Tests for combined overview statistics."""
    
    def test_basic_overview(self):
        """Test basic combined overview."""
        result = statistics.calculate_overview_statistics()
        
        self.assertIsInstance(result, dict)
        self.assertIn('product_summary', result)
        self.assertIn('variant_summary', result)
        self.assertIn('order_summary', result)
        self.assertIn('revenue_summary', result)
    
    def test_overview_structure(self):
        """Test overview has all required sections."""
        result = statistics.calculate_overview_statistics()
        
        # Products section
        self.assertIn('total_products', result['product_summary'])
        self.assertIn('active_products', result['product_summary'])
        
        # Variants section
        self.assertIn('total_variants', result['variant_summary'])
        self.assertIn('total_stock', result['variant_summary'])
        
        # Orders section
        self.assertIn('total_orders', result['order_summary'])
        
        # Revenue section (CRITICAL: only completed orders)
        self.assertIn('total_revenue', result['revenue_summary'])
        self.assertIn('completed_orders', result['revenue_summary'])
    
    def test_overview_with_event_filter(self):
        """Test overview filtered by event."""
        result = statistics.calculate_overview_statistics(
            event_id=str(self.event1.event_id)
        )
        
        self.assertGreater(result['product_summary']['total_products'], 0)
        self.assertGreater(result['variant_summary']['total_variants'], 0)
    
    def test_overview_with_organization_filter(self):
        """Test overview filtered by organization."""
        result = statistics.calculate_overview_statistics(
            organization_id=self.org1.id
        )
        
        self.assertGreater(result['product_summary']['total_products'], 0)


# ============================================================================
# API ENDPOINT TESTS
# ============================================================================

class ProductStatisticsAPITests(ProductStatisticsBaseTestCase):
    """Tests for product statistics API endpoints."""
    
    def test_list_endpoints(self):
        """Test endpoint discovery."""
        response = self.client.get('/api/products/statistics/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIsInstance(data, dict)
        self.assertIn('endpoints', data)
    
    def test_authentication_required(self):
        """Test all endpoints require authentication."""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/products/statistics/overview/')
        self.assertIn(response.status_code, [401, 403])
    
    def test_overview_endpoint_raw_format(self):
        """Test overview endpoint returns raw format."""
        response = self.client.get('/api/products/statistics/overview/?format=raw')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('product_summary', data)
        self.assertIn('variant_summary', data)
        self.assertIn('order_summary', data)
        self.assertIn('revenue_summary', data)
    
    def test_overview_endpoint_echarts_format(self):
        """Test overview endpoint returns ECharts format."""
        response = self.client.get('/api/products/statistics/overview/?format=echarts')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        # ECharts format should have chart-ready data
        self.assertIsInstance(data, dict)
    
    def test_product_overview_endpoint(self):
        """Test product overview endpoint."""
        response = self.client.get('/api/products/statistics/product-overview/?format=raw')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('total_products', data)
        self.assertIn('active_products', data)
    
    def test_category_distribution_endpoint(self):
        """Test category distribution endpoint."""
        response = self.client.get('/api/products/statistics/category-distribution/?format=raw')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('total_categories', data)
        self.assertIn('distribution', data)
    
    def test_revenue_overview_endpoint(self):
        """Test revenue overview endpoint."""
        response = self.client.get('/api/products/statistics/revenue-overview/?format=raw')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('total_revenue', data)
        self.assertIn('total_orders', data)
        self.assertIn('average_order_value', data)
    
    def test_filters_applied_metadata(self):
        """Test filters_applied in response metadata."""
        response = self.client.get(
            f'/api/products/statistics/overview/?event_id={str(self.event1.event_id)}&format=raw'
        )
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('filters_applied', data)
        self.assertIn('event_id', data['filters_applied'])
        self.assertEqual(
            data['filters_applied']['event_id'],
            str(self.event1.event_id)
        )
    
    def test_query_parameter_validation(self):
        """Test invalid parameters are handled."""
        # Invalid UUID should be handled gracefully
        response = self.client.get('/api/products/statistics/overview/?event_id=invalid-uuid')
        # Should either return 400 or empty results depending on implementation
        self.assertIn(response.status_code, [200, 400])
    
    def test_all_major_endpoints_accessible(self):
        """Test all major endpoints are accessible."""
        endpoints = [
            '/api/products/statistics/overview/',
            '/api/products/statistics/product-overview/',
            '/api/products/statistics/category-distribution/',
            '/api/products/statistics/status-distribution/',
            '/api/products/statistics/variant-stock-overview/',
            '/api/products/statistics/order-status-distribution/',
            '/api/products/statistics/revenue-overview/',
            '/api/products/statistics/revenue-by-product/',
            '/api/products/statistics/revenue-by-category/',
        ]
        
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(f'{endpoint}?format=raw')
                self.assertEqual(
                    response.status_code,
                    200,
                    f"Endpoint {endpoint} failed with status {response.status_code}"
                )
