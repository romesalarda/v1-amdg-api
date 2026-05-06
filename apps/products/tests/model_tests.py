"""
Comprehensive unit tests for Product and ProductVariant models.
Tests all methods, validation, edge cases, and critical functionality.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import timedelta, date
from decimal import Decimal
from djmoney.money import Money
import os

from apps.products.models import Product, ProductVariant, ProductSizeChoices, Order, OrderStatusChoices, OrderItem, StockAuditLog
from apps.events.models import Event, EventType, EventStatusChoices
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.common.models.resource import Resource, ResourceTypeChoices
from apps.common.models.availability import AvailabilityWindow, AvailabilityTypeChoices
from apps.common.models.rules import AccessRule, BaseEventRuleChoices
from apps.payments.models import Discount, DiscountType, DiscountRule, DiscountRuleTypeChoices
from apps.payments.evaluator import DiscountContext
from apps.bookings.models import Booking
from apps.organisations.models import Organisation

User = get_user_model()


class ProductModelTest(TestCase):
    """Test the Product model in isolation"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Test Conference 2025',
            display_code='TC2025',
            display_identifier='TC2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
    def test_product_creation_with_valid_data(self):
        """Test creating a product with valid data"""
        product = Product.objects.create(
            title='Conference T-Shirt',
            description='Official conference merchandise',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.assertIsNotNone(product.id)
        self.assertIsNotNone(product.product_id)
        self.assertIsNotNone(product.display_code)
        self.assertEqual(product.title, 'Conference T-Shirt')
        self.assertEqual(product.base_amount, Money(20, 'GBP'))
        self.assertTrue(product.verified)
        self.assertTrue(product.is_active)
        
    def test_product_title_is_titlecased_on_save(self):
        """Test that product title is automatically title-cased"""
        product = Product.objects.create(
            title='conference t-shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.assertEqual(product.title, 'Conference T-Shirt')
        
    def test_product_unique_constraint_per_event(self):
        """Test that product titles must be unique per event"""
        Product.objects.create(
            title='T-Shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        with self.assertRaises(ValidationError):
            product2 = Product(
                title='T-Shirt',
                event=self.event,
                base_amount=Money(25, 'GBP'),
                added_by=self.user,
                verified=True
            )
            product2.save()
            
    def test_product_display_code_generation(self):
        """Test that display code is auto-generated"""
        product = Product.objects.create(
            title='Hoodie',
            event=self.event,
            base_amount=Money(35, 'GBP'),
            added_by=self.user
        )
        
        self.assertIsNotNone(product.display_code)
        self.assertTrue(product.display_code.startswith('PROD'))
        
    def test_product_cannot_be_active_without_verification(self):
        """Test that unverified products cannot be made active"""

        self.event.settings.product_publication_requires_verification = True
        self.event.settings.save()
        
        product = Product(
            title='Unverified Product',
            event=self.event,
            base_amount=Money(10, 'GBP'),
            added_by=self.user,
            verified=False,
            is_active=True
        )
        
        with self.assertRaises(ValidationError) as context:
            product.save()
        
        self.assertIn('cannot be published', str(context.exception).lower())
        
    def test_product_base_amount_validation(self):
        """Test that base amount cannot be negative"""
        product = Product(
            title='Invalid Product',
            event=self.event,
            base_amount=Money(-10, 'GBP'),
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            product.save()
            
    def test_product_percentage_modifier_validation(self):
        """Test that percentage modifier must be between -100 and 100"""
        product = Product(
            title='Modified Product',
            event=self.event,
            base_amount=Money(100, 'GBP'),
            percentage_modifier=Decimal('150.00'),
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            product.save()
            
    def test_product_modified_amount_calculation(self):
        """Test that modified amount is calculated correctly"""
        product = Product.objects.create(
            title='Sale Item',
            event=self.event,
            base_amount=Money(100, 'GBP'),
            percentage_modifier=Decimal('-10.00'),  # 10% discount
            added_by=self.user,
            verified=True
        )
        
        self.assertEqual(product.modified_amount, Money(90, 'GBP'))
        
    def test_product_is_free_property(self):
        """Test is_free property"""
        free_product = Product.objects.create(
            title='Free Sticker',
            event=self.event,
            base_amount=Money(0, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        paid_product = Product.objects.create(
            title='Paid Item',
            event=self.event,
            base_amount=Money(10, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.assertTrue(free_product.is_free)
        self.assertFalse(paid_product.is_free)
        
    def test_product_is_positive_property(self):
        """Test is_positive property"""
        product = Product.objects.create(
            title='Paid Item',
            event=self.event,
            base_amount=Money(10, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.assertTrue(product.is_positive)
        
    def test_product_str_and_repr(self):
        """Test string representations"""
        product = Product.objects.create(
            title='Test Product',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user
        )
        
        self.assertIn('Test Product', str(product))
        self.assertIn('Product', repr(product))
        self.assertIn(str(product.product_id), repr(product))


class ProductImageManagementTest(TestCase):
    """Test product image functionality"""
    
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
            title='Test Org',
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
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
    def _create_test_image_resource(self, filename='test.jpg'):
        """Helper to create a test image resource"""
        # Get the actual test image from the test images folder
        test_image_path = os.path.join(
            os.path.dirname(__file__),
            'images',
            'test-tshirt.jpg'
        )
        
        if os.path.exists(test_image_path):
            with open(test_image_path, 'rb') as f:
                image_content = f.read()
        else:
            # Fallback: create a minimal valid JPEG in memory
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
        
    def test_add_main_product_image(self):
        """Test adding a main product image"""
        image = self._create_test_image_resource()
        
        result = self.product.add_product_image(image, is_main=True)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.tag, 'PRODUCT_PHOTO_MAIN')
        self.assertIn(result, self.product.product_images)
        
    def test_add_secondary_product_image(self):
        """Test adding a secondary product image"""
        image = self._create_test_image_resource()
        
        result = self.product.add_product_image(image, is_main=False)
        
        self.assertEqual(result.tag, 'PRODUCT_PHOTO_SECONDARY')
        
    def test_adding_new_main_image_demotes_existing(self):
        """Test that adding a new main image demotes the old one"""
        image1 = self._create_test_image_resource('image1.jpg')
        image2 = self._create_test_image_resource('image2.jpg')
        
        self.product.add_product_image(image1, is_main=True)
        self.product.add_product_image(image2, is_main=True)
        
        # Refresh from database
        image1.refresh_from_db()
        image2.refresh_from_db()
        
        self.assertEqual(image1.tag, 'PRODUCT_PHOTO_SECONDARY')
        self.assertEqual(image2.tag, 'PRODUCT_PHOTO_MAIN')
        
    def test_product_images_property(self):
        """Test retrieving all product images"""
        image1 = self._create_test_image_resource('img1.jpg')
        image2 = self._create_test_image_resource('img2.jpg')
        
        self.product.add_product_image(image1, is_main=True)
        self.product.add_product_image(image2, is_main=False)
        
        images = self.product.product_images
        self.assertEqual(images.count(), 2)
        
    def test_remove_product_image(self):
        """Test removing a product image"""
        image = self._create_test_image_resource()
        self.product.add_product_image(image, is_main=True)
        
        self.product.remove_product_image(image)
        
        self.assertEqual(self.product.product_images.count(), 0)
        
    def test_add_non_image_resource_raises_error(self):
        """Test that adding non-image resources raises ValidationError"""
        # Create a document resource instead of image
        doc_resource = Resource.objects.create(
            name='Document',
            resource_type=ResourceTypeChoices.DOCUMENT,
            target_type=ContentType.objects.get_for_model(self.product),
            target_id=self.product.id,
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError) as context:
            self.product.add_product_image(doc_resource)
        
        self.assertIn('not an image', str(context.exception).lower())
        
    def test_remove_unassociated_image_raises_error(self):
        """Test removing an image not associated with the product"""
        other_product = Product.objects.create(
            title='Other Product',
            event=self.event,
            base_amount=Money(30, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        image = self._create_test_image_resource()
        image.target_id = other_product.id
        image.save()
        
        with self.assertRaises(ValidationError):
            self.product.remove_product_image(image)


class ProductAvailabilityTest(TestCase):
    """Test product availability window functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='availuser',
            email='avail@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Availability Test Event',
            display_code='ATE2025',
            display_identifier='ATE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.product = Product.objects.create(
            title='Limited Time Product',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
    def test_add_availability_window(self):
        """Test adding an availability window"""
        start = timezone.now()
        end = start + timedelta(days=7)
        
        window = self.product.add_availability_window(start, end)
        
        self.assertIsNotNone(window)
        self.assertEqual(window.availability_type, AvailabilityTypeChoices.PRODUCT)
        self.assertEqual(window.available_from, start)
        self.assertEqual(window.available_to, end)
        
    def test_availability_window_validation_start_before_end(self):
        """Test that start must be before end"""
        start = timezone.now()
        end = start - timedelta(days=1)  # End before start
        
        with self.assertRaises(ValidationError) as context:
            self.product.add_availability_window(start, end)
        
        self.assertIn('earlier', str(context.exception).lower())
        
    def test_availability_window_clash_detection(self):
        """Test that overlapping windows are rejected"""
        start1 = timezone.now()
        end1 = start1 + timedelta(days=7)
        
        start2 = start1 + timedelta(days=3)  # Overlaps with first window
        end2 = start2 + timedelta(days=7)
        
        self.product.add_availability_window(start1, end1)
        
        with self.assertRaises(ValidationError) as context:
            self.product.add_availability_window(start2, end2)
        
        self.assertIn('clashes', str(context.exception).lower())
        
    def test_is_purchasable_with_no_windows(self):
        """Test that product is purchasable when active and no windows defined"""
        self.assertTrue(self.product.is_purchasable)
        
    def test_is_purchasable_within_window(self):
        """Test product is purchasable within availability window"""
        now = timezone.now()
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)
        
        self.product.add_availability_window(start, end)
        
        self.assertTrue(self.product.is_purchasable)
        
    def test_is_not_purchasable_outside_window(self):
        """Test product is not purchasable outside availability window"""
        now = timezone.now()
        start = now + timedelta(days=1)
        end = now + timedelta(days=2)
        
        self.product.add_availability_window(start, end)
        
        self.assertFalse(self.product.is_purchasable)
        
    def test_is_not_purchasable_when_inactive(self):
        """Test that inactive products are not purchasable"""
        self.product.is_active = False
        self.product.save()
        
        self.assertFalse(self.product.is_purchasable)


class ProductDiscountTest(TestCase):
    """Test product discount functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='discountuser',
            email='discount@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Discount Test Event',
            display_code='DTE2025',
            display_identifier='DTE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.product = Product.objects.create(
            title='Discounted Product',
            event=self.event,
            base_amount=Money(100, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
    def test_add_percentage_discount(self):
        """Test adding a percentage discount"""
        discount = Discount.objects.create(
            name='10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.id
        )
        
        self.product.add_discount(discount)
        
        self.assertIn(discount, self.product.discounts)
        
    def test_add_fixed_amount_discount(self):
        """Test adding a fixed amount discount"""
        discount = Discount.objects.create(
            name='£15 Off',
            discount_type=DiscountType.FIXED,
            amount=Money(15, 'GBP'),
            active=True,
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.id
        )
        
        self.product.add_discount(discount)
        
        self.assertIn(discount, self.product.discounts)
        
    def test_calculate_total_discounts_percentage(self):
        """Test calculating percentage discounts"""
        discount = Discount.objects.create(
            name='10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.id
        )
        self.product.add_discount(discount)
        
        # Add a rule that always passes
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        discount_amount = self.product.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        self.assertEqual(discount_amount, Money(10, 'GBP'))
        
    def test_calculate_total_discounts_fixed(self):
        """Test calculating fixed amount discounts"""
        discount = Discount.objects.create(
            name='£20 Off',
            discount_type=DiscountType.FIXED,
            amount=Money(20, 'GBP'),
            active=True,
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.id
        )
        self.product.add_discount(discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        discount_amount = self.product.calculate_total_discounts(
            discount_base=Money(100, 'GBP'),
            context=context
        )
        
        self.assertEqual(discount_amount, Money(20, 'GBP'))
        
    def test_total_amount_for_context_with_discounts(self):
        """Test final amount calculation with discounts"""
        discount = Discount.objects.create(
            name='10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.id
        )
        self.product.add_discount(discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        final_amount = self.product.total_amount_for_context(context)
        
        self.assertEqual(final_amount, Money(90, 'GBP'))
        
    def test_discounts_capped_at_base_amount(self):
        """Test that discounts cannot exceed the base amount"""
        discount = Discount.objects.create(
            name='£150 Off',
            discount_type=DiscountType.FIXED,
            amount=Money(150, 'GBP'),  # More than base amount
            active=True,
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.id
        )
        self.product.add_discount(discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Over 18',
            discount=discount,
            value='18',
            active=True
        )
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        final_amount = self.product.total_amount_for_context(context)
        
        # Should be capped at 0, not negative
        self.assertEqual(final_amount, Money(0, 'GBP'))
        
    def test_inactive_discount_not_applied(self):
        """Test that inactive discounts are not applied"""
        discount = Discount.objects.create(
            name='10% Off',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=False,  # Inactive
            target_type=ContentType.objects.get_for_model(Product),
            target_id=self.product.id
        )
        self.product.add_discount(discount)
        
        context = DiscountContext(
            user=self.user,
            event=self.event,
            metadata={"age": 25}
        )
        
        final_amount = self.product.total_amount_for_context(context)
        
        # No discount should be applied
        self.assertEqual(final_amount, Money(100, 'GBP'))


class ProductVariantModelTest(TestCase):
    """Test ProductVariant model functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='variantuser',
            email='variant@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Variant Test Event',
            display_code='VTE2025',
            display_identifier='VTE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.product = Product.objects.create(
            title='T-Shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
    def test_variant_creation(self):
        """Test creating a product variant"""
        variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#FF0000',
            stock_quantity=50,
            max_stock_quantity=100,
            added_by=self.user,
            verified=True
        )
        
        self.assertIsNotNone(variant.id)
        self.assertIsNotNone(variant.variant_id)
        self.assertEqual(variant.size, ProductSizeChoices.MEDIUM)
        self.assertEqual(variant.color, '#FF0000')
        self.assertEqual(variant.stock_quantity, 50)
        
    def test_variant_inherits_product_base_amount(self):
        """Test that variant inherits base amount from product"""
        variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#0000FF',
            stock_quantity=30,
            added_by=self.user
        )
        
        self.assertEqual(variant.base_amount, self.product.base_amount)
        
    def test_variant_unique_constraint(self):
        """Test that variants must be unique per product-size-color combination"""
        ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#FF0000',
            stock_quantity=50,
            added_by=self.user,
            verified=True
        )
        
        with self.assertRaises(ValidationError):
            variant2 = ProductVariant(
                product=self.product,
                size=ProductSizeChoices.MEDIUM,
                color='#FF0000',
                stock_quantity=30,
                added_by=self.user,
                verified=True
            )
            variant2.save()
            
    def test_variant_stock_cannot_be_negative(self):
        """Test that stock quantity cannot be negative"""
        variant = ProductVariant(
            product=self.product,
            size=ProductSizeChoices.SMALL,
            color='#00FF00',
            stock_quantity=-10,  # Negative stock
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            variant.save()
            
    def test_variant_must_have_product(self):
        """Test that variant must be associated with a product"""
        variant = ProductVariant(
            product=None,  # No product
            size=ProductSizeChoices.SMALL,
            color='#00FF00',
            stock_quantity=10,
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            variant.save()
            
    def test_variant_color_normalized_to_uppercase(self):
        """Test that color hex codes are normalized to uppercase"""
        variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.SMALL,
            color='#aabbcc',
            stock_quantity=10,
            added_by=self.user
        )
        
        self.assertEqual(variant.color, '#AABBCC')
        
    def test_variant_size_normalized_to_uppercase(self):
        """Test that size codes are normalized to uppercase"""
        variant = ProductVariant.objects.create(
            product=self.product,
            size='md',
            color='#FFFFFF',
            stock_quantity=10,
            added_by=self.user
        )
        
        self.assertEqual(variant.size, 'MD')
        
    def test_variant_event_property(self):
        """Test that variant inherits event from product"""
        variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#000000',
            stock_quantity=20,
            added_by=self.user
        )
        
        self.assertEqual(variant.event, self.product.event)
        
    def test_variant_str_and_repr(self):
        """Test string representations"""
        variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#FF0000',
            stock_quantity=30,
            added_by=self.user
        )
        
        self.assertIn('T-Shirt', str(variant))
        self.assertIn('MD', str(variant))
        self.assertIn('ProductVariant', repr(variant))


class ProductVariantStockManagementTest(TestCase):
    """Test product variant stock management"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='stockuser',
            email='stock@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
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
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.product = Product.objects.create(
            title='Hoodie',
            event=self.event,
            base_amount=Money(40, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#000000',
            stock_quantity=100,
            max_stock_quantity=200,
            added_by=self.user
        )
        
    def test_increment_stock(self):
        """Test incrementing stock quantity"""
        initial_stock = self.variant.stock_quantity
        
        self.variant.increment_stock(10)
        self.variant.refresh_from_db()
        
        self.assertEqual(self.variant.stock_quantity, initial_stock + 10)

    def test_increment_stock_creates_audit_log(self):
        """Stock increments should always produce an immutable audit record."""
        self.variant.increment_stock(7, reason='admin_action', actor=self.user, notes='manual top-up')

        log = StockAuditLog.objects.filter(product_variant=self.variant).latest('created_at')
        self.assertEqual(log.old_quantity, 100)
        self.assertEqual(log.new_quantity, 107)
        self.assertEqual(log.change_amount, 7)
        self.assertEqual(log.change_reason, 'admin_action')
        self.assertEqual(log.actor, self.user)
        
    def test_increment_stock_with_max_limit(self):
        """Test that stock cannot exceed max_stock_quantity"""
        self.variant.stock_quantity = 195
        self.variant.save()
        
        with self.assertRaises(ValidationError) as context:
            self.variant.increment_stock(10)  # Would exceed 200 max
        
        self.assertIn('exceed maximum capacity', str(context.exception).lower())
        
    def test_increment_stock_with_zero_amount_raises_error(self):
        """Test that increment amount must be positive"""
        with self.assertRaises(ValidationError):
            self.variant.increment_stock(0)
            
    def test_increment_stock_with_negative_amount_raises_error(self):
        """Test that increment amount cannot be negative"""
        with self.assertRaises(ValidationError):
            self.variant.increment_stock(-5)
            
    def test_decrement_stock(self):
        """Test decrementing stock quantity"""
        initial_stock = self.variant.stock_quantity
        
        self.variant.decrement_stock(20)
        self.variant.refresh_from_db()
        
        self.assertEqual(self.variant.stock_quantity, initial_stock - 20)

    def test_decrement_stock_creates_audit_log(self):
        """Stock decrements should always produce an immutable audit record."""
        self.variant.decrement_stock(12, reason='initial_order_deduction', actor=self.user)

        log = StockAuditLog.objects.filter(product_variant=self.variant).latest('created_at')
        self.assertEqual(log.old_quantity, 100)
        self.assertEqual(log.new_quantity, 88)
        self.assertEqual(log.change_amount, -12)
        self.assertEqual(log.change_reason, 'initial_order_deduction')
        self.assertEqual(log.actor, self.user)
        
    def test_decrement_stock_insufficient_raises_error(self):
        """Test that stock cannot go below zero"""
        self.variant.stock_quantity = 5
        self.variant.save()
        
        with self.assertRaises(ValidationError) as context:
            self.variant.decrement_stock(10)  # More than available
        
        self.assertIn('insufficient stock', str(context.exception).lower())
        
    def test_decrement_stock_with_zero_amount_raises_error(self):
        """Test that decrement amount must be positive"""
        with self.assertRaises(ValidationError):
            self.variant.decrement_stock(0)
            
    def test_decrement_stock_with_negative_amount_raises_error(self):
        """Test that decrement amount cannot be negative"""
        with self.assertRaises(ValidationError):
            self.variant.decrement_stock(-5)
            
    def test_can_decrement_stock_returns_true_when_sufficient(self):
        """Test can_decrement_stock advisory check"""
        self.assertTrue(self.variant.can_decrement_stock(50))
        
    def test_can_decrement_stock_returns_false_when_insufficient(self):
        """Test can_decrement_stock returns False for insufficient stock"""
        self.assertFalse(self.variant.can_decrement_stock(150))
        
    def test_can_decrement_stock_returns_false_for_zero(self):
        """Test can_decrement_stock returns False for zero amount"""
        self.assertFalse(self.variant.can_decrement_stock(0))
        
    def test_can_decrement_stock_returns_false_for_negative(self):
        """Test can_decrement_stock returns False for negative amount"""
        self.assertFalse(self.variant.can_decrement_stock(-5))


class ProductVariantPurchaseTest(TestCase):
    """Test product variant purchase eligibility checks"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='purchaseuser',
            email='purchase@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Purchase Test Event',
            display_code='PTE2025',
            display_identifier='PTE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.product = Product.objects.create(
            title='Limited Edition Hoodie',
            event=self.event,
            base_amount=Money(50, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=10,
            max_purchase_quantity_per_order=3,
            added_by=self.user,
            verified=True
        )
        
        # Create a booking for the attendee
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-TEST-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            user=self.user,
            event=self.event,
            date_of_birth=date(1990, 1, 1),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
    def test_can_attendee_purchase_when_eligible(self):
        """Test that eligible attendee can purchase"""
        self.assertTrue(self.variant.can_attendee_purchase(self.attendee))
        
    def test_cannot_purchase_when_variant_inactive(self):
        """Test that attendee cannot purchase inactive variant"""
        self.variant.is_active = False
        self.variant.save()
        
        self.assertFalse(self.variant.can_attendee_purchase(self.attendee))
        
    def test_cannot_purchase_when_product_inactive(self):
        """Test that attendee cannot purchase when product is inactive"""
        self.product.is_active = False
        self.product.save()
        
        self.variant.refresh_from_db()
        self.assertFalse(self.variant.can_attendee_purchase(self.attendee))
        
    def test_get_attendee_purchase_quantity(self):
        """Test getting attendee's current purchase quantity"""
        # Initially should be 0
        quantity = self.variant.get_attendee_purchase_quantity(self.attendee)
        self.assertEqual(quantity, 0)

    def test_get_attendee_product_purchase_quantity(self):
        """Test attendee product quantity aggregation across variants."""
        second_variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#00FF00',
            stock_quantity=10,
            max_purchase_quantity_per_order=3,
            added_by=self.user,
            verified=True
        )

        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            created_by=self.user,
            total_amount=Money(0, 'GBP'),
            status=OrderStatusChoices.DRAFT,
        )
        order.add_order_item(self.variant, 1)
        order.add_order_item(second_variant, 1)

        quantity = self.variant.get_attendee_product_purchase_quantity(self.attendee)
        self.assertEqual(quantity, 2)

    def test_effective_max_purchase_quantity_uses_stricter_limit(self):
        """Test product+variant effective cap uses stricter limit."""
        self.product.max_purchase_quantity_per_order = 2
        self.product.save()

        self.assertEqual(self.variant.get_effective_max_purchase_quantity_per_attendee(), 2)

    def test_effective_max_purchase_quantity_falls_back_to_variant_when_product_unset(self):
        """Test product cap fallback when product-level cap is unset."""
        self.product.max_purchase_quantity_per_order = None
        self.product.save()

        self.assertEqual(self.variant.get_effective_max_purchase_quantity_per_attendee(), 3)
        
    def test_can_attendee_purchase_quantity_when_eligible(self):
        """Test quantity check when attendee can purchase"""
        result = self.variant.can_attendee_purchase_quantity(self.attendee, 2)
        self.assertTrue(result)
        
    def test_cannot_purchase_quantity_exceeding_max(self):
        """Test that quantity cannot exceed max_purchase_quantity_per_order"""
        result = self.variant.can_attendee_purchase_quantity(self.attendee, 5, raise_exception=False)
        self.assertFalse(result)

    def test_product_cap_is_enforced_across_variants(self):
        """Test product-level cap across all variants for an attendee."""
        self.product.max_purchase_quantity_per_order = 1
        self.product.save()

        second_variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#00AA00',
            stock_quantity=10,
            max_purchase_quantity_per_order=3,
            added_by=self.user,
            verified=True
        )

        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            created_by=self.user,
            total_amount=Money(0, 'GBP'),
            status=OrderStatusChoices.DRAFT,
        )
        order.add_order_item(self.variant, 1)

        result = second_variant.can_attendee_purchase_quantity(self.attendee, 1, raise_exception=False)
        self.assertFalse(result)

    def test_draft_orders_count_towards_purchase_limit(self):
        """Test draft order quantities are counted towards attendee purchase cap."""
        self.product.max_purchase_quantity_per_order = 2
        self.product.save()

        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            created_by=self.user,
            total_amount=Money(0, 'GBP'),
            status=OrderStatusChoices.DRAFT,
        )
        order.add_order_item(self.variant, 2)

        result = self.variant.can_attendee_purchase_quantity(self.attendee, 1, raise_exception=False)
        self.assertFalse(result)
        
    def test_cannot_purchase_quantity_exceeding_max_raises_exception(self):
        """Test that exceeding max raises exception when raise_exception=True"""
        with self.assertRaises(ValidationError) as context:
            self.variant.can_attendee_purchase_quantity(self.attendee, 5, raise_exception=True)
        
        self.assertIn('exceed maximum', str(context.exception).lower())
        
    def test_cannot_purchase_quantity_exceeding_stock(self):
        """Test that quantity cannot exceed available stock"""
        result = self.variant.can_attendee_purchase_quantity(self.attendee, 15, raise_exception=False)
        self.assertFalse(result)
        
    def test_cannot_purchase_zero_quantity(self):
        """Test that zero quantity returns False"""
        result = self.variant.can_attendee_purchase_quantity(self.attendee, 0)
        self.assertFalse(result)
        
    def test_cannot_purchase_negative_quantity(self):
        """Test that negative quantity returns False"""
        result = self.variant.can_attendee_purchase_quantity(self.attendee, -1)
        self.assertFalse(result)
        
    def test_get_attendee_final_price(self):
        """Test getting final price for attendee"""
        final_price = self.variant.get_attendee_final_price(self.attendee)
        
        self.assertIsInstance(final_price, Money)
        self.assertEqual(final_price, Money(50, 'GBP'))
        
    def test_get_attendee_final_price_with_discount(self):
        """Test final price calculation with discount applied"""
        # Add a discount for young attendees
        discount = Discount.objects.create(
            name='Youth Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('20.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(ProductVariant),
            target_id=self.variant.id
        )
        self.variant.add_discount(discount)
        
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_LT,
            name='Under 25',
            discount=discount,
            value='25',
            active=True
        )
        
        # Update attendee age in metadata
        from datetime import date
        from dateutil.relativedelta import relativedelta
        self.attendee.date_of_birth = date.today() - relativedelta(years=20)
        self.attendee.save()
        
        final_price = self.variant.get_attendee_final_price(self.attendee)
        
        # Should be 50 - 20% = 40
        self.assertEqual(final_price, Money(40, 'GBP'))


class OrderModelTest(TestCase):
    """Test the Order model in isolation"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='orderuser',
            email='order@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Order Test Event',
            display_code='OTE2025',
            display_identifier='OTE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-ORDER-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Order',
            last_name='Tester',
            user=self.user,
            event=self.event,
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user,
            date_of_birth=timezone.now().date() - timedelta(days=8000)
        )
        
    def test_order_creation(self):
        """Test creating an order"""
        from apps.products.models import Order, OrderStatusChoices
        
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        self.assertIsNotNone(order.id)
        self.assertIsNotNone(order.order_id)
        self.assertIsNotNone(order.order_reference_id)
        self.assertEqual(order.status, OrderStatusChoices.DRAFT)
        self.assertEqual(order.total_amount, Money(0, 'GBP'))
        
    def test_order_reference_id_generation(self):
        """Test that order reference ID is auto-generated"""
        from apps.products.models import Order
        
        order = Order.objects.create(
            customer=self.user,
            attendee=self.attendee,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        self.assertIsNotNone(order.order_reference_id)
        self.assertTrue(order.order_reference_id.startswith('ORD'))
        
    def test_order_must_have_customer_or_attendee(self):
        """Test that order must be associated with customer or attendee"""
        from apps.products.models import Order
        
        order = Order(
            customer=None,
            attendee=None,  # Neither customer nor attendee
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            order.clean()
            order.save()
            
    def test_order_total_amount_cannot_be_negative(self):
        """Test that total amount cannot be negative"""
        from apps.products.models import Order
        
        order = Order(
            customer=self.user,
            attendee=self.attendee,
            total_amount=Money(-50, 'GBP'),
            created_by=self.user
        )
        with self.assertRaises(ValidationError):
            order.clean()
            order.save()
            
    def test_order_event_property(self):
        """Test that order inherits event from attendee"""
        from apps.products.models import Order
        
        order = Order.objects.create(
            attendee=self.attendee,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        self.assertEqual(order.event, self.attendee.event)
        
    def test_order_status_transitions_valid(self):
        """Test valid status transitions"""
        from apps.products.models import Order, OrderStatusChoices
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        # Draft -> Pending (valid)
        self.assertTrue(order.can_transition_to(OrderStatusChoices.PENDING))
        order.transition_to(OrderStatusChoices.PENDING)
        self.assertEqual(order.status, OrderStatusChoices.PENDING)
        
        # Pending -> Processing (valid)
        self.assertTrue(order.can_transition_to(OrderStatusChoices.PROCESSING))
        order.transition_to(OrderStatusChoices.PROCESSING)
        self.assertEqual(order.status, OrderStatusChoices.PROCESSING)
        
        # Processing -> Completed (valid)
        self.assertTrue(order.can_transition_to(OrderStatusChoices.COMPLETED))
        order.transition_to(OrderStatusChoices.COMPLETED)
        self.assertEqual(order.status, OrderStatusChoices.COMPLETED)
        
    def test_order_status_transitions_invalid(self):
        """Test invalid status transitions"""
        from apps.products.models import Order, OrderStatusChoices
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        # Draft -> Completed (invalid - must go through pending/processing)
        self.assertFalse(order.can_transition_to(OrderStatusChoices.COMPLETED))
        
        with self.assertRaises(ValidationError):
            order.transition_to(OrderStatusChoices.COMPLETED)
            
    def test_order_cannot_transition_from_completed(self):
        """Test that completed orders can only be refunded"""
        from apps.products.models import Order, OrderStatusChoices
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.COMPLETED,
            total_amount=Money(100, 'GBP'),
            created_by=self.user
        )
        
        # Completed can only go to refunded
        self.assertTrue(order.can_transition_to(OrderStatusChoices.REFUNDED))
        self.assertFalse(order.can_transition_to(OrderStatusChoices.PENDING))
        self.assertFalse(order.can_transition_to(OrderStatusChoices.PROCESSING))
        
    def test_order_can_add_products_only_in_draft_status(self):
        """Test that products can only be added in draft status"""
        from apps.products.models import Order, OrderStatusChoices
        
        draft_order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        completed_order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.COMPLETED,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        self.assertTrue(draft_order.can_add_products)
        self.assertFalse(completed_order.can_add_products)
        
    def test_get_total_amount_calculation(self):
        """Test total amount calculation from order items"""
        from apps.products.models import Order, OrderStatusChoices, OrderItem, Product, ProductVariant
        
        product = Product.objects.create(
            title='Test Product',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        variant = ProductVariant.objects.create(
            product=product,
            size=ProductSizeChoices.MEDIUM,
            color='#FF0000',
            stock_quantity=100,
            added_by=self.user
        )
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        # Add order items manually (bypassing add_order_item logic for isolated test)
        OrderItem.objects.create(
            order=order,
            product_variant=variant,
            quantity=2,
            unit_price=Money(25, 'GBP'),
            total_price=Money(50, 'GBP')
        )
        
        OrderItem.objects.create(
            order=order,
            product_variant=variant,
            quantity=1,
            unit_price=Money(25, 'GBP'),
            total_price=Money(25, 'GBP')
        )
        
        total = order.get_total_amount()
        self.assertEqual(total, Money(75, 'GBP'))
        
    def test_recalculate_total_amount(self):
        """Test recalculating and updating order total"""
        from apps.products.models import Order, OrderStatusChoices, OrderItem, Product, ProductVariant
        
        product = Product.objects.create(
            title='Test Product',
            event=self.event,
            base_amount=Money(30, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        variant = ProductVariant.objects.create(
            product=product,
            size=ProductSizeChoices.LARGE,
            color='#0000FF',
            stock_quantity=50,
            added_by=self.user
        )
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        OrderItem.objects.create(
            order=order,
            product_variant=variant,
            quantity=3,
            unit_price=Money(30, 'GBP'), # after discount
            total_price=Money(90, 'GBP') # 3 * 30
        )
        
        order.recalculate_total_amount()
        
        self.assertEqual(order.total_amount, Money(90, 'GBP'))


class OrderItemManagementTest(TestCase):
    """Test adding and managing order items"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='orderitemuser',
            email='orderitem@example.com',
            password='testpass123'
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='OrderItem Test Event',
            display_code='OITE2025',
            display_identifier='OITE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-ITEM-001',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='Item',
            last_name='Tester',
            user=self.user,
            event=self.event,
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user,
            date_of_birth=timezone.now().date() - timedelta(days=9000)
        )
        
        self.product = Product.objects.create(
            title='Conference Merchandise',
            event=self.event,
            base_amount=Money(40, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#00FF00',
            stock_quantity=50,
            max_purchase_quantity_per_order=10,
            added_by=self.user,
            verified=True
        )
        
    def test_add_order_item_to_order(self):
        """Test adding an order item to an order"""
        from apps.products.models import Order, OrderStatusChoices
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user,
            customer=self.user
        )
        order.full_clean()
        order.save()
        
        initial_stock = self.variant.stock_quantity
        
        order_item = order.add_order_item(self.variant, 2)
        
        self.assertIsNotNone(order_item)
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.unit_price, Money(40, 'GBP'))
        self.assertEqual(order_item.total_price, Money(80, 'GBP'))
        
        # Check stock was decremented
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock - 2)
        
        # Check order total was updated
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Money(80, 'GBP'))
        
    def test_add_order_item_checks_eligibility(self):
        """Test that adding items checks attendee eligibility"""
        from apps.products.models import Order, OrderStatusChoices
        
        # Make variant inactive
        self.variant.is_active = False
        self.variant.save()
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError) as context:
            order.add_order_item(self.variant, 1)
        
        self.assertIn('not eligible', str(context.exception).lower())
        
    def test_add_order_item_checks_stock(self):
        """Test that adding items checks stock availability"""
        from apps.products.models import Order, OrderStatusChoices
        
        self.variant.stock_quantity = 2
        self.variant.save()
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError) as context:
            order.add_order_item(self.variant, 5)  # More than available
        
        self.assertIn('insufficient stock', str(context.exception).lower())
        
    def test_add_order_item_with_zero_quantity_raises_error(self):
        """Test that zero quantity raises error"""
        from apps.products.models import Order, OrderStatusChoices
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            order.add_order_item(self.variant, 0)
            
    def test_add_order_item_to_non_draft_order_raises_error(self):
        """Test that items can only be added to draft orders"""
        from apps.products.models import Order, OrderStatusChoices
        
        order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.COMPLETED,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError) as context:
            order.add_order_item(self.variant, 1)
        
        self.assertIn('not in \'draft\' status', str(context.exception).lower())


class OrderItemModelTest(TestCase):
    """Test the OrderItem model in isolation"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='itemuser',
            email='item@example.com',
            password='testpass123'
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )

        self.organisation = Organisation.objects.create(
            title='Test Org',
            created_by=self.user
        )
        
        self.event = Event.objects.create(
            title='Item Test Event',
            display_code='ITE2025',
            display_identifier='ITE2025CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.booking = Booking.objects.create(
            event=self.event,
            booking_reference='BKG-ITEM-002',
            made_by=self.user
        )
        
        self.attendee = Attendee.objects.create(
            first_name='OrderItem',
            last_name='User',
            user=self.user,
            event=self.event,
            date_of_birth=date(1992, 3, 15),
            relationship_to_user=AttendeeRelationship.SELF,
            booking=self.booking,
            defined_by=self.user
        )
        
        self.product = Product.objects.create(
            title='Item Product',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            added_by=self.user,
            verified=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#AAAAAA',
            stock_quantity=100,
            added_by=self.user
        )
        
        from apps.products.models import Order, OrderStatusChoices
        self.order = Order.objects.create(
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.user
        )
        
    def test_order_item_creation(self):
        """Test creating an order item"""
        from apps.products.models import OrderItem
        
        item = OrderItem.objects.create(
            order=self.order,
            product_variant=self.variant,
            quantity=3,
            unit_price=Money(25, 'GBP'),
            total_price=Money(75, 'GBP')
        )
        
        self.assertIsNotNone(item.id)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.unit_price, Money(25, 'GBP'))
        self.assertEqual(item.total_price, Money(75, 'GBP'))
        
    def test_order_item_quantity_must_be_positive(self):
        """Test that quantity must be at least 1"""
        from apps.products.models import OrderItem
        
        item = OrderItem(
            order=self.order,
            product_variant=self.variant,
            quantity=0,
            unit_price=Money(25, 'GBP'),
            total_price=Money(0, 'GBP')
        )
        
        with self.assertRaises(ValidationError):
            item.save()
            
    def test_order_item_unit_price_cannot_be_negative(self):
        """Test that unit price cannot be negative"""
        from apps.products.models import OrderItem
        
        item = OrderItem(
            order=self.order,
            product_variant=self.variant,
            quantity=1,
            unit_price=Money(-10, 'GBP'),
            total_price=Money(-10, 'GBP')
        )
        
        with self.assertRaises(ValidationError):
            item.save()
            
    def test_order_item_total_price_validation(self):
        """Test that total price must equal unit price * quantity"""
        from apps.products.models import OrderItem
        
        item = OrderItem(
            order=self.order,
            product_variant=self.variant,
            quantity=3,
            unit_price=Money(25, 'GBP'),
            total_price=Money(50, 'GBP')  # Incorrect: should be 75
        )
        
        with self.assertRaises(ValidationError):
            item.save()
            
    def test_order_item_str_and_repr(self):
        """Test string representations"""
        from apps.products.models import OrderItem
        
        item = OrderItem.objects.create(
            order=self.order,
            product_variant=self.variant,
            quantity=2,
            unit_price=Money(25, 'GBP'),
            total_price=Money(50, 'GBP')
        )
        
        self.assertIn('OrderItem', str(item))
        self.assertIn('Item Product', str(item))
        self.assertIn('OrderItem', repr(item))
