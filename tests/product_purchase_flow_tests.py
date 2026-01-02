"""
Full product purchase flow integration test.

Tests the complete product purchase journey:
1. Browse available products for an event
2. Select product variants (size, color)
3. Check eligibility and stock
4. Create order (cart)
5. Add products to order with quantity checks
6. Apply discounts based on attendee context
7. Calculate final prices
8. Create payment
9. Complete order and verify stock updates

Scenario:
Emma (22) is attending a conference and wants to purchase merchandise:
- Conference T-Shirt (Medium, Blue) - £20, gets 10% student discount = £18
- Conference Hoodie (Large, Black) - £40, standard price
- Conference Mug (One Size, White) - £10, free for event staff = £0
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import date, timedelta
from decimal import Decimal
from djmoney.money import Money
import os

from apps.products.models import (
    Product, ProductVariant, ProductSizeChoices,
    Order, OrderStatusChoices, OrderItem
)
from apps.payments.models import (
    Payment, PaymentMethod, PaymentMethodTypeChoices,
    PaymentStatusChoices, Discount, DiscountType,
    DiscountRule, DiscountRuleTypeChoices
)
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.bookings.models import Booking
from apps.common.models.resource import Resource, ResourceTypeChoices
from apps.payments.evaluator import DiscountContext
from apps.organisations.models import Organisation

User = get_user_model()


class FullProductPurchaseFlowTest(TestCase):
    """
    Test the complete product purchase flow from browsing to order completion.
    """
    
    def setUp(self):
        """Set up test data for the full product purchase flow"""
        # Create Emma's user account
        self.emma = User.objects.create_user(
            username='emma',
            email='emma@example.com',
            password='testpass123'
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Tech Conference',
            code='TECH',
            created_by=self.emma
        )

        self.organisation = Organisation.objects.create(
            title='Tech Conference Org',
            created_by=self.emma
        )
        
        self.event = Event.objects.create(
            title='Annual Tech Conference 2025',
            display_code='TC2025',
            display_identifier='TC2025TECH001',
            created_by=self.emma,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create booking and attendee for Emma
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-EMMA-001',
            made_by=self.emma
        )
        
        self.emma_attendee = Attendee.objects.create(
            first_name='Emma',
            last_name='Johnson',
            user=self.emma,
            event=self.event,
            date_of_birth=date(2003, 5, 15),  # 22 years old
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.emma
        )
        
        # Create products
        self.tshirt = Product.objects.create(
            title='Conference T-Shirt',
            description='Official conference merchandise',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.emma,
            verified=True,
            is_active=True
        )
        
        self.hoodie = Product.objects.create(
            title='Conference Hoodie',
            description='Premium conference hoodie',
            event=self.event,
            base_amount=Money(40, 'GBP'),
            added_by=self.emma,
            verified=True,
            is_active=True
        )
        
        self.mug = Product.objects.create(
            title='Conference Mug',
            description='Ceramic mug with conference logo',
            event=self.event,
            base_amount=Money(10, 'GBP'),
            added_by=self.emma,
            verified=True,
            is_active=True
        )
        
        # Create product variants
        self.tshirt_medium_blue = ProductVariant.objects.create(
            product=self.tshirt,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=50,
            max_stock_quantity=100,
            max_purchase_quantity_per_order=5,
            added_by=self.emma,
            verified=True,
            is_active=True
        )
        
        self.hoodie_large_black = ProductVariant.objects.create(
            product=self.hoodie,
            size=ProductSizeChoices.LARGE,
            color='#000000',
            stock_quantity=30,
            max_stock_quantity=50,
            max_purchase_quantity_per_order=3,
            added_by=self.emma,
            verified=True,
            is_active=True
        )
        
        self.mug_onesize_white = ProductVariant.objects.create(
            product=self.mug,
            size=ProductSizeChoices.ONE_SIZE,
            color='#FFFFFF',
            stock_quantity=100,
            max_stock_quantity=200,
            max_purchase_quantity_per_order=10,
            added_by=self.emma,
            verified=True,
            is_active=True
        )
        
        # Create discounts
        # Student discount for t-shirt (10%)
        self.student_discount = Discount.objects.create(
            name='Student Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(ProductVariant),
            target_id=self.tshirt_medium_blue.id
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 25',
            discount=self.student_discount,
            value='25',
            active=True
        )
        
        # Staff discount for mug (100% - free)
        self.staff_discount = Discount.objects.create(
            name='Staff Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('100.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(ProductVariant),
            target_id=self.mug_onesize_white.id
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_EVENT_STAFF,
            name='Is Event Staff',
            discount=self.staff_discount,
            value='',
            active=True
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit/Debit Card',
            is_active=True,
            created_by=self.emma
        )
        
    def test_full_purchase_flow_non_staff_student(self):
        """
        Test complete purchase flow for a non-staff student.
        Emma (student, non-staff) purchases T-Shirt and Hoodie.
        """
        
        # ===== STEP 1: Browse available products =====
        # Emma browses products available for the event
        available_products = Product.objects.filter(
            event=self.event,
            is_active=True,
            verified=True
        )
        
        self.assertEqual(available_products.count(), 3)
        self.assertIn(self.tshirt, available_products)
        self.assertIn(self.hoodie, available_products)
        self.assertIn(self.mug, available_products)
        
        # ===== STEP 2: Select product variants =====
        # Emma selects T-Shirt (Medium, Blue) and Hoodie (Large, Black)
        selected_variants = [
            (self.tshirt_medium_blue, 1),
            (self.hoodie_large_black, 1),
        ]
        
        # ===== STEP 3: Check eligibility and stock =====
        for variant, quantity in selected_variants:
            # Check if Emma can purchase
            can_purchase = variant.can_attendee_purchase(self.emma_attendee)
            self.assertTrue(can_purchase, f"Emma should be able to purchase {variant}")
            
            # Check if quantity is available
            can_purchase_qty = variant.can_attendee_purchase_quantity(
                self.emma_attendee, 
                quantity
            )
            self.assertTrue(can_purchase_qty, f"Quantity {quantity} should be available for {variant}")
        
        # ===== STEP 4: Create order (cart) =====
        order = Order.objects.create(
            customer=self.emma,
            attendee=self.emma_attendee,
            status=OrderStatusChoices.DRAFT, # TODO: shoulder be DRAFT initially
            total_amount=Money(0, 'GBP'),
            created_by=self.emma
        )
        
        self.assertIsNotNone(order.order_reference_id)
        self.assertEqual(order.status, OrderStatusChoices.DRAFT)
        
        # ===== STEP 5: Add products to order =====
        initial_tshirt_stock = self.tshirt_medium_blue.stock_quantity
        initial_hoodie_stock = self.hoodie_large_black.stock_quantity
        
        for variant, quantity in selected_variants:
            order_item = order.add_order_item(variant, quantity)
            self.assertIsNotNone(order_item)
            self.assertEqual(order_item.quantity, quantity)
        
        # ===== STEP 6: Verify discount application =====
        # Refresh variants to see updated prices
        tshirt_item = OrderItem.objects.get(
            order=order,
            product_variant=self.tshirt_medium_blue
        )
        hoodie_item = OrderItem.objects.get(
            order=order,
            product_variant=self.hoodie_large_black
        )
        
        # T-Shirt should have 10% student discount: £20 - 10% = £18
        self.assertEqual(tshirt_item.unit_price, Money(18, 'GBP'))
        self.assertEqual(tshirt_item.total_price, Money(18, 'GBP'))
        
        # Hoodie should be full price (no discount for non-staff): £40
        self.assertEqual(hoodie_item.unit_price, Money(40, 'GBP'))
        self.assertEqual(hoodie_item.total_price, Money(40, 'GBP'))
        
        # ===== STEP 7: Verify order total =====
        order.refresh_from_db()
        expected_total = Money(18, 'GBP') + Money(40, 'GBP')  # £58
        self.assertEqual(order.total_amount, expected_total)
        
        # ===== STEP 8: Verify stock was decremented =====
        self.tshirt_medium_blue.refresh_from_db()
        self.hoodie_large_black.refresh_from_db()
        
        self.assertEqual(
            self.tshirt_medium_blue.stock_quantity,
            initial_tshirt_stock - 1
        )
        self.assertEqual(
            self.hoodie_large_black.stock_quantity,
            initial_hoodie_stock - 1
        )

        # submit order
        order.transition_to(OrderStatusChoices.PENDING)
        self.assertEqual(order.status, OrderStatusChoices.PENDING)
        
        # ===== STEP 9: Create payment =====
        payment = Payment.objects.create(
            user=self.emma,
            event=self.event,
            method=self.payment_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.PENDING,
            target=order
        )
        
        self.assertIsNotNone(payment.payment_reference)
        self.assertEqual(payment.base_amount, expected_total)
        
        # Link payment to order
        order.payment = payment
        order.save()
        
        # ===== STEP 10: Complete order =====
        # Simulate payment completion
        payment.status = PaymentStatusChoices.COMPLETED
        payment.save()
        
        # Transition order to processing then completed
        order.transition_to(OrderStatusChoices.PROCESSING)
        order.transition_to(OrderStatusChoices.COMPLETED)
        
        self.assertEqual(order.status, OrderStatusChoices.COMPLETED)
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        
    def test_full_purchase_flow_staff_member(self):
        """
        Test complete purchase flow for an event staff member.
        Staff member gets free mug (100% discount).
        """
        
        # Mark Emma as event staff in her attendee metadata
        # (This would normally be done through event staff assignment)
        staff_context = DiscountContext(
            user=self.emma,
            event=self.event,
            metadata={
                "is_event_staff": True,
                "age": self.emma_attendee.age
            }
        )
        
        # ===== STEP 1: Create order =====
        order = Order.objects.create(
            customer=self.emma,
            attendee=self.emma_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.emma
        )
        
        # ===== STEP 2: Check mug price for staff =====
        # Calculate price with staff discount
        from apps.common.evaluator import BaseContext
        
        staff_base_context = BaseContext(
            user=self.emma,
            event=self.event,
            metadata={
                "is_event_staff": True,
                "age": self.emma_attendee.age
            }
        )
        
        mug_price_for_staff = self.mug_onesize_white.total_amount_for_context(
            staff_context
        )
        
        # Should be free (100% discount)
        self.assertEqual(mug_price_for_staff, Money(0, 'GBP'))
        
    def test_purchase_flow_with_quantity_limits(self):
        """
        Test that quantity limits are enforced.
        """
        
        order = Order.objects.create(
            attendee=self.emma_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.emma
        )
        
        # Try to purchase more than max_purchase_quantity_per_order
        with self.assertRaises(Exception) as context:
            order.add_order_item(self.tshirt_medium_blue, 10)  # Max is 5
        
        self.assertIn('exceed maximum', str(context.exception).lower())
        
    def test_purchase_flow_with_insufficient_stock(self):
        """
        Test that insufficient stock prevents purchase.
        """
        
        # Reduce stock to 2
        self.tshirt_medium_blue.stock_quantity = 2
        self.tshirt_medium_blue.save()
        
        order = Order.objects.create(
            attendee=self.emma_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.emma
        )
        
        # Try to purchase 5 when only 2 available
        with self.assertRaises(Exception) as context:
            order.add_order_item(self.tshirt_medium_blue, 5)
        
        self.assertIn('insufficient stock', str(context.exception).lower())
        
    def test_purchase_flow_with_inactive_product(self):
        """
        Test that inactive products cannot be purchased.
        """
        
        # Make product inactive
        self.tshirt.is_active = False
        self.tshirt.save()
        
        order = Order.objects.create(
            attendee=self.emma_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.emma
        )
        
        # Try to purchase inactive product
        with self.assertRaises(Exception) as context:
            order.add_order_item(self.tshirt_medium_blue, 1)
        
        self.assertIn('not eligible', str(context.exception).lower())
        
    def test_purchase_flow_order_cancellation(self):
        """
        Test order cancellation flow.
        """
        
        order = Order.objects.create(
            attendee=self.emma_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.emma,
            customer=self.emma
        )
        
        initial_stock = self.tshirt_medium_blue.stock_quantity
        
        # Add item to order
        order.add_order_item(self.tshirt_medium_blue, 2)
        
        # Verify stock was decremented
        self.tshirt_medium_blue.refresh_from_db()
        self.assertEqual(
            self.tshirt_medium_blue.stock_quantity,
            initial_stock - 2
        )
        
        # Cancel order
        order.transition_to(OrderStatusChoices.CANCELLED)
        
        self.assertEqual(order.status, OrderStatusChoices.CANCELLED)
        
        # Note: In a real system, you'd want to restore stock on cancellation
        # This would require additional logic in the Order model
        
    def test_purchase_flow_multiple_quantities(self):
        """
        Test purchasing multiple quantities of the same product.
        """
        
        order = Order.objects.create(
            attendee=self.emma_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.emma,
            customer=self.emma
        )
        
        initial_stock = self.hoodie_large_black.stock_quantity
        
        # Purchase 3 hoodies
        order_item = order.add_order_item(self.hoodie_large_black, 3)
        
        # Verify order item
        self.assertEqual(order_item.quantity, 3)
        self.assertEqual(order_item.unit_price, Money(40, 'GBP'))
        self.assertEqual(order_item.total_price, Money(120, 'GBP'))
        
        # Verify stock
        self.hoodie_large_black.refresh_from_db()
        self.assertEqual(
            self.hoodie_large_black.stock_quantity,
            initial_stock - 3
        )
        
        # Verify order total
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Money(120, 'GBP'))
        
    def test_purchase_flow_mixed_discounts(self):
        """
        Test a purchase with multiple products having different discounts.
        """
        
        # Create a new user who is both a student and event staff
        staff_student = User.objects.create_user(
            username='staffstudent',
            email='staffstudent@example.com',
            password='testpass123'
        )
        
        booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-STAFF-001',
            made_by=staff_student
        )
        
        staff_attendee = Attendee.objects.create(
            first_name='Staff',
            last_name='Student',
            user=staff_student,
            event=self.event,
            date_of_birth=date(2004, 1, 1),  # 21 years old
            relationship_to_user=AttendeeRelationship.SELF,
            booking=booking,
            defined_by=staff_student
        )
        
        order = Order.objects.create(
            attendee=staff_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=staff_student,
            customer=staff_student
        )
        
        # Mock staff context for add_order_item
        # Update attendee's pricing context to include is_event_staff
        original_pricing_context = staff_attendee.pricing_context
        
        def mock_pricing_context():
            ctx = original_pricing_context()
            ctx.metadata['is_event_staff'] = True
            return ctx
        
        # Temporarily replace the method
        staff_attendee.pricing_context = mock_pricing_context
        
        # Add items: T-shirt (10% student discount) and Mug (100% staff discount)
        tshirt_item = order.add_order_item(self.tshirt_medium_blue, 1)
        mug_item = order.add_order_item(self.mug_onesize_white, 1)
        
        # T-shirt: £20 - 10% = £18
        self.assertEqual(tshirt_item.unit_price, Money(18, 'GBP'))
        
        # Mug: £10 - 100% = £0 (free for staff)
        self.assertEqual(mug_item.unit_price, Money(0, 'GBP'))
        
        # Total: £18 + £0 = £18
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Money(18, 'GBP'))


class ProductImageIntegrationTest(TestCase):
    """Test product image functionality in a purchase flow context"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='imageuser',
            email='image@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.organisation = Organisation.objects.create(
            title='Image Test Organisation',
            created_by=self.user    
        )
        
        self.event = Event.objects.create(
            title='Image Test Event',
            display_code='ITE2025',
            display_identifier='ITE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.product = Product.objects.create(
            title='T-Shirt with Images',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
    def test_product_with_multiple_images(self):
        """Test browsing product with multiple images"""
        
        # Create test images
        main_image = self._create_test_image('main.jpg')
        secondary_image_1 = self._create_test_image('secondary1.jpg')
        secondary_image_2 = self._create_test_image('secondary2.jpg')
        
        # Add images to product
        self.product.add_product_image(main_image, is_main=True)
        self.product.add_product_image(secondary_image_1, is_main=False)
        self.product.add_product_image(secondary_image_2, is_main=False)
        
        # Verify product has images
        images = self.product.product_images
        self.assertEqual(images.count(), 3)
        
        # Verify main image
        main_images = images.filter(tag='PRODUCT_PHOTO_MAIN')
        self.assertEqual(main_images.count(), 1)
        self.assertEqual(main_images.first(), main_image)
        
        # Verify secondary images
        secondary_images = images.filter(tag='PRODUCT_PHOTO_SECONDARY')
        self.assertEqual(secondary_images.count(), 2)
        
    def _create_test_image(self, filename):
        """Helper to create a test image resource"""
        test_image_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'apps', 'products', 'tests', 'images',
            'test-tshirt.jpg'
        )
        
        if os.path.exists(test_image_path):
            with open(test_image_path, 'rb') as f:
                image_content = f.read()
        else:
            # Fallback minimal JPEG
            image_content = (
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
                b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c'
                b'\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c'
                b'\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01'
                b'\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01'
                b'\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08'
                b'\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xd2\xcf \xff\xd9'
            )
        
        image_file = SimpleUploadedFile(
            filename,
            image_content,
            content_type='image/jpeg'
        )
        
        resource = Resource.objects.create(
            name=f'Test Image {filename}',
            resource_type=ResourceTypeChoices.IMAGE,
            image=image_file,
            target_type=ContentType.objects.get_for_model(self.product),
            target_id=self.product.id,
            added_by=self.user
        )
        
        return resource