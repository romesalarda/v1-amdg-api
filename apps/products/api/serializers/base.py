"""
Production-grade serializers for the products app.

Provides comprehensive serializers for product management with HATEOAS support,
extensive validation, image handling, timezone handling, and separation of concerns (list/detail/create/update).

Serializers:
    ProductCategory: ProductCategorySerializer, ProductCategoryCreateUpdateSerializer
    EventProductCategory: EventProductCategorySerializer, EventProductCategoryCreateUpdateSerializer
    Product: ProductListSerializer, ProductDetailSerializer, ProductCreateSerializer, ProductUpdateSerializer
    ProductVariant: ProductVariantListSerializer, ProductVariantDetailSerializer, ProductVariantCreateUpdateSerializer
    Order: OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer, OrderUpdateSerializer
    OrderItem: OrderItemSerializer, OrderItemCreateSerializer

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer, inline_serializer
from drf_spectacular.types import OpenApiTypes
from djmoney.money import Money
from djmoney.contrib.django_rest_framework import MoneyField
from decimal import Decimal
from typing import Dict, Any, Optional
import pytz

from apps.products.models import (
    Product, ProductVariant, ProductSizeChoices,
    Order, OrderItem, OrderStatusChoices,
    ProductCategory, EventProductCategory
)
from apps.events.models import Event
from apps.common.models import Resource
from apps.common.api.serializers import AvailabilityWindowSerializer

User = get_user_model()


# ============================================================================
# UTILITY FUNCTIONS FOR TIMEZONE AND IMAGE HANDLING
# ============================================================================

def localize_datetime_to_event_timezone(dt, event):
    """Convert datetime to event's timezone."""
    if not dt:
        return None
    
    if not event or not hasattr(event, 'settings'):
        return dt
    
    # Get event timezone from settings
    event_tz_str = event.settings.default_timezone if hasattr(event, 'settings') else 'UTC'
    event_tz = pytz.timezone(str(event_tz_str))
    
    # If datetime is naive, make it aware in UTC first
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    
    # Convert to event timezone
    return dt.astimezone(event_tz)


class EventTimezoneField(serializers.DateTimeField):
    """Custom datetime field that returns datetimes in event timezone."""
    
    def to_representation(self, value):
        """Convert datetime to event timezone for serialization."""
        if not value:
            return None
        
        # Get event from context
        event = self.context.get('event')
        if event:
            value = localize_datetime_to_event_timezone(value, event)
        
        return super().to_representation(value)


# ============================================================================
# PRODUCT CATEGORY SERIALIZERS
# ============================================================================

class ProductCategorySerializer(serializers.ModelSerializer):
    """List/Detail serializer for ProductCategory with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    product_count = serializers.IntegerField(source='products.count', read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = ProductCategory
        fields = (
            'id', 'name', 'description', 'product_count',
            'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'product_count')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'products': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/products/categories/{obj.id}/"),
            'products': request.build_absolute_uri(f"/api/products/list/?category={obj.id}"),
        }


class ProductCategoryCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for ProductCategory with validation."""
    
    class Meta:
        model = ProductCategory
        fields = ('name', 'description')
    
    def validate_name(self, value):
        """Ensure category name is unique."""
        if not value or not value.strip():
            raise serializers.ValidationError("Category name cannot be empty.")
        
        # Check for duplicate names (case-insensitive)
        queryset = ProductCategory.objects.filter(name__iexact=value.strip())
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise serializers.ValidationError("A category with this name already exists.")
        
        return value.strip()


# ============================================================================
# EVENT PRODUCT CATEGORY SERIALIZERS
# ============================================================================

class EventProductCategorySerializer(serializers.ModelSerializer):
    """List/Detail serializer for EventProductCategory with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    product_id = serializers.UUIDField(source='product.product_id', read_only=True, allow_null=True)
    added_at = EventTimezoneField(read_only=True)
    
    class Meta:
        model = EventProductCategory
        fields = (
            'id', 'event', 'event_name', 'category', 'category_name',
            'product', 'product_id', 'added_at', '_links'
        )
        read_only_fields = ('id', 'added_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'category': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/products/event-categories/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/events/{obj.event.event_id}/"),
            'category': request.build_absolute_uri(f"/api/products/categories/{obj.category.id}/"),
        }


class EventProductCategoryCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for EventProductCategory with validation."""

    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        required=False,
        allow_null=True,
        help_text="Optional product ID for product-specific category mapping"
    )
    
    class Meta:
        model = EventProductCategory
        fields = ('event', 'category', 'product')
    
    def validate(self, attrs):
        """Ensure unique event-category-product combination and event consistency."""
        event = attrs.get('event') or (self.instance.event if self.instance else None)
        category = attrs.get('category') or (self.instance.category if self.instance else None)
        product = attrs.get('product') if 'product' in attrs else (self.instance.product if self.instance else None)

        if product and product.event_id != event.id:
            raise serializers.ValidationError(
                "Selected product does not belong to the specified event."
            )

        queryset = EventProductCategory.objects.filter(event=event, category=category, product=product)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise serializers.ValidationError(
                "This category mapping already exists for the selected scope."
            )
        
        return attrs


# ============================================================================
# PRODUCT SERIALIZERS
# ============================================================================

class ProductImageField(serializers.Field):
    """Custom field for handling product images."""
    
    class Meta:
        swagger_schema_fields = {
            'type': 'object',
            'properties': {
                'main': {
                    'type': 'object',
                    'nullable': True,
                    'properties': {
                        'id': {'type': 'integer'},
                        'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                        'alt_text': {'type': 'string'},
                    }
                },
                'additional': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'integer'},
                            'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                            'alt_text': {'type': 'string'},
                        }
                    }
                }
            }
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'main': {
                'type': 'object',
                'nullable': True,
                'properties': {
                    'id': {'type': 'integer'},
                    'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                    'alt_text': {'type': 'string'},
                }
            },
            'additional': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                        'alt_text': {'type': 'string'},
                    }
                }
            }
        }
    })
    def to_representation(self, value):
        """Convert product to its images."""
        request = self.context.get('request')
        images = value.product_images.all()
        
        result = {
            'main': None,
            'additional': []
        }
        
        for img in images:
            img_data = {
                'id': img.id,
                'url': request.build_absolute_uri(img.file.url) if request and img.file else None,
                'alt_text': img.name or value.title,
            }
            
            if img.tag == 'PRODUCT_PHOTO_MAIN':
                result['main'] = img_data
            else:
                result['additional'].append(img_data)
        
        return result
    
    def to_internal_value(self, data):
        """Handle image upload data."""
        # This will be handled in create/update methods
        return data


class ProductListSerializer(serializers.ModelSerializer):
    """List serializer for Product with essential information and HATEOAS."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    final_price = serializers.SerializerMethodField(help_text="Final price after percentage modifier")
    variant_count = serializers.IntegerField(source='variants.count', read_only=True)
    categories = serializers.StringRelatedField(many=True, read_only=True)
    main_image = serializers.SerializerMethodField()
    added_at = EventTimezoneField(read_only=True)
    
    class Meta:
        model = Product
        fields = (
            'id', 'product_id', 'display_code', 'title', 'event', 'event_name',
            'base_amount', 'base_amount_currency', 'percentage_modifier', 'final_price', 'verified',
            'is_active', 'variant_count', 'categories', 'main_image',
            'added_at', '_links'
        )
        read_only_fields = ('id', 'product_id', 'display_code', 'added_at', 'variant_count')
    
    def get_final_price(self, obj) -> str:
        """Return the modified price as string."""
        return str(obj.modified_amount)
    
    @extend_schema_field({
        'type': 'object',
        'nullable': True,
        'properties': {
            'id': {'type': 'integer'},
            'url': {'type': 'string', 'format': 'uri', 'nullable': True},
        }
    })
    def get_main_image(self, obj):
        """Get main product image URL."""
        request = self.context.get('request')
        main_img = obj.product_images.filter(tag='PRODUCT_PHOTO_MAIN').first()
        
        if main_img and main_img.image:
            return {
                'id': main_img.id,
                'url': request.build_absolute_uri(main_img.image.url) if request else None,
            }
        return None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'variants': {'type': 'string', 'format': 'uri'},
            'availability_windows': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/products/list/{obj.product_id}/"),
            'event': request.build_absolute_uri(f"/api/events/{obj.event.event_id}/"),
            'variants': request.build_absolute_uri(f"/api/products/list/{obj.product_id}/variants/"),
            'availability_windows': request.build_absolute_uri(f"/api/products/list/{obj.product_id}/availability-windows/"),
        }


class ProductDetailSerializer(ProductListSerializer):
    """Detailed serializer for Product with full information including images and availability windows."""
    
    images = serializers.SerializerMethodField()
    availability_windows = AvailabilityWindowSerializer(many=True, read_only=True)
    rules = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    last_updated_at = EventTimezoneField(read_only=True)
    last_updated_by_name = serializers.CharField(source='last_updated_by.username', read_only=True, allow_null=True)
    
    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + (
            'description', 'images', 'availability_windows', 'rules',
            'variants', 'added_by', 'added_by_name', 'last_updated_by',
            'last_updated_by_name', 'last_updated_at'
        )
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'main': {
                'type': 'object',
                'nullable': True,
                'properties': {
                    'id': {'type': 'integer'},
                    'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                    'alt_text': {'type': 'string'},
                }
            },
            'additional': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                        'alt_text': {'type': 'string'},
                    }
                }
            }
        }
    })
    def get_images(self, obj):
        """Get all product images (main and additional)."""
        request = self.context.get('request')
        images = obj.product_images.all()
        
        result = {
            'main': None,
            'additional': []
        }
        
        for img in images:
            img_data = {
                'id': img.id,
                'url': request.build_absolute_uri(img.image.url) if request and img.image else None,
                'alt_text': img.name or obj.title,
            }
            
            if img.tag == 'PRODUCT_PHOTO_MAIN':
                result['main'] = img_data
            else:
                result['additional'].append(img_data)
        
        return result
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_rules(self, obj) -> list:
        """Return purchase rules for the product."""
        rules = obj.rules.all()[:20]
        return [{
            'id': r.id,
            'rule_type': r.rule_type,
            'condition': r.condition,
            'is_active': r.is_active,
        } for r in rules]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_variants(self, obj) -> list:
        """Return summary of product variants."""
        request = self.context.get('request')
        variants = obj.variants.filter(is_active=True)[:20]
        return [{
            'id': v.variant_id,
            'size': v.size,
            'color': v.color,
            'stock_quantity': v.stock_quantity,
            'is_active': v.is_active,
            'url': request.build_absolute_uri(f"/api/products/list/{obj.product_id}/variants/{v.variant_id}/") if request else None,
        } for v in variants]


class ProductCreateSerializer(serializers.ModelSerializer):
    """Create serializer for Product with validation and image handling."""
    
    base_amount = MoneyField(max_digits=10, decimal_places=2)
    main_image = serializers.ImageField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Main product image file"
    )
    additional_images = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False,
        allow_empty=True,
        help_text="List of additional product image files"
    )
    
    class Meta:
        model = Product
        fields = (
            'title', 'description', 'event', 'base_amount', 'base_amount_currency', 'percentage_modifier',
            'verified', 'is_active', 'main_image', 'additional_images'
        )
    
    def validate_event(self, value):
        """Ensure event exists and is accessible."""
        if not value:
            raise serializers.ValidationError("Event is required.")
        return value
    
    def validate_base_amount(self, value):
        """Ensure amount is non-negative."""
        if value.amount < 0:
            raise serializers.ValidationError("Product price cannot be negative.")
        return value
    
    def validate_title(self, value):
        """Validate and clean title."""
        if not value or not value.strip():
            raise serializers.ValidationError("Product title cannot be empty.")
        return value.strip()
    
    def validate_main_image(self, value):
        """Validate main image file."""
        if value:
            # Check file size (max 10MB)
            if value.size > 10 * 1024 * 1024:
                raise serializers.ValidationError("Image file size cannot exceed 10MB.")
            
            # Check file type
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
            if hasattr(value, 'content_type') and value.content_type not in allowed_types:
                raise serializers.ValidationError("Only JPEG, PNG, GIF, and WebP images are allowed.")
        return value
    
    def validate_additional_images(self, value):
        """Validate additional image files."""
        if value:
            for img in value:
                # Check file size (max 10MB)
                if img.size > 10 * 1024 * 1024:
                    raise serializers.ValidationError("Each image file size cannot exceed 10MB.")
                
                # Check file type
                allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
                if hasattr(img, 'content_type') and img.content_type not in allowed_types:
                    raise serializers.ValidationError("Only JPEG, PNG, GIF, and WebP images are allowed.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        # Validate percentage modifier if provided
        percentage_modifier = attrs.get('percentage_modifier')
        if percentage_modifier is not None and percentage_modifier < -100:
            raise serializers.ValidationError({
                'percentage_modifier': 'Percentage modifier cannot be less than -100%.'
            })
        
        # Validate active status
        event = attrs.get('event')
        is_active = attrs.get('is_active', False)
        verified = attrs.get('verified', False)
        
        if is_active and event:
            requires_verification = event.settings.product_publication_requires_verification if hasattr(event, 'settings') else False
            if requires_verification and not verified:
                raise serializers.ValidationError({
                    'is_active': 'Product cannot be active until verified when verification is required.'
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create product with images."""
        main_image = validated_data.pop('main_image', None)
        additional_images = validated_data.pop('additional_images', [])
        
        # Set added_by from request user
        request = self.context.get('request')
        user = None
        if request and request.user and request.user.is_authenticated:
            validated_data['added_by'] = request.user
            user = request.user
        
        # Create product
        product = Product.objects.create(**validated_data)
        
        # Get content type for product
        content_type = ContentType.objects.get_for_model(Product)
        
        # Add main image
        if main_image:
            try:
                # Create Resource object for main image
                resource = Resource.objects.create(
                    name=f"{product.title} - Main Image",
                    description=f"Main product image for {product.title}",
                    tag='PRODUCT_PHOTO_MAIN',
                    target_type=content_type,
                    target_id=str(product.id),
                    resource_type='IMAGE',
                    image=main_image,
                    added_by=user,
                    public=True
                )
                product.add_product_image(resource, is_main=True)
            except Exception as e:
                # If resource creation fails, continue but log the error
                pass
        
        # Add additional images
        for idx, img in enumerate(additional_images, start=1):
            try:
                # Create Resource object for each additional image
                resource = Resource.objects.create(
                    name=f"{product.title} - Image {idx}",
                    description=f"Additional product image {idx} for {product.title}",
                    tag='PRODUCT_PHOTO_SECONDARY',
                    target_type=content_type,
                    target_id=str(product.id),
                    resource_type='IMAGE',
                    image=img,
                    added_by=user,
                    public=True
                )
                product.add_product_image(resource, is_main=False)
            except Exception as e:
                # If resource creation fails, continue but log the error
                pass
        
        return product


class ProductUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for Product with validation."""
    
    base_amount = MoneyField(max_digits=10, decimal_places=2, required=False)
    main_image = serializers.ImageField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Main product image file to replace current main image"
    )
    additional_images = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False,
        allow_empty=True,
        help_text="Additional product image files to add"
    )
    
    class Meta:
        model = Product
        fields = (
            'title', 'description', 'base_amount', 'base_amount_currency', 'percentage_modifier',
            'verified', 'is_active', 'main_image', 'additional_images'
        )
    
    def validate_base_amount(self, value):
        """Ensure amount is non-negative."""
        if value and value.amount < 0:
            raise serializers.ValidationError("Product price cannot be negative.")
        return value
    
    def validate_title(self, value):
        """Validate and clean title."""
        if value and not value.strip():
            raise serializers.ValidationError("Product title cannot be empty.")
        return value.strip() if value else value
    
    def validate_main_image(self, value):
        """Validate main image file."""
        if value:
            # Check file size (max 10MB)
            if value.size > 10 * 1024 * 1024:
                raise serializers.ValidationError("Image file size cannot exceed 10MB.")
            
            # Check file type
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
            if hasattr(value, 'content_type') and value.content_type not in allowed_types:
                raise serializers.ValidationError("Only JPEG, PNG, GIF, and WebP images are allowed.")
        return value
    
    def validate_additional_images(self, value):
        """Validate additional image files."""
        if value:
            for img in value:
                # Check file size (max 10MB)
                if img.size > 10 * 1024 * 1024:
                    raise serializers.ValidationError("Each image file size cannot exceed 10MB.")
                
                # Check file type
                allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
                if hasattr(img, 'content_type') and img.content_type not in allowed_types:
                    raise serializers.ValidationError("Only JPEG, PNG, GIF, and WebP images are allowed.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        percentage_modifier = attrs.get('percentage_modifier')
        if percentage_modifier is not None and percentage_modifier < -100:
            raise serializers.ValidationError({
                'percentage_modifier': 'Percentage modifier cannot be less than -100%.'
            })
        
        return attrs
    
    def update(self, instance, validated_data):
        """Update product with images."""
        main_image = validated_data.pop('main_image', None)
        additional_images = validated_data.pop('additional_images', [])
        
        # Set last_updated_by from request user
        request = self.context.get('request')
        user = None
        if request and request.user and request.user.is_authenticated:
            validated_data['last_updated_by'] = request.user
            user = request.user
        
        # Update product fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Get content type for product
        content_type = ContentType.objects.get_for_model(Product)
        
        # Update main image if provided
        if main_image:
            try:
                # Remove old main image
                old_main_images = instance.resources.filter(tag='PRODUCT_PHOTO_MAIN')
                for old_img in old_main_images:
                    instance.remove_product_image(old_img)
                
                # Create and add new main image
                resource = Resource.objects.create(
                    name=f"{instance.title} - Main Image",
                    description=f"Main product image for {instance.title}",
                    tag='PRODUCT_PHOTO_MAIN',
                    target_type=content_type,
                    target_id=str(instance.id),
                    resource_type='IMAGE',
                    image=main_image,
                    added_by=user,
                    public=True
                )
                instance.add_product_image(resource, is_main=True)
            except Exception as e:
                pass  # Continue if image update fails
        
        # Add additional images if provided
        for idx, img in enumerate(additional_images, start=1):
            try:
                # Create Resource object for each additional image
                existing_count = instance.resources.filter(tag='PRODUCT_PHOTO_SECONDARY').count()
                resource = Resource.objects.create(
                    name=f"{instance.title} - Image {existing_count + idx}",
                    description=f"Additional product image for {instance.title}",
                    tag='PRODUCT_PHOTO_SECONDARY',
                    target_type=content_type,
                    target_id=str(instance.id),
                    resource_type='IMAGE',
                    image=img,
                    added_by=user,
                    public=True
                )
                instance.add_product_image(resource, is_main=False)
            except Exception as e:
                pass  # Continue if image addition fails
        
        return instance


# ============================================================================
# PRODUCT VARIANT SERIALIZERS
# ============================================================================

class ProductVariantListSerializer(serializers.ModelSerializer):
    """List serializer for ProductVariant with essential information."""
    
    _links = serializers.SerializerMethodField()
    product_title = serializers.CharField(source='product.title', read_only=True)
    final_price = serializers.SerializerMethodField(help_text="Final price after percentage modifier")
    size_display = serializers.CharField(source='get_size_display', read_only=True)
    is_in_stock = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    added_at = EventTimezoneField(read_only=True)
    
    class Meta:
        model = ProductVariant
        fields = (
            'id', 'variant_id', 'product', 'product_title', 'size', 'size_display',
            'color', 'stock_quantity', 'max_purchase_quantity_per_order',
            'final_price', 'is_active', 'verified', 'is_in_stock',
            'images', 'added_at', '_links'
        )
        read_only_fields = ('id', 'variant_id', 'added_at')
    
    def get_final_price(self, obj) -> str:
        """Return the modified price as string."""
        return str(obj.modified_amount)
    
    def get_is_in_stock(self, obj) -> bool:
        """Check if variant has stock."""
        return obj.stock_quantity > 0
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'main': {
                'type': 'object',
                'nullable': True,
                'properties': {
                    'id': {'type': 'integer'},
                    'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                    'alt_text': {'type': 'string'},
                }
            },
            'additional': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                        'alt_text': {'type': 'string'},
                    }
                }
            }
        }
    })
    def get_images(self, obj) -> Dict[str, Any]:
        """Return all variant images."""
        main_images = obj.resources.filter(tag='VARIANT_PHOTO_MAIN')
        additional_images = obj.resources.filter(tag='VARIANT_PHOTO_SECONDARY')
        request = self.context.get('request')
        result = {
            'main': None,
            'additional': []
        }
        
        if main_images.exists():
            img = main_images.first()
            # return full url
            result['main'] = {
                'id': img.id,
                'url': request.build_absolute_uri(img.image.url) if img.image else None,
                'alt_text': img.name or '',
            }
        
        for img in additional_images:
            result['additional'].append({
                'id': img.id,
                'url': request.build_absolute_uri(img.image.url) if img.image else None,
                'alt_text': img.name or '',
            })
        
        return result
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'product': {'type': 'string', 'format': 'uri'},
            'availability_windows': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/products/list/{obj.product.product_id}/variants/{obj.variant_id}/"),
            'product': request.build_absolute_uri(f"/api/products/list/{obj.product.product_id}/"),
            'availability_windows': request.build_absolute_uri(f"/api/products/list/{obj.product.product_id}/variants/{obj.variant_id}/availability-windows/"),
        }


class ProductVariantDetailSerializer(ProductVariantListSerializer):
    """Detailed serializer for ProductVariant with full information and availability windows."""
    
    product_details = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    availability_windows = AvailabilityWindowSerializer(many=True, read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    last_updated_at = EventTimezoneField(read_only=True)
    last_updated_by_name = serializers.CharField(source='last_updated_by.username', read_only=True, allow_null=True)
    base_amount = serializers.SerializerMethodField()
    
    class Meta(ProductVariantListSerializer.Meta):
        fields = ProductVariantListSerializer.Meta.fields + (
            'base_amount', 'base_amount_currency', 'percentage_modifier', 'max_stock_quantity',
            'images', 'availability_windows', 'product_details', 'added_by', 'added_by_name',
            'last_updated_by', 'last_updated_by_name', 'last_updated_at'
        )
    
    def get_base_amount(self, obj) -> str:
        """Return base amount as string."""
        return str(obj.base_amount)
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'main': {
                'type': 'object',
                'nullable': True,
                'properties': {
                    'id': {'type': 'integer'},
                    'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                    'alt_text': {'type': 'string'},
                }
            },
            'additional': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'url': {'type': 'string', 'format': 'uri', 'nullable': True},
                        'alt_text': {'type': 'string'},
                    }
                }
            }
        }
    })
    def get_images(self, obj) -> Dict[str, Any]:
        """Return all variant images."""
        main_images = obj.resources.filter(tag='VARIANT_PHOTO_MAIN')
        additional_images = obj.resources.filter(tag='VARIANT_PHOTO_SECONDARY')
        
        result = {
            'main': None,
            'additional': []
        }
        
        if main_images.exists():
            img = main_images.first()
            result['main'] = {
                'id': img.id,
                'url': img.file.url if img.file else None,
                'alt_text': img.name or '',
            }
        
        for img in additional_images:
            result['additional'].append({
                'id': img.id,
                'url': img.file.url if img.file else None,
                'alt_text': img.name or '',
            })
        
        return result
    
    @extend_schema_field({'type': 'object'})
    def get_product_details(self, obj) -> dict:
        """Return basic product information."""
        return {
            'product_id': str(obj.product.product_id),
            'title': obj.product.title,
            'display_code': obj.product.display_code,
        }


class ProductVariantCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for ProductVariant with validation."""
    
    class Meta:
        model = ProductVariant
        fields = (
            'product', 'size', 'color', 'stock_quantity', 'max_stock_quantity',
            'max_purchase_quantity_per_order', 'percentage_modifier',
            'verified', 'is_active'
        )
    
    def validate_product(self, value):
        """Ensure product exists."""
        if not value:
            raise serializers.ValidationError("Product is required.")
        return value
    
    def validate_stock_quantity(self, value):
        """Ensure stock quantity is non-negative."""
        if value < 0:
            raise serializers.ValidationError("Stock quantity cannot be negative.")
        return value
    
    def validate_max_stock_quantity(self, value):
        """Validate max stock quantity."""
        if value is not None and value < 0:
            raise serializers.ValidationError("Max stock quantity cannot be negative.")
        return value
    
    def validate_max_purchase_quantity_per_order(self, value):
        """Validate max purchase quantity."""
        if value <= 0:
            raise serializers.ValidationError("Max purchase quantity must be at least 1.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        stock_quantity = attrs.get('stock_quantity', 0)
        max_stock_quantity = attrs.get('max_stock_quantity')
        
        if max_stock_quantity is not None and stock_quantity > max_stock_quantity:
            raise serializers.ValidationError({
                'stock_quantity': 'Stock quantity cannot exceed max stock quantity.'
            })
        
        # Validate unique size+color combination per product
        product = attrs.get('product') or (self.instance.product if self.instance else None)
        size = attrs.get('size') or (self.instance.size if self.instance else None)
        color = attrs.get('color') or (self.instance.color if self.instance else None)
        
        if product and size and color:
            # Normalize color to uppercase for comparison (hex colors)
            normalized_color = color.upper() if color else None
            
            queryset = ProductVariant.objects.filter(
                product=product,
                size=size,
                color__iexact=normalized_color
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise serializers.ValidationError({
                    'non_field_errors': [
                        f"A variant with size '{size}' and color '{color}' already exists for this product. "
                        "Each variant must have a unique combination of size and color."
                    ]
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create variant with proper user tracking."""
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            validated_data['added_by'] = request.user
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Update variant with proper user tracking."""
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            validated_data['last_updated_by'] = request.user
        
        return super().update(instance, validated_data)


# ============================================================================
# ORDER SERIALIZERS
# ============================================================================

class OrderItemSerializer(serializers.ModelSerializer):
    """Serializer for OrderItem (read-only in most contexts)."""
    
    product_variant_details = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    
    class Meta:
        model = OrderItem
        fields = (
            'id', 'product_variant', 'product_variant_details',
            'quantity', 'unit_price', 'total_price'
        )
        read_only_fields = ('id', 'unit_price', 'total_price')
    
    def get_unit_price(self, obj) -> str:
        return str(obj.unit_price)
    
    def get_total_price(self, obj) -> str:
        return str(obj.total_price)
    
    @extend_schema_field({'type': 'object'})
    def get_product_variant_details(self, obj) -> dict:
        """Return product variant details."""
        if not obj.product_variant:
            return None
        
        v = obj.product_variant
        return {
            'variant_id': str(v.variant_id),
            'product_title': v.product.title,
            'size': v.size,
            'color': v.color,
        }


class OrderItemCreateSerializer(serializers.Serializer):
    """Create serializer for adding items to orders."""
    
    product_variant_id = serializers.UUIDField(help_text="UUID of the product variant")
    quantity = serializers.IntegerField(min_value=1, help_text="Quantity to order")
    
    def validate_product_variant_id(self, value):
        """Ensure product variant exists."""
        try:
            ProductVariant.objects.get(variant_id=value)
        except ProductVariant.DoesNotExist:
            raise serializers.ValidationError("Product variant does not exist.")
        return value


class OrderListSerializer(serializers.ModelSerializer):
    """List serializer for Order with essential information."""
    
    _links = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    attendee_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_amount = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(source='order_items.count', read_only=True)
    created_at = EventTimezoneField(read_only=True)
    
    class Meta:
        model = Order
        fields = (
            'id', 'order_id', 'order_reference_id', 'customer', 'customer_name',
            'attendee', 'attendee_name', 'status', 'status_display',
            'total_amount', 'item_count', 'created_at', '_links'
        )
        read_only_fields = ('id', 'order_id', 'order_reference_id', 'created_at')
    
    def get_total_amount(self, obj) -> str:
        return str(obj.total_amount)
    
    def get_customer_name(self, obj) -> Optional[str]:
        if obj.customer:
            return f"{obj.customer.first_name} {obj.customer.last_name}".strip() or obj.customer.username
        return None
    
    def get_attendee_name(self, obj) -> Optional[str]:
        if obj.attendee:
            return f"{obj.attendee.first_name} {obj.attendee.last_name}".strip()
        return None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'customer': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/products/orders/{obj.order_id}/"),
        }
        
        if obj.customer:
            links['customer'] = request.build_absolute_uri(f"/api/users/{obj.customer.id}/")
        
        if obj.attendee:
            links['attendee'] = request.build_absolute_uri(f"/api/attendees/{obj.attendee.attendee_id}/")
        
        return links


class OrderDetailSerializer(OrderListSerializer):
    """Detailed serializer for Order with full information including items."""
    
    order_items = OrderItemSerializer(many=True, read_only=True)
    payment_details = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    updated_at = EventTimezoneField(read_only=True)
    updated_by_name = serializers.CharField(source='updated_by.username', read_only=True, allow_null=True)
    
    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + (
            'order_items', 'payment', 'payment_details',
            'created_by', 'created_by_name', 'updated_by',
            'updated_by_name', 'updated_at'
        )
    
    @extend_schema_field({'type': 'object'})
    def get_payment_details(self, obj) -> Optional[dict]:
        """Return payment information if available."""
        if obj.payment:
            return {
                'payment_id': str(obj.payment.payment_id),
                'payment_reference': obj.payment.payment_reference,
                'status': obj.payment.status,
            }
        return None


class OrderCreateSerializer(serializers.ModelSerializer):
    """Create serializer for Order with validation."""
    
    items = OrderItemCreateSerializer(many=True, write_only=True, help_text="Items to add to the order")
    
    class Meta:
        model = Order
        fields = ('customer', 'attendee', 'items', 'order_id')
    
    def validate(self, attrs):
        """Validate order creation."""
        customer = attrs.get('customer')
        attendee = attrs.get('attendee')
        items = attrs.get('items', [])
        
        # Must have either customer or attendee
        if not customer and not attendee:
            raise serializers.ValidationError(
                "Order must have either a customer or an attendee."
            )
        
        # Must have at least one item
        if not items:
            raise serializers.ValidationError({
                'items': 'Order must have at least one item.'
            })
        
        # If attendee is provided, validate items can be purchased
        if attendee:
            for item_data in items:
                variant_id = item_data['product_variant_id']
                quantity = item_data['quantity']
                
                try:
                    variant = ProductVariant.objects.get(variant_id=variant_id)
                    
                    # Check if attendee can purchase this variant
                    if not variant.can_attendee_purchase(attendee):
                        raise serializers.ValidationError({
                            'items': f"Attendee cannot purchase variant {variant_id}."
                        })
                    
                    # Check quantity availability
                    if not variant.can_attendee_purchase_quantity(attendee, quantity):
                        raise serializers.ValidationError({
                            'items': f"Insufficient stock or exceeds purchase limit for variant {variant_id}."
                        })
                
                except ProductVariant.DoesNotExist:
                    raise serializers.ValidationError({
                        'items': f"Variant {variant_id} does not exist."
                    })
        
        return attrs
    
    def create(self, validated_data):
        """Create order with items."""
        items_data = validated_data.pop('items')
        
        # Set created_by from request user
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            validated_data['created_by'] = request.user
        
        # Initialize order in draft status with zero amount
        validated_data['status'] = OrderStatusChoices.DRAFT
        validated_data['total_amount'] = Money(0, 'GBP')
        
        # Create order
        order = Order.objects.create(**validated_data)
        
        # Add items to order
        for item_data in items_data:
            variant = ProductVariant.objects.get(variant_id=item_data['product_variant_id'])
            quantity = item_data['quantity']
            
            # Use the model's add_order_item method which handles all business logic
            order.add_order_item(variant, quantity)
            
        order.recalculate_total_amount()
        return order


class OrderUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for Order (limited fields)."""
    
    class Meta:
        model = Order
        fields = ('status',)
    
    def validate_status(self, value):
        """Validate status transitions."""
        if self.instance:
            if not self.instance.can_transition_to(value):
                raise serializers.ValidationError(
                    f"Cannot transition from {self.instance.status} to {value}."
                )
        return value
    
    def update(self, instance, validated_data):
        """Update order with status transition."""
        new_status = validated_data.get('status')
        
        if new_status and new_status != instance.status:
            instance.transition_to(new_status)
        
        # Set updated_by from request user
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            instance.updated_by = request.user
            instance.save()
        
        return instance


# ============================================================================
# ORDER CHECKOUT SERIALIZER
# ============================================================================

class OrderCheckoutSerializer(serializers.Serializer):
    """
    Checkout serializer for orders.
    
    Validates payment method and order status before creating payment.
    Backend calculates all pricing from order.total_amount.
    """
    
    payment_method_id = serializers.IntegerField(
        help_text="ID of the PaymentMethod to use for this order"
    )
    
    def validate_payment_method_id(self, value):
        """Validate payment method exists and is active."""
        from apps.payments.models import PaymentMethod
        
        try:
            payment_method = PaymentMethod.objects.get(id=value)
        except PaymentMethod.DoesNotExist:
            raise serializers.ValidationError(
                f'PaymentMethod with id {value} does not exist.'
            )
        
        if not payment_method.is_active:
            raise serializers.ValidationError(
                f'Payment method "{payment_method.title}" is not active.'
            )
        
        return value
    
    def validate(self, attrs):
        """Cross-field validation for order checkout."""
        order = self.context.get('order')
        
        if not order:
            raise serializers.ValidationError('Order context is required.')
        
        # Validate order is in pending status (already submitted)
        if order.status != OrderStatusChoices.DRAFT:
            raise serializers.ValidationError({
                'order': f'Order must be in DRAFT status to checkout. Current status: {order.get_status_display()}'
            })
        
        # Validate order has at least one item
        if not order.order_items.exists():
            raise serializers.ValidationError({
                'order': 'Order must have at least one item.'
            })
        
        # Validate payment method belongs to same event as order
        from apps.payments.models import PaymentMethod
        payment_method = PaymentMethod.objects.get(id=attrs['payment_method_id'])
        
        order_event = order.attendee.event if order.attendee else None
        if not order_event:
            raise serializers.ValidationError({
                'order': 'Order must have an attendee with event context.'
            })
        
        if payment_method.event_id != order_event.id:
            raise serializers.ValidationError({
                'payment_method_id': f'Payment method must belong to the same event as the order ({order_event.title}).'
            })
        
        # Store payment method for use in viewset
        attrs['payment_method'] = payment_method
        
        return attrs
