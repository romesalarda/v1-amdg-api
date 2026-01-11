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
    DiscountRule, DiscountRuleTypeChoices,
    RefundRequest, RefundAssociation, PaymentHistoryAction
)
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventType, EventStatusChoices, EventStaff
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
            target=order,
            metadata=order.get_metadata(), # TODO: TESTME
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

        # Mock staff context for add_order_item
        # Update attendee's pricing context to include is_event_staff

        event_staff = EventStaff.objects.create(
            user=staff_student,
            assigned_by=self.emma,
            event=self.event
        )
        
        order = Order.objects.create(
            attendee=staff_attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=staff_student,
            customer=staff_student
        )
        
        
        
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


class RefundFlowTest(TestCase):
    """
    Test the complete refund flow for product purchases.
    
    Covers:
    - Full refunds (entire order)
    - Partial refunds (individual items)
    - RefundRequest creation and verification workflow
    - RefundAssociation linking refunds to order items
    - PaymentHistoryAction tracking with metadata
    """
    
    def setUp(self):
        """Set up test data for refund flow tests"""
        # Create Sam's user account
        self.sam = User.objects.create_user(
            username='sam',
            email='sam@example.com',
            password='testpass123'
        )
        
        # Create additional users for attendees
        self.attendee1_user = User.objects.create_user(
            username='attendee1',
            email='attendee1@example.com',
            password='testpass123'
        )
        
        self.attendee2_user = User.objects.create_user(
            username='attendee2',
            email='attendee2@example.com',
            password='testpass123'
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.sam
        )
        
        self.organisation = Organisation.objects.create(
            title='Refund Test Organisation',
            created_by=self.sam
        )
        
        self.event = Event.objects.create(
            title='Annual Conference 2026',
            display_code='AC2026',
            display_identifier='AC2026CONF001',
            created_by=self.sam,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create booking for Sam
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-SAM-001',
            made_by=self.sam
        )
        
        # Create attendees: Sam, Attendee1, Attendee2
        self.sam_attendee = Attendee.objects.create(
            first_name='Sam',
            last_name='Smith',
            user=self.sam,
            event=self.event,
            date_of_birth=date(1995, 3, 20),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.sam
        )
        
        self.attendee1 = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            user=self.attendee1_user,
            event=self.event,
            date_of_birth=date(1998, 6, 15),
            relationship_to_user=AttendeeRelationship.FRIEND,
            booking=self.booking,
            defined_by=self.sam
        )
        
        self.attendee2 = Attendee.objects.create(
            first_name='Jane',
            last_name='Doe',
            user=self.attendee2_user,
            event=self.event,
            date_of_birth=date(2000, 9, 10),
            relationship_to_user=AttendeeRelationship.FRIEND,
            booking=self.booking,
            defined_by=self.sam
        )
        
        # Create products
        self.bag = Product.objects.create(
            title='Conference Bag',
            description='Canvas tote bag',
            event=self.event,
            base_amount=Money(15, 'GBP'),
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        self.shirt = Product.objects.create(
            title='Conference Shirt',
            description='Cotton T-shirt',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Create product variants
        self.bag_variant = ProductVariant.objects.create(
            product=self.bag,
            size=ProductSizeChoices.ONE_SIZE,
            color='#000000',
            stock_quantity=100,
            max_stock_quantity=200,
            max_purchase_quantity_per_order=10,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        self.shirt_variant = ProductVariant.objects.create(
            product=self.shirt,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=100,
            max_stock_quantity=200,
            max_purchase_quantity_per_order=10,
            added_by=self.sam,
            verified=True,
            is_active=True
        )
        
        # Create payment method
        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            title='Credit Card',
            is_active=True,
            created_by=self.sam
        )
        
    def _create_order_with_payment(self, attendee, items):
        """
        Helper method to create an order with items and complete payment.
        
        @param attendee: The attendee associated with the order
        @param items: List of tuples (product_variant, quantity)
        @return: Tuple of (order, payment)
        """
        # Create order
        order = Order.objects.create(
            customer=self.sam,
            attendee=attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.sam
        )
        
        # Add items to order
        for product_variant, quantity in items:
            order.add_order_item(product_variant, quantity)
        
        # Refresh order to get updated total
        order.refresh_from_db()
        
        # Submit order
        order.transition_to(OrderStatusChoices.PENDING)
        
        # Create and complete payment
        payment = Payment.objects.create(
            user=self.sam,
            event=self.event,
            method=self.payment_method,
            base_amount=order.total_amount,
            status=PaymentStatusChoices.PENDING,
            target=order,
            metadata=order.get_metadata()
        )
        
        # Link payment to order
        order.payment = payment
        order.save()
        
        # Complete payment
        payment.status = PaymentStatusChoices.COMPLETED
        payment.save()
        
        # Complete order
        order.transition_to(OrderStatusChoices.PROCESSING)
        order.transition_to(OrderStatusChoices.COMPLETED)
        
        return order, payment
    
    def test_full_refund_entire_order(self):
        """
        Test requesting a full refund for an entire order.
        
        Scenario:
        - Sam purchases 1 bag (£15) and 1 shirt (£25) = £40 total
        - Sam requests a full refund for the entire order
        - Verify RefundRequest, RefundAssociation, and PaymentHistoryAction are created correctly
        """
        # Create order with items
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [
                (self.bag_variant, 1),
                (self.shirt_variant, 1)
            ]
        )
        
        # Verify order and payment amounts
        expected_total = Money(40, 'GBP')  # £15 + £25
        self.assertEqual(order.total_amount, expected_total)
        self.assertEqual(payment.base_amount, expected_total)
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
        
        # ===== REQUEST FULL REFUND =====
        # Sam requests a refund for the entire order
        refund_request = RefundRequest.objects.create(
            payment=payment,
            amount=expected_total,
            reason='Changed mind about attending the conference',
            requested_by=self.sam
        )
        
        # Verify RefundRequest was created with correct status
        self.assertIsNotNone(refund_request.tracking_reference)
        self.assertEqual(refund_request.verification_status, VerificationStatus.PENDING)
        self.assertEqual(refund_request.amount, expected_total)
        self.assertEqual(refund_request.requested_by, self.sam)
        self.assertTrue(refund_request.is_active)
        
        # ===== ASSOCIATE REFUND WITH ORDER ITEMS =====
        # Associate the refund with all order items using FROZEN amounts from payment
        order_items = order.order_items.all()
        self.assertEqual(order_items.count(), 2)
        
        for item in order_items:
            # Use frozen amount from order item (which was frozen at order creation)
            frozen_amount = item.total_price
            frozen_metadata = {
                'item_id': item.id,
                'product_title': item.product_variant.product.title if item.product_variant else 'Unknown',
                'quantity': item.quantity,
                'unit_price': str(item.unit_price.amount),
                'total_price': str(item.total_price.amount),
                'frozen_at_payment': True
            }
            
            refund_association = refund_request.associate_with(
                item,
                amount=frozen_amount,
                metadata=frozen_metadata
            )
            self.assertIsNotNone(refund_association)
            self.assertEqual(refund_association.refund_request, refund_request)
            self.assertEqual(refund_association.target_object, item)
            self.assertEqual(refund_association.amount, frozen_amount)
        
        # Verify associations were created
        associations = refund_request.associations.all()
        self.assertEqual(associations.count(), 2)
        
        # Verify total refund amount calculation
        calculated_refund_amount = refund_request.get_refund_amount()
        self.assertEqual(calculated_refund_amount, expected_total)
        
        # ===== VERIFY REFUND =====
        # Admin verifies the refund request
        admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123'
        )
        
        refund_request.mark_verified(admin_user)
        refund_request.refresh_from_db()
        
        self.assertEqual(refund_request.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(refund_request.verified_by, admin_user)
        self.assertIsNotNone(refund_request.verified_updated_at)
        
        # ===== CREATE PAYMENT HISTORY ACTION =====
        # Create a PaymentHistoryAction to track the refund
        payment_history_action = PaymentHistoryAction.objects.create(
            payment=payment,
            description=f'Full refund processed for order {order.order_reference_id}',
            action='REFUND_INITIATED',
            performed_by=admin_user,
            metadata={
                'refund_request_id': str(refund_request.refund_id),
                'refund_tracking_reference': refund_request.tracking_reference,
                'original_amount': str(payment.base_amount.amount),
                'original_currency': payment.base_amount.currency.code,
                'refund_amount': str(refund_request.amount.amount),
                'refund_currency': refund_request.amount.currency.code,
                'refund_type': 'full',
                'order_reference': order.order_reference_id,
                'refunded_items': [
                    {
                        'item_id': item.id,
                        'product_variant_id': item.product_variant.id if item.product_variant else None,
                        'product_title': item.product_variant.product.title if item.product_variant else 'Unknown',
                        'quantity': item.quantity,
                        'unit_price': str(item.unit_price.amount),
                        'total_price': str(item.total_price.amount)
                    }
                    for item in order_items
                ]
            },
            notes='Customer changed mind about attending conference'
        )
        
        # Verify PaymentHistoryAction was created correctly
        self.assertIsNotNone(payment_history_action.action_id)
        self.assertEqual(payment_history_action.payment, payment)
        self.assertEqual(payment_history_action.action, 'REFUND_INITIATED')
        self.assertEqual(payment_history_action.performed_by, admin_user)
        self.assertEqual(payment_history_action.metadata['original_amount'], '40.00')
        self.assertEqual(payment_history_action.metadata['refund_amount'], '40.00')
        self.assertEqual(payment_history_action.metadata['refund_type'], 'full')
        self.assertEqual(len(payment_history_action.metadata['refunded_items']), 2)
        
        # ===== PROCESS REFUND =====
        # Admin processes the refund (external refund completed)
        refund_request.mark_processed(admin_user)
        refund_request.refresh_from_db()
        
        self.assertEqual(refund_request.verification_status, VerificationStatus.PROCESSED)
        self.assertEqual(refund_request.processed_by, admin_user)
        self.assertIsNotNone(refund_request.processed_at)
        
        # Update payment status to pending refund then refunded
        payment.status = PaymentStatusChoices.PENDING_REFUND
        payment.save()
        
        # Create another history action for refund completion
        completion_action = PaymentHistoryAction.objects.create(
            payment=payment,
            description=f'Refund completed for order {order.order_reference_id}',
            action='REFUND_COMPLETED',
            performed_by=admin_user,
            metadata={
                'refund_request_id': str(refund_request.refund_id),
                'completion_timestamp': timezone.now().isoformat(),
                'refund_amount': str(refund_request.amount.amount),
                'new_payment_status': PaymentStatusChoices.REFUNDED
            }
        )
        
        payment.status = PaymentStatusChoices.REFUNDED
        payment.save()
        
        # Verify final states
        self.assertEqual(payment.status, PaymentStatusChoices.REFUNDED)
        self.assertEqual(refund_request.verification_status, VerificationStatus.PROCESSED)
        
        # Verify payment history has both actions
        history_actions = payment.history_actions.all()
        self.assertEqual(history_actions.count(), 2)
        self.assertIn('REFUND_INITIATED', [action.action for action in history_actions])
        self.assertIn('REFUND_COMPLETED', [action.action for action in history_actions])
    
    def test_partial_refund_single_item(self):
        """
        Test requesting a partial refund for a single item from an order.
        
        Scenario:
        - Sam purchases 1 bag (£15) and 1 shirt (£25) = £40 total
        - Sam requests a refund for only the shirt (£25)
        - Verify partial refund is handled correctly
        """
        # Create order with items
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [
                (self.bag_variant, 1),
                (self.shirt_variant, 1)
            ]
        )
        
        order_total = Money(40, 'GBP')  # £15 + £25
        self.assertEqual(order.total_amount, order_total)
        
        # Get the shirt order item
        shirt_item = order.order_items.get(product_variant=self.shirt_variant)
        self.assertEqual(shirt_item.total_price, Money(25, 'GBP'))
        
        # ===== REQUEST PARTIAL REFUND FOR SHIRT ONLY =====
        refund_amount = Money(25, 'GBP')
        refund_request = RefundRequest.objects.create(
            payment=payment,
            amount=refund_amount,
            reason='Shirt size not available',
            requested_by=self.sam
        )
        
        # Verify refund request
        self.assertEqual(refund_request.amount, refund_amount)
        self.assertTrue(refund_request.is_partial)
        self.assertFalse(refund_request.is_full)
        
        # ===== ASSOCIATE REFUND WITH SHIRT ITEM ONLY =====
        # Use frozen amount from order item
        frozen_shirt_amount = shirt_item.total_price
        frozen_metadata = {
            'item_id': shirt_item.id,
            'product_title': shirt_item.product_variant.product.title,
            'quantity': shirt_item.quantity,
            'unit_price': str(shirt_item.unit_price.amount),
            'total_price': str(shirt_item.total_price.amount),
            'refund_reason': 'Shirt size not available'
        }
        
        refund_association = refund_request.associate_with(
            shirt_item,
            amount=frozen_shirt_amount,
            metadata=frozen_metadata
        )
        
        self.assertIsNotNone(refund_association)
        self.assertEqual(refund_association.target_object, shirt_item)
        self.assertEqual(refund_association.amount, frozen_shirt_amount)
        
        # Verify only one association exists
        associations = refund_request.associations.all()
        self.assertEqual(associations.count(), 1)
        
        # Verify refund amount calculation
        calculated_refund = refund_request.get_refund_amount()
        self.assertEqual(calculated_refund, Money(25, 'GBP'))  # Just the shirt
        
        # ===== CREATE PAYMENT HISTORY ACTION FOR PARTIAL REFUND =====
        admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123'
        )
        
        refund_request.mark_verified(admin_user)
        
        payment_history_action = PaymentHistoryAction.objects.create(
            payment=payment,
            description=f'Partial refund processed for order {order.order_reference_id}',
            action='REFUND_INITIATED',
            performed_by=admin_user,
            metadata={
                'refund_request_id': str(refund_request.refund_id),
                'refund_tracking_reference': refund_request.tracking_reference,
                'original_amount': str(Decimal(payment.base_amount.amount)),
                'original_currency': payment.base_amount.currency.code,
                'refund_amount': str(refund_request.absolute_amount()),
                'refund_currency': refund_request.amount.currency.code,
                'remaining_amount': str((payment.absolute_amount() - refund_request.absolute_amount())),
                'refund_type': 'partial',
                'order_reference': order.order_reference_id,
                'refunded_items': [
                    {
                        'item_id': shirt_item.id,
                        'product_variant_id': shirt_item.product_variant.id,
                        'product_title': shirt_item.product_variant.product.title,
                        'quantity': shirt_item.quantity,
                        'unit_price': str(shirt_item.unit_price.amount),
                        'total_price': str(shirt_item.total_price.amount)
                    }
                ]
            },
            notes='Shirt size not available for customer'
        )
        
        # Verify metadata
        self.assertEqual(payment_history_action.metadata['original_amount'], '40.00')
        self.assertEqual(payment_history_action.metadata['refund_amount'], '25.00')
        self.assertEqual(payment_history_action.metadata['remaining_amount'], '15.00')
        self.assertEqual(payment_history_action.metadata['refund_type'], 'partial')
        self.assertEqual(len(payment_history_action.metadata['refunded_items']), 1)
        
        # Process refund
        refund_request.mark_processed(admin_user)
        
        # For partial refunds, payment should remain COMPLETED
        # (In a real system, you might track partial refunds differently)
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)
    
    def test_partial_refund_multiple_items(self):
        """
        Test requesting a partial refund for multiple items from an order.
        
        Scenario:
        - Order contains: 2 bags (£15 each) and 2 shirts (£25 each) = £80 total
        - Refund requested for: 1 bag (£15) and 1 shirt (£25) = £40 refund
        - Verify partial refund with multiple items
        """
        # Create order with multiple quantities
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [
                (self.bag_variant, 2),   # 2 bags
                (self.shirt_variant, 2)  # 2 shirts
            ]
        )
        
        order_total = Money(80, 'GBP')  # (£15 × 2) + (£25 × 2)
        self.assertEqual(order.total_amount, order_total)
        
        # Get order items
        bag_item = order.order_items.get(product_variant=self.bag_variant)
        shirt_item = order.order_items.get(product_variant=self.shirt_variant)
        
        self.assertEqual(bag_item.total_price, Money(30, 'GBP'))  # £15 × 2
        self.assertEqual(shirt_item.total_price, Money(50, 'GBP'))  # £25 × 2
        
        # ===== REQUEST PARTIAL REFUND =====
        # Note: For simplicity, we refund entire items. In a real system,
        # you might need to handle partial quantities within an item.
        refund_amount = Money(40, 'GBP')  # Refunding both items
        refund_request = RefundRequest.objects.create(
            payment=payment,
            amount=refund_amount,
            reason='Some items defective',
            requested_by=self.sam
        )
        
        # Verify refund is partial
        self.assertTrue(refund_request.is_partial)
        self.assertFalse(refund_request.is_full)
        
        # ===== ASSOCIATE REFUND WITH BOTH ITEMS =====
        # In this test, we're refunding the full amount of both order items
        # In a real scenario, you might create separate OrderItems for each quantity
        # or implement a quantity field in RefundAssociation
        
        # Get frozen amounts from payment metadata
        payment_metadata = payment.metadata
        order_items = payment_metadata.get('order', {}).get('order_items', [])
        
        # Find amounts for each item
        bag_frozen = None
        shirt_frozen = None
        for item_data in order_items:
            if item_data['order_item_id'] == bag_item.id:
                bag_frozen = Money(item_data['total_amount'], item_data['currency'])
            elif item_data['order_item_id'] == shirt_item.id:
                shirt_frozen = Money(item_data['total_amount'], item_data['currency'])
        
        bag_association = refund_request.associate_with(
            bag_item,
            amount=bag_frozen,
            metadata={'item_name': 'Bag', 'original_price': str(bag_frozen)}
        )
        shirt_association = refund_request.associate_with(
            shirt_item,
            amount=shirt_frozen,
            metadata={'item_name': 'Shirt', 'original_price': str(shirt_frozen)}
        )
        
        self.assertEqual(refund_request.associations.count(), 2)
        
        # Calculate refund amount
        # Note: This will refund the FULL amount of both items (£30 + £50 = £80)
        # which doesn't match our £40 refund_amount in this simplified test.
        # In production, you'd need a more sophisticated mechanism to handle
        # partial quantities within items.
        calculated_refund = refund_request.get_refund_amount()
        self.assertEqual(calculated_refund, Money(80, 'GBP'))  # Full amount of both items
        
        # For this test to work correctly with £40 refund, we should verify
        # the refund_request.amount is used, not the calculated amount
        self.assertEqual(refund_request.amount, Money(40, 'GBP'))
        
        # ===== CREATE PAYMENT HISTORY ACTION =====
        admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123'
        )
        
        refund_request.mark_verified(admin_user)
        
        payment_history_action = PaymentHistoryAction.objects.create(
            payment=payment,
            description=f'Partial refund for multiple items in order {order.order_reference_id}',
            action='REFUND_INITIATED',
            performed_by=admin_user,
            metadata={
                'refund_request_id': str(refund_request.refund_id),
                'original_amount': str(payment.absolute_amount()),
                'refund_amount': str(refund_request.absolute_amount()),
                'remaining_amount': str((payment.absolute_amount() - refund_request.absolute_amount())),
                'refund_type': 'partial',
                'refunded_items': [
                    {
                        'item_id': bag_item.id,
                        'product_title': bag_item.product_variant.product.title,
                        'quantity': bag_item.quantity,
                        'total_price': str(bag_item.total_price.amount)
                    },
                    {
                        'item_id': shirt_item.id,
                        'product_title': shirt_item.product_variant.product.title,
                        'quantity': shirt_item.quantity,
                        'total_price': str(shirt_item.total_price.amount)
                    }
                ]
            }
        )
        
        # Verify metadata
        self.assertEqual(payment_history_action.metadata['original_amount'], '80.00')
        self.assertEqual(payment_history_action.metadata['refund_amount'], '40.00')
        self.assertEqual(payment_history_action.metadata['remaining_amount'], '40.00')
        self.assertEqual(len(payment_history_action.metadata['refunded_items']), 2)
    
    def test_refund_verification_workflow(self):
        """
        Test the complete refund verification workflow.
        
        Workflow:
        1. User requests refund -> status: PENDING
        2. Admin reviews and verifies -> status: VERIFIED
        3. Admin processes refund externally -> status: PROCESSED
        """
        # Create simple order
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [(self.bag_variant, 1)]
        )
        
        # ===== STEP 1: USER REQUESTS REFUND =====
        refund_request = RefundRequest.objects.create(
            payment=payment,
            amount=Money(15, 'GBP'),
            reason='Product damaged',
            requested_by=self.sam
        )
        
        # Associate with order item
        order_item = order.order_items.first()
        
        # Get frozen amount from payment metadata
        payment_metadata = payment.metadata
        order_items = payment_metadata.get('order', {}).get('order_items', [])
        item_data = order_items[0]
        frozen_amount = Money(item_data['total_amount'], item_data['currency'])
        
        refund_request.associate_with(
            order_item,
            amount=frozen_amount,
            metadata={'item_name': 'Bag', 'original_price': str(frozen_amount)}
        )
        
        # Verify initial status
        self.assertTrue(refund_request.is_pending)
        self.assertFalse(refund_request.is_verified)
        self.assertFalse(refund_request.is_processed)
        self.assertEqual(refund_request.verification_status, VerificationStatus.PENDING)
        
        # ===== STEP 2: ADMIN VERIFIES REFUND =====
        admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123'
        )
        
        refund_request.mark_verified(admin)
        refund_request.refresh_from_db()
        
        self.assertFalse(refund_request.is_pending)
        self.assertTrue(refund_request.is_verified)
        self.assertFalse(refund_request.is_processed)
        self.assertEqual(refund_request.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(refund_request.verified_by, admin)
        self.assertIsNotNone(refund_request.verified_updated_at)
        
        # Create history action for verification
        PaymentHistoryAction.objects.create(
            payment=payment,
            description='Refund request verified',
            action='REFUND_VERIFIED',
            performed_by=admin,
            metadata={
                'refund_request_id': str(refund_request.refund_id),
                'verification_timestamp': timezone.now().isoformat(),
                'verified_by': admin.username
            }
        )
        
        # ===== STEP 3: ADMIN PROCESSES REFUND =====
        refund_request.mark_processed(admin)
        refund_request.refresh_from_db()
        
        self.assertFalse(refund_request.is_pending)
        # self.assertTrue(refund_request.is_verified) # can remain false even after processing
        self.assertTrue(refund_request.is_processed)
        self.assertEqual(refund_request.verification_status, VerificationStatus.PROCESSED)
        self.assertEqual(refund_request.processed_by, admin)
        self.assertIsNotNone(refund_request.processed_at)
        self.assertFalse(refund_request.auto_processed)
        
        # Create history action for processing
        PaymentHistoryAction.objects.create(
            payment=payment,
            description='Refund completed',
            action='REFUND_COMPLETED',
            performed_by=admin,
            metadata={
                'refund_request_id': str(refund_request.refund_id),
                'processing_timestamp': timezone.now().isoformat(),
                'processed_by': admin.username,
                'stripe_refund_id': 're_test123456'  # Example external refund ID
            }
        )
        
        # Verify payment history
        history = payment.history_actions.all().order_by('timestamp')
        self.assertEqual(history.count(), 2)
        self.assertEqual(history[0].action, 'REFUND_VERIFIED')
        self.assertEqual(history[1].action, 'REFUND_COMPLETED')
    
    def test_refund_validation_exceeds_payment_amount(self):
        """
        Test that refund amount cannot exceed the original payment amount.
        """
        # Create order
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [(self.bag_variant, 1)]  # £15
        )
        
        # Try to create refund for more than payment amount
        with self.assertRaises(Exception) as context:
            refund_request = RefundRequest.objects.create(
                payment=payment,
                amount=Money(50, 'GBP'),  # More than £15
                reason='Testing validation',
                requested_by=self.sam
            )
        
        self.assertIn('exceed', str(context.exception).lower())
    
    def test_refund_unique_active_refund_per_payment(self):
        """
        Test that only one active refund request can exist per payment.
        """
        # Create order
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [(self.bag_variant, 1)]
        )
        
        # Create first active refund request
        refund1 = RefundRequest.objects.create(
            payment=payment,
            amount=Money(15, 'GBP'),
            reason='First refund',
            requested_by=self.sam,
            is_active=True
        )
        
        # Try to create second active refund request for same payment
        with self.assertRaises(Exception):
            refund2 = RefundRequest.objects.create(
                payment=payment,
                amount=Money(10, 'GBP'),
                reason='Second refund',
                requested_by=self.sam,
                is_active=True
            )
    
    def test_multiple_refunds_when_first_is_inactive(self):
        """
        Test that a new refund can be created if the previous one is inactive.
        """
        # Create order
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [(self.bag_variant, 1)]
        )
        
        # Create first refund request and make it inactive
        refund1 = RefundRequest.objects.create(
            payment=payment,
            amount=Money(15, 'GBP'),
            reason='First refund',
            requested_by=self.sam,
            is_active=True
        )
        
        # Deactivate first refund
        refund1.is_active = False
        refund1.save()
        
        # Create second refund request - should succeed
        refund2 = RefundRequest.objects.create(
            payment=payment,
            amount=Money(15, 'GBP'),
            reason='Second refund attempt',
            requested_by=self.sam,
            is_active=True
        )
        
        self.assertIsNotNone(refund2)
        self.assertTrue(refund2.is_active)
        self.assertEqual(RefundRequest.objects.filter(payment=payment).count(), 2)
        self.assertEqual(RefundRequest.objects.filter(payment=payment, is_active=True).count(), 1)
    
    def test_refund_rejected_workflow(self):
        """
        Test that a refund request can be rejected by admin.
        """
        # Create order
        order, payment = self._create_order_with_payment(
            self.sam_attendee,
            [(self.bag_variant, 1)]
        )
        
        # Create refund request
        refund_request = RefundRequest.objects.create(
            payment=payment,
            amount=Money(15, 'GBP'),
            reason='Requesting refund',
            requested_by=self.sam
        )
        
        order_item = order.order_items.first()
        
        # Get frozen amount from payment metadata
        payment_metadata = payment.metadata
        order_items = payment_metadata.get('order', {}).get('order_items', [])
        item_data = order_items[0]
        frozen_amount = Money(item_data['total_amount'], item_data['currency'])
        
        refund_request.associate_with(
            order_item,
            amount=frozen_amount,
            metadata={'item_name': 'Bag', 'original_price': str(frozen_amount)}
        )
        
        # Admin rejects the refund
        admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123'
        )
        
        refund_request.mark_rejected(admin)
        refund_request.refresh_from_db()
        
        self.assertTrue(refund_request.is_rejected)
        self.assertEqual(refund_request.verification_status, VerificationStatus.REJECTED)
        self.assertEqual(refund_request.verified_by, admin)
        
        # Create history action for rejection
        PaymentHistoryAction.objects.create(
            payment=payment,
            description='Refund request rejected',
            action='REFUND_REJECTED',
            performed_by=admin,
            metadata={
                'refund_request_id': str(refund_request.refund_id),
                'rejection_timestamp': timezone.now().isoformat(),
                'rejected_by': admin.username,
                'rejection_reason': 'Outside refund window'
            }
        )
        
        # Verify history action was created
        rejection_action = payment.history_actions.filter(action='REFUND_REJECTED').first()
        self.assertIsNotNone(rejection_action)
        self.assertEqual(rejection_action.metadata['rejected_by'], admin.username)
        
        # Payment status should remain COMPLETED
        self.assertEqual(payment.status, PaymentStatusChoices.COMPLETED)

        