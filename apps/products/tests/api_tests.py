"""
Comprehensive API tests for the products app.

Tests all endpoints, permissions, serialization, filtering, nested routing,
and business logic for products, variants, orders, and categories.

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import date, timedelta
from djmoney.money import Money
from decimal import Decimal
import uuid

from apps.products.models import (
    Product, ProductVariant, ProductSizeChoices,
    Order, OrderItem, OrderStatusChoices,
    ProductCategory, EventProductCategory
)
from apps.events.models import Event, EventType, EventStatusChoices, EventRole, EventRoleAssignment, EventRoleCategoryChoices
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.common.models import Resource

User = get_user_model()


class ProductCategoryAPITestCase(APITestCase):
    """Test suite for ProductCategory API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        # Create category
        self.category = ProductCategory.objects.create(
            name='Clothing',
            description='Apparel and clothing items'
        )
        
        self.client = APIClient()
    
    def test_list_categories_authenticated(self):
        """Authenticated users should see all categories."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/products/categories/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_categories_unauthenticated(self):
        """Unauthenticated users should not access categories."""
        response = self.client.get('/api/products/categories/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_retrieve_category_detail(self):
        """Test retrieving category details."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/products/categories/{self.category.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Clothing')
        self.assertIn('_links', response.data)
    
    def test_create_category_as_admin(self):
        """Admin should be able to create categories."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'name': 'Electronics',
            'description': 'Electronic items'
        }
        response = self.client.post('/api/products/categories/', data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ProductCategory.objects.filter(name='Electronics').count(), 1)
    
    def test_create_category_as_regular_user(self):
        """Regular users should not be able to create global categories."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'name': 'Books',
            'description': 'Book items'
        }
        response = self.client.post('/api/products/categories/', data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_update_category_as_admin(self):
        """Admin should be able to update categories."""
        self.client.force_authenticate(user=self.admin_user)
        data = {'description': 'Updated description'}
        response = self.client.patch(f'/api/products/categories/{self.category.id}/', data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.category.refresh_from_db()
        self.assertEqual(self.category.description, 'Updated description')
    
    def test_delete_category_as_admin(self):
        """Admin should be able to delete categories."""
        category = ProductCategory.objects.create(name='Temporary')
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(f'/api/products/categories/{category.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ProductCategory.objects.filter(id=category.id).exists())
    
    def test_category_name_search(self):
        """Test category search filtering."""
        ProductCategory.objects.create(name='Accessories', description='Accessory items')
        self.client.force_authenticate(user=self.regular_user)
        
        response = self.client.get('/api/products/categories/?name__contains=cloth')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)


class ProductAPITestCase(APITestCase):
    """Test suite for Product API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        self.other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )
        
        # Create organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        # Create event
        event_type = EventType.objects.create(
            title='Conference',
            code='CONF'
        )
        self.event = Event.objects.create(
            title='Test Event',
            display_code='PROD001',
            display_identifier='PROD001CONF001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create administrative role
        admin_role, _ = EventRole.objects.get_or_create(
            code='EVADM',
            defaults={
                'name': 'Event Admin',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE
            }
        )
        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.regular_user,
            role=admin_role
        )
        
        # Create categories
        self.category1 = ProductCategory.objects.create(name='T-Shirts')
        self.category2 = ProductCategory.objects.create(name='Accessories')
        
        # Create product
        self.product = Product.objects.create(
            title='Conference T-Shirt',
            description='Official conference merchandise',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            verified=True,
            is_active=True,
            added_by=self.admin_user
        )
        
        # Associate category
        EventProductCategory.objects.create(
            event=self.event,
            category=self.category1,
            product=self.product
        )
        
        self.client = APIClient()
    
    def test_list_products_authenticated(self):
        """Authenticated users should see active products."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/products/list/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_products_unauthenticated(self):
        """Unauthenticated users should not access products."""
        response = self.client.get('/api/products/list/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_retrieve_product_detail(self):
        """Test retrieving detailed product information."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/products/list/{self.product.product_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Conference T-Shirt')
        self.assertIn('_links', response.data)
        self.assertIn('images', response.data)
        self.assertIn('variants', response.data)
    
    def test_create_product_as_event_admin(self):
        """Event admin should be able to create products."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'title': 'Event Hoodie',
            'description': 'Comfortable hoodie',
            'event': self.event.id,
            'base_amount': '35.00',
            'base_amount_currency': 'GBP',
            'verified': False,
            'is_active': False,
        }
        response = self.client.post('/api/products/list/', data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Product.objects.filter(title='Event Hoodie').count(), 1)

        created_product = Product.objects.get(title='Event Hoodie')
        mapping_response = self.client.post('/api/products/event-categories/', {
            'event': self.event.id,
            'category': self.category1.id,
            'product': created_product.id,
        })

        self.assertEqual(mapping_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            EventProductCategory.objects.filter(
                event=self.event,
                category=self.category1,
                product=created_product,
            ).exists()
        )
    
    def test_create_product_with_main_image(self):
        """Test creating product with main image upload."""
        self.client.force_authenticate(user=self.regular_user)
        
        # Create a simple test image
        from io import BytesIO
        from PIL import Image
        
        image = Image.new('RGB', (100, 100), color='red')
        image_file = BytesIO()
        image.save(image_file, 'PNG')
        image_file.seek(0)
        image_file.name = 'test_image.png'
        
        data = {
            'title': 'Product With Image',
            'description': 'Test product',
            'event': self.event.id,
            'base_amount': '30.00',
            'base_amount_currency': 'GBP',
            'verified': True,
            'is_active': False,
            'main_image': image_file
        }
        response = self.client.post('/api/products/list/', data, format='multipart')
            
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Title gets titlecased in Product.clean(), so look for the titlecased version
        product = Product.objects.get(title='Product With Image')
        
        # Verify main image was added
        main_images = product.resources.filter(tag='PRODUCT_PHOTO_MAIN')
        self.assertEqual(main_images.count(), 1)
        self.assertTrue(main_images.first().image)
    
    def test_create_product_with_multiple_images(self):
        """Test creating product with main and additional images."""
        self.client.force_authenticate(user=self.regular_user)
        
        # Create test images
        from io import BytesIO
        from PIL import Image
        
        # Main image
        main_image = Image.new('RGB', (100, 100), color='red')
        main_image_file = BytesIO()
        main_image.save(main_image_file, 'PNG')
        main_image_file.seek(0)
        main_image_file.name = 'main_image.png'
        
        # Additional images
        additional_image1 = Image.new('RGB', (100, 100), color='blue')
        additional_image_file1 = BytesIO()
        additional_image1.save(additional_image_file1, 'PNG')
        additional_image_file1.seek(0)
        additional_image_file1.name = 'additional_image1.png'
        
        additional_image2 = Image.new('RGB', (100, 100), color='green')
        additional_image_file2 = BytesIO()
        additional_image2.save(additional_image_file2, 'PNG')
        additional_image_file2.seek(0)
        additional_image_file2.name = 'additional_image2.png'
        
        data = {
            'title': 'Product With Multiple Images',
            'description': 'Test product',
            'event': self.event.id,
            'base_amount': '40.00',
            'base_amount_currency': 'GBP',
            'verified': True,
            'is_active': False,
            'main_image': main_image_file,
            'additional_images': [additional_image_file1, additional_image_file2]
        }
        response = self.client.post('/api/products/list/', data, format='multipart')
            
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Title gets titlecased in Product.clean()
        product = Product.objects.get(title='Product With Multiple Images')
        
        # Verify images were added
        main_images = product.resources.filter(tag='PRODUCT_PHOTO_MAIN')
        additional_images = product.resources.filter(tag='PRODUCT_PHOTO_SECONDARY')
        
        self.assertEqual(main_images.count(), 1)
        self.assertEqual(additional_images.count(), 2)
    
    def test_create_product_as_non_admin(self):
        """Non-admin users should not be able to create products."""
        self.client.force_authenticate(user=self.other_user)
        data = {
            'title': 'Unauthorized Product',
            'event': self.event.id,
            'base_amount': '10.00',
            'base_amount_currency': 'GBP',
        }
        response = self.client.post('/api/products/list/', data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_update_product(self):
        """Event admin should be able to update products."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'title': 'Updated T-Shirt',
            'description': 'New description'
        }
        response = self.client.patch(f'/api/products/list/{self.product.product_id}/', data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.title, 'Updated T-Shirt')
    
    def test_toggle_product_active(self):
        """Test toggling product active status."""
        self.client.force_authenticate(user=self.regular_user)
        initial_status = self.product.is_active
        
        response = self.client.post(f'/api/products/list/{self.product.product_id}/toggle-active/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.is_active, not initial_status)
    
    def test_filter_products_by_category(self):
        """Test filtering products by category."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/products/list/?category={self.category1.id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_products_by_price_range(self):
        """Test filtering products by price range."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/products/list/?min_price=10&max_price=25')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for product in response.data['results']:
            price = float(product['base_amount'].split()[0])
            self.assertTrue(10 <= price <= 25)
    
    def test_filter_products_by_event(self):
        """Test filtering products by event."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/products/list/?event={self.event.id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for product in response.data['results']:
            self.assertEqual(product['event'], self.event.id)
    
    def test_search_products(self):
        """Test full-text search on products."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/products/list/?search=Conference')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_add_image_to_product(self):
        """Test adding image to existing product via add_image action."""
        self.client.force_authenticate(user=self.regular_user)
        
        # Create a test image
        from io import BytesIO
        from PIL import Image
        
        image = Image.new('RGB', (100, 100), color='yellow')
        image_file = BytesIO()
        image.save(image_file, 'PNG')
        image_file.seek(0)
        image_file.name = 'add_test_image.png'
        
        data = {
            'image': image_file,
            'is_main': 'false'
        }
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/add-image/',
            data,
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('resource_id', response.data)
        
        # Verify image was added
        self.product.refresh_from_db()
        images = self.product.resources.filter(tag__in=['PRODUCT_PHOTO_MAIN', 'PRODUCT_PHOTO_SECONDARY'])
        self.assertGreater(images.count(), 0)
    
    def test_add_main_image_replaces_existing(self):
        """Test that adding main image replaces existing main image."""
        self.client.force_authenticate(user=self.regular_user)
        
        from io import BytesIO
        from PIL import Image
        
        # Add first main image
        image1 = Image.new('RGB', (100, 100), color='red')
        image_file1 = BytesIO()
        image1.save(image_file1, 'PNG')
        image_file1.seek(0)
        image_file1.name = 'main_image1.png'
        
        self.client.post(
            f'/api/products/list/{self.product.product_id}/add-image/',
            {'image': image_file1, 'is_main': 'true'},
            format='multipart'
        )
        
        # Add second main image
        image2 = Image.new('RGB', (100, 100), color='blue')
        image_file2 = BytesIO()
        image2.save(image_file2, 'PNG')
        image_file2.seek(0)
        image_file2.name = 'main_image2.png'
        
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/add-image/',
            {'image': image_file2, 'is_main': 'true'},
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify only one main image exists
        self.product.refresh_from_db()
        main_images = self.product.resources.filter(tag='PRODUCT_PHOTO_MAIN')
        self.assertEqual(main_images.count(), 1)
    
    def test_add_image_without_file_fails(self):
        """Test that add_image requires an image file."""
        self.client.force_authenticate(user=self.regular_user)
        
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/add-image/',
            {'is_main': 'false'},
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('image', response.data)
    
    def test_update_product_with_new_main_image(self):
        """Test updating product with new main image."""
        self.client.force_authenticate(user=self.regular_user)
        
        from io import BytesIO
        from PIL import Image
        
        image = Image.new('RGB', (100, 100), color='purple')
        image_file = BytesIO()
        image.save(image_file, 'PNG')
        image_file.seek(0)
        image_file.name = 'updated_main_image.png'
        
        data = {
            'title': 'Updated Product Title',
            'main_image': image_file
        }
        response = self.client.patch(
            f'/api/products/list/{self.product.product_id}/',
            data,
            format='multipart'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.title, 'Updated Product Title')
        
        # Verify main image was updated
        main_images = self.product.resources.filter(tag='PRODUCT_PHOTO_MAIN')
        self.assertGreater(main_images.count(), 0)


class ProductVariantAPITestCase(APITestCase):
    """Test suite for ProductVariant API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        # Create organisation and event
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='VAR001',
            display_identifier='VAR001CONF001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create administrative role
        admin_role, _ = EventRole.objects.get_or_create(
            code='EVADM',
            defaults={
                'name': 'Event Admin',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE
            }
        )
        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.regular_user,
            role=admin_role
        )
        
        # Create product
        self.product = Product.objects.create(
            title='T-Shirt',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            verified=True,
            is_active=True,
            added_by=self.admin_user
        )
        
        # Create variant
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=50,
            max_stock_quantity=100,
            max_purchase_quantity_per_order=5,
            verified=True,
            is_active=True,
            added_by=self.admin_user
        )
        
        self.client = APIClient()
    
    def test_list_variants_nested_route(self):
        """Test listing variants through nested product route."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/products/list/{self.product.product_id}/variants/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_variant_detail_nested(self):
        """Test retrieving variant details through nested route."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/products/list/{self.product.product_id}/variants/{self.variant.variant_id}/'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['size'], 'MD')
        self.assertEqual(response.data['stock_quantity'], 50)
    
    def test_create_variant_as_event_admin(self):
        """Event admin should be able to create variants."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'product': self.product.id,
            'size': ProductSizeChoices.LARGE,
            'color': '#FF0000',
            'stock_quantity': 30,
            'max_purchase_quantity_per_order': 3,
            'verified': True,
            'is_active': True
        }
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/', 
            data
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            ProductVariant.objects.filter(
                product=self.product, 
                size=ProductSizeChoices.LARGE
            ).count(), 
            1
        )
    
    def test_create_duplicate_variant(self):
        """Should not allow duplicate variants (same product, size, color)."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'product': self.product.id,
            'size': ProductSizeChoices.MEDIUM,
            'color': '#0000FF',
            'stock_quantity': 10,
            'max_purchase_quantity_per_order': 2
        }
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/', 
            data
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_increment_stock(self):
        """Test incrementing variant stock."""
        self.client.force_authenticate(user=self.regular_user)
        initial_stock = self.variant.stock_quantity
        
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/{self.variant.variant_id}/increment-stock/',
            {'amount': 10}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock + 10)
    
    def test_decrement_stock(self):
        """Test decrementing variant stock."""
        self.client.force_authenticate(user=self.regular_user)
        initial_stock = self.variant.stock_quantity
        
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/{self.variant.variant_id}/decrement-stock/',
            {'amount': 5}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock - 5)
    
    def test_decrement_stock_insufficient(self):
        """Should not allow decrementing more than available stock."""
        self.client.force_authenticate(user=self.regular_user)
        
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/{self.variant.variant_id}/decrement-stock/',
            {'amount': 1000}
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_set_stock(self):
        """Test setting stock to specific value."""
        self.client.force_authenticate(user=self.regular_user)
        
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/{self.variant.variant_id}/set-stock/',
            {'stock_quantity': 75}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 75)
    
    def test_toggle_variant_active(self):
        """Test toggling variant active status."""
        self.client.force_authenticate(user=self.regular_user)
        initial_status = self.variant.is_active
        
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/{self.variant.variant_id}/toggle-active/'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.is_active, not initial_status)
    
    def test_filter_variants_by_size(self):
        """Test filtering variants by size."""
        ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.SMALL,
            color='#00FF00',
            stock_quantity=20,
            verified=True,
            is_active=True,
            added_by=self.admin_user
        )
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/products/list/{self.product.product_id}/variants/?size=SM'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['size'], 'SM')
    
    def test_filter_variants_in_stock(self):
        """Test filtering variants that are in stock."""
        ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.LARGE,
            color='#000000',
            stock_quantity=0,
            verified=True,
            is_active=True,
            added_by=self.admin_user
        )
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/products/list/{self.product.product_id}/variants/?in_stock=true'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for variant in response.data['results']:
            self.assertGreater(variant['stock_quantity'], 0)


class OrderAPITestCase(APITestCase):
    """Test suite for Order API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.customer_user = User.objects.create_user(
            username='customer',
            email='customer@test.com',
            password='testpass123'
        )
        
        self.other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )
        
        # Create organisation and event
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='ORD001',
            display_identifier='ORD001CONF001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Create attendee
        self.attendee = Attendee.objects.create(
            user=self.customer_user,
            event=self.event,
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            date_of_birth=date(1990, 1, 1),
            relationship_to_user=AttendeeRelationship.SELF,
            defined_by=self.customer_user
        )
        
        # Create product and variant
        self.product = Product.objects.create(
            title='Event T-Shirt',
            event=self.event,
            base_amount=Money(25, 'GBP'),
            verified=True,
            is_active=True
        )
        
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#0000FF',
            stock_quantity=100,
            max_purchase_quantity_per_order=5,
            verified=True,
            is_active=True,
            added_by=self.admin_user
        )
        
        # Create order
        self.order = Order.objects.create(
            customer=self.customer_user,
            attendee=self.attendee,
            status=OrderStatusChoices.DRAFT,
            total_amount=Money(0, 'GBP'),
            created_by=self.customer_user
        )
        
        self.client = APIClient()
    
    def test_list_orders_as_customer(self):
        """Customer should see their own orders."""
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get('/api/products/orders/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_list_orders_as_admin(self):
        """Admin should see all orders."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/products/orders/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_orders_as_other_user(self):
        """Other users should not see orders they don't own."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get('/api/products/orders/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)
    
    def test_retrieve_order_detail(self):
        """Test retrieving detailed order information."""
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(f'/api/products/orders/{self.order.order_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], OrderStatusChoices.DRAFT)
        self.assertIn('order_items', response.data)
    
    def test_create_order_with_items(self):
        """Test creating an order with items."""
        self.client.force_authenticate(user=self.customer_user)
        data = {
            'customer': self.customer_user.id,
            'attendee': self.attendee.id,
            'items': [
                {
                    'product_variant_id': str(self.variant.variant_id),
                    'quantity': 2
                }
            ]
        }
        response = self.client.post('/api/products/orders/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify order was created with correct total
        order = Order.objects.get(order_id=response.data['order_id'])
        self.assertEqual(order.order_items.count(), 1)
        self.assertEqual(order.total_amount.amount, Decimal('50.00'))  # 2 * 25
        
        # Verify stock was decremented
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 98)
    
    def test_create_order_without_items(self):
        """Should not allow creating order without items."""
        self.client.force_authenticate(user=self.customer_user)
        data = {
            'customer': self.customer_user.id,
            'attendee': self.attendee.id,
            'items': []
        }
        response = self.client.post('/api/products/orders/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_add_item_to_order(self):
        """Test adding item to draft order."""
        self.client.force_authenticate(user=self.customer_user)
        data = {
            'product_variant_id': str(self.variant.variant_id),
            'quantity': 3
        }
        response = self.client.post(
            f'/api/products/orders/{self.order.order_id}/add-item/',
            data
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_items.count(), 1)
        # Verify the total was recalculated (3 * £25 = £75)
        self.assertEqual(self.order.total_amount, Money(75, 'GBP'))
    
    def test_submit_order(self):
        """Test submitting an order."""
        # Add item first
        self.order.add_order_item(self.variant, 2)
        
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.post(f'/api/products/orders/{self.order.order_id}/submit/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatusChoices.PENDING)
    
    def test_submit_order_without_items(self):
        """Should not allow submitting order without items."""
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.post(f'/api/products/orders/{self.order.order_id}/submit/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_cancel_order(self):
        """Test cancelling an order."""
        # Capture initial stock before adding items
        initial_stock = self.variant.stock_quantity
        
        # Add item and submit
        self.order.add_order_item(self.variant, 2)
        self.order.submit()
        
        # Verify stock was decremented after adding items
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock - 2)
        
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.post(f'/api/products/orders/{self.order.order_id}/cancel/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatusChoices.CANCELLED)
        
        # Verify stock was restored to original amount
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, initial_stock)
    
    def test_update_order_status(self):
        """Test updating order status through patch."""
        self.order.add_order_item(self.variant, 1)
        self.order.submit()
        
        self.client.force_authenticate(user=self.admin_user)
        data = {'status': OrderStatusChoices.PROCESSING}
        response = self.client.patch(
            f'/api/products/orders/{self.order.order_id}/',
            data
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatusChoices.PROCESSING)
    
    def test_filter_orders_by_status(self):
        """Test filtering orders by status."""
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(f'/api/products/orders/?status={OrderStatusChoices.DRAFT}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for order in response.data['results']:
            self.assertEqual(order['status'], OrderStatusChoices.DRAFT)
    
    def test_filter_orders_by_date_range(self):
        """Test filtering orders by date range."""
        self.client.force_authenticate(user=self.customer_user)
        today = timezone.now().date()
        response = self.client.get(f'/api/products/orders/?created_date={today}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_search_orders(self):
        """Test full-text search on orders."""
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get('/api/products/orders/?search=john')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class PermissionsTestCase(APITestCase):
    """Test suite for permission classes."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.event_admin_user = User.objects.create_user(
            username='event_admin',
            email='event_admin@test.com',
            password='testpass123'
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        # Create organisation and event
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='PERM001',
            display_identifier='PERM001CONF001',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        # Assign event admin role
        admin_role, _ = EventRole.objects.get_or_create(
            code='EVADM',
            defaults={
                'name': 'Event Admin',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE
            }
        )
        EventRoleAssignment.objects.create(
            event=self.event,
            user=self.event_admin_user,
            role=admin_role
        )
        
        self.product = Product.objects.create(
            title='Test Product',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            verified=True,
            is_active=True
        )
        
        self.client = APIClient()
    
    def test_superuser_has_full_access(self):
        """Superuser should have access to all operations."""
        self.client.force_authenticate(user=self.admin_user)
        
        # Can create product
        data = {
            'title': 'New Product',
            'event': self.event.id,
            'base_amount': '30.00',
            'base_amount_currency': 'GBP',
        }
        response = self.client.post('/api/products/list/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Can update product
        response = self.client.patch(
            f'/api/products/list/{self.product.product_id}/',
            {'title': 'Updated'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Can delete product
        response = self.client.delete(f'/api/products/list/{self.product.product_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
    
    def test_event_admin_can_manage_event_products(self):
        """Event admin should be able to manage their event's products."""
        self.client.force_authenticate(user=self.event_admin_user)
        
        # Can create product for their event
        data = {
            'title': 'Event Product',
            'event': self.event.id,
            'base_amount': '25.00',
            'base_amount_currency': 'GBP',
        }
        response = self.client.post('/api/products/list/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Can update product
        response = self.client.patch(
            f'/api/products/list/{self.product.product_id}/',
            {'description': 'Updated description'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_regular_user_read_only_access(self):
        """Regular users should have read-only access."""
        self.client.force_authenticate(user=self.regular_user)
        
        # Can read products
        response = self.client.get('/api/products/list/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Cannot create products
        data = {
            'title': 'Unauthorized Product',
            'event': self.event.id,
            'base_amount': '20.00',
            'base_amount_currency': 'GBP',
        }
        response = self.client.post('/api/products/list/', data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Cannot update products
        response = self.client.patch(
            f'/api/products/list/{self.product.product_id}/',
            {'title': 'Updated'}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_stock_operations_require_admin(self):
        """Stock operations should require admin permissions."""
        variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductSizeChoices.MEDIUM,
            color='#000000',
            stock_quantity=50,
            verified=True,
            is_active=True,
            added_by=self.admin_user
        )
        
        # Regular user cannot manage stock
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/{variant.variant_id}/increment-stock/',
            {'amount': 10}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Event admin can manage stock
        self.client.force_authenticate(user=self.event_admin_user)
        response = self.client.post(
            f'/api/products/list/{self.product.product_id}/variants/{variant.variant_id}/increment-stock/',
            {'amount': 10}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class HATEOASTestCase(APITestCase):
    """Test suite for HATEOAS link generation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123'
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.user
        )
        
        event_type = EventType.objects.create(title='Conference', code='CONF')
        self.event = Event.objects.create(
            title='Test Event',
            display_code='HATEOAS001',
            display_identifier='HATEOAS001CONF001',
            created_by=self.user,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.product = Product.objects.create(
            title='Test Product',
            event=self.event,
            base_amount=Money(20, 'GBP'),
            verified=True,
            is_active=True
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_product_list_has_links(self):
        """Product list response should include HATEOAS links."""
        response = self.client.get('/api/products/list/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        product = response.data['results'][0]
        self.assertIn('_links', product)
        self.assertIn('self', product['_links'])
        self.assertIn('event', product['_links'])
        self.assertIn('variants', product['_links'])
    
    def test_product_detail_has_links(self):
        """Product detail response should include comprehensive HATEOAS links."""
        response = self.client.get(f'/api/products/list/{self.product.product_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        links = response.data['_links']
        self.assertIn('self', links)
        self.assertIn('event', links)
        self.assertIn('variants', links)
    
    def test_category_has_links(self):
        """Category response should include HATEOAS links."""
        category = ProductCategory.objects.create(name='Test Category')
        response = self.client.get(f'/api/products/categories/{category.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('products', response.data['_links'])
