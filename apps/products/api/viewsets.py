"""
Production-grade viewsets for the products app.

Provides comprehensive viewsets for product management with proper validation,
business logic separation, schema configuration, nested routes, custom actions,
and permission classes.

ViewSets:
    - ProductCategoryViewSet: Manage product categories (admin only create/update/delete)
    - EventProductCategoryViewSet: Manage event-category associations
    - ProductViewSet: Full CRUD for products with nested variants route and image management
    - ProductVariantViewSet: Manage product variants with stock operations (nested under products)
    - OrderViewSet: Manage orders with item management and status transitions
    - OrderItemViewSet: Read-only order items (managed through orders)

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied

from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch, Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any

from apps.products.models import (
    Product, ProductVariant,
    Order, OrderItem, OrderStatusChoices,
    ProductCategory, EventProductCategory
)
from apps.common.models import Resource
from .serializers import (
    ProductCategorySerializer, ProductCategoryCreateUpdateSerializer,
    EventProductCategorySerializer, EventProductCategoryCreateUpdateSerializer,
    ProductListSerializer, ProductDetailSerializer, ProductCreateSerializer, ProductUpdateSerializer,
    ProductVariantListSerializer, ProductVariantDetailSerializer, ProductVariantCreateUpdateSerializer,
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer, OrderUpdateSerializer,
    OrderItemSerializer, OrderItemCreateSerializer,
)
from .filtersets import (
    ProductCategoryFilterSet, EventProductCategoryFilterSet,
    ProductFilterSet, ProductVariantFilterSet, OrderFilterSet,
)
from .permissions import (
    IsAdministrativeStaff, IsAdministrativeStaffOnly,
    IsOrderOwnerOrAdministrative, IsReadOnly,
    CanManageProducts, CanManageCategories,
)

import decimal


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration for product endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================================
# PRODUCT CATEGORY VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List product categories",
        description="Retrieve a paginated list of all product categories. Categories are global across all events.",
        tags=["Product Categories"],
    ),
    retrieve=extend_schema(
        summary="Retrieve category details",
        description="Get detailed information about a specific product category.",
        tags=["Product Categories"],
    ),
    create=extend_schema(
        summary="Create product category",
        description="Create a new product category. Only superusers and staff can create global categories.",
        tags=["Product Categories"],
    ),
    update=extend_schema(
        summary="Update product category",
        description="Update an existing product category. Only superusers and staff can modify categories.",
        tags=["Product Categories"],
    ),
    partial_update=extend_schema(
        summary="Partially update product category",
        description="Partially update a product category.",
        tags=["Product Categories"],
    ),
    destroy=extend_schema(
        summary="Delete product category",
        description="Delete a product category. Only allowed if no products are using this category.",
        tags=["Product Categories"],
    ),
)
class ProductCategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing product categories.
    
    Provides:
    - List/Retrieve: All authenticated users
    - Create/Update/Delete: Superusers and staff only
    
    Categories are global and can be associated with events through EventProductCategory.
    """
    
    queryset = ProductCategory.objects.all()
    permission_classes = [permissions.IsAuthenticated, CanManageCategories]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductCategoryFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return ProductCategoryCreateUpdateSerializer
        return ProductCategorySerializer


@extend_schema_view(
    list=extend_schema(
        summary="List event-category associations",
        description="Retrieve a paginated list of event-category associations.",
        tags=["Product Categories"],
    ),
    retrieve=extend_schema(
        summary="Retrieve association details",
        description="Get detailed information about a specific event-category association.",
        tags=["Product Categories"],
    ),
    create=extend_schema(
        summary="Associate category with event",
        description="Create a new event-category association. Event administrators can manage their event's categories.",
        tags=["Product Categories"],
    ),
    destroy=extend_schema(
        summary="Remove category from event",
        description="Delete an event-category association.",
        tags=["Product Categories"],
    ),
)
class EventProductCategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event-category associations.
    
    Provides:
    - List/Retrieve: All authenticated users
    - Create/Delete: Event administrators
    
    Note: Update is not supported - delete and recreate instead.
    """
    
    queryset = EventProductCategory.objects.select_related('event', 'category')
    permission_classes = [permissions.IsAuthenticated, CanManageCategories]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventProductCategoryFilterSet
    search_fields = ['event__title', 'category__name']
    ordering_fields = ['added_at', 'event__title', 'category__name']
    ordering = ['-added_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']  # No PUT/PATCH
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'create':
            return EventProductCategoryCreateUpdateSerializer
        return EventProductCategorySerializer


# ============================================================================
# PRODUCT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List products",
        description="Retrieve a paginated list of products. Supports extensive filtering for e-commerce-style search including price ranges, categories, stock availability, and full-text search.",
        tags=["Products"],
        examples=[
            OpenApiExample(
                'Filter by event and category',
                value={'event': 123, 'category': '1,2', 'in_stock': True},
                request_only=True,
            ),
            OpenApiExample(
                'Price range search',
                value={'min_price': 10, 'max_price': 50, 'is_active': True},
                request_only=True,
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve product details",
        description="Get detailed information about a specific product including images, variants, availability windows, and rules.",
        tags=["Products"],
    ),
    create=extend_schema(
        summary="Create product",
        description="Create a new product. Event administrators can create products for their events. Supports image upload via multipart/form-data for direct file uploads (main_image and additional_images fields) instead of resource IDs.",
        tags=["Products"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'description': {'type': 'string'},
                    'event': {'type': 'integer'},
                    'base_amount': {'type': 'string'},
                    'base_amount_currency': {'type': 'string'},
                    'percentage_modifier': {'type': 'number'},
                    'verified': {'type': 'boolean'},
                    'is_active': {'type': 'boolean'},
                    'category_ids': {'type': 'array', 'items': {'type': 'integer'}},
                    'main_image': {'type': 'string', 'format': 'binary'},
                    'additional_images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                }
            }
        }
    ),
    update=extend_schema(
        summary="Update product",
        description="Update an existing product. Only administrators can modify products. Supports image upload via multipart/form-data for direct file uploads.",
        tags=["Products"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'description': {'type': 'string'},
                    'base_amount': {'type': 'string'},
                    'base_amount_currency': {'type': 'string'},
                    'percentage_modifier': {'type': 'number'},
                    'verified': {'type': 'boolean'},
                    'is_active': {'type': 'boolean'},
                    'category_ids': {'type': 'array', 'items': {'type': 'integer'}},
                    'main_image': {'type': 'string', 'format': 'binary'},
                    'additional_images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                }
            }
        }
    ),
    partial_update=extend_schema(
        summary="Partially update product",
        description="Partially update a product. Supports image upload via multipart/form-data for direct file uploads.",
        tags=["Products"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'description': {'type': 'string'},
                    'base_amount': {'type': 'string'},
                    'base_amount_currency': {'type': 'string'},
                    'percentage_modifier': {'type': 'number'},
                    'verified': {'type': 'boolean'},
                    'is_active': {'type': 'boolean'},
                    'category_ids': {'type': 'array', 'items': {'type': 'integer'}},
                    'main_image': {'type': 'string', 'format': 'binary'},
                    'additional_images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                }
            }
        }
    ),
    destroy=extend_schema(
        summary="Delete product",
        description="Delete a product. Only allowed if no orders reference this product's variants.",
        tags=["Products"],
    ),
)
class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing products.
    
    Provides:
    - List/Retrieve: All authenticated users
    - Create/Update/Delete: Event administrators
    - Custom actions: add_image, remove_image, toggle_active
    - Nested route: /products/list/{product_id}/variants/
    
    Permissions:
    - Read: Authenticated users
    - Write: Administrative staff for the event
    """
    
    queryset = Product.objects.select_related('event', 'added_by', 'last_updated_by').prefetch_related(
        'variants'
    )
    permission_classes = [permissions.IsAuthenticated, CanManageProducts]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilterSet
    search_fields = ['title', 'description', 'display_code']
    ordering_fields = ['added_at', 'title', 'base_amount']
    ordering = ['-added_at']
    lookup_field = 'product_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return ProductListSerializer
        elif self.action == 'create':
            return ProductCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ProductUpdateSerializer
        return ProductDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Admins see all products
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see only active products (unless they're event admins)
        # Event admins can see their event's products regardless of active status
        # For now, show all active products to authenticated users
        return queryset.filter(is_active=True)
    
    @extend_schema(
        summary="Add image to product",
        description="Upload an image file directly to the product. The file will be automatically converted to a Resource object and attached to the product. Supports JPEG, PNG, GIF, and WebP formats up to 10MB. If is_main is true, any existing main image will be replaced.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'image': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Image file to upload (JPEG, PNG, GIF, or WebP, max 10MB)'
                    },
                    'is_main': {
                        'type': 'string',
                        'description': 'Whether this should be the main product image (true/false, 1/0, yes/no)',
                        'default': 'false'
                    },
                },
                'required': ['image'],
            }
        },
        responses={
            200: {
                'description': 'Image added successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Image added to product Conference T-Shirt.',
                            'resource_id': 123,
                            'image_url': 'https://example.com/media/resources/images/product_image.png'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid image file or validation error',
                'content': {
                    'application/json': {
                        'example': {
                            'image': ['Image file size cannot exceed 10MB.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'}
        },
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='add-image')
    def add_image(self, request, product_id=None):
        """Add an image to the product."""
        product = self.get_object()
        image_file = request.FILES.get('image')
        is_main = request.data.get('is_main', 'false').lower() in ['true', '1', 'yes']
        
        if not image_file:
            raise ValidationError({'image': 'Image file is required.'})
        
        # Validate file size (max 10MB)
        if image_file.size > 10 * 1024 * 1024:
            raise ValidationError({'image': 'Image file size cannot exceed 10MB.'})
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        if hasattr(image_file, 'content_type') and image_file.content_type not in allowed_types:
            raise ValidationError({'image': 'Only JPEG, PNG, GIF, and WebP images are allowed.'})
        
        try:
            # Get content type for product
            from django.contrib.contenttypes.models import ContentType
            content_type = ContentType.objects.get_for_model(Product)
            
            # Create Resource object for the image
            tag = 'PRODUCT_PHOTO_MAIN' if is_main else 'PRODUCT_PHOTO_SECONDARY'
            resource = Resource.objects.create(
                name=f"{product.title} - {'Main' if is_main else 'Additional'} Image",
                description=f"{'Main' if is_main else 'Additional'} product image for {product.title}",
                tag=tag,
                target_type=content_type,
                target_id=str(product.id),
                resource_type='IMAGE',
                image=image_file,
                added_by=request.user,
                public=True
            )
            
            product.add_product_image(resource, is_main=is_main)
            
            return Response({
                'status': 'success',
                'message': f'Image added to product {product.title}.',
                'resource_id': resource.id,
                'image_url': resource.image.url if resource.image else None
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Remove image from product",
        description="Remove an image resource from the product by providing the resource ID. The resource will be disassociated from the product.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'resource_id': {
                        'type': 'integer',
                        'description': 'ID of the image resource to remove'
                    },
                },
                'required': ['resource_id'],
            }
        },
        responses={
            200: {
                'description': 'Image removed successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Image removed from product Conference T-Shirt.'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid resource_id or validation error',
                'content': {
                    'application/json': {
                        'example': {
                            'resource_id': ['Resource ID is required.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Resource does not exist'}
        },
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='remove-image')
    def remove_image(self, request, product_id=None):
        """Remove an image from the product."""
        product = self.get_object()
        resource_id = request.data.get('resource_id')
        
        if not resource_id:
            raise ValidationError({'resource_id': 'Resource ID is required.'})
        
        try:
            resource = Resource.objects.get(id=resource_id)
            product.remove_product_image(resource)
            return Response({
                'status': 'success',
                'message': f'Image removed from product {product.title}.'
            }, status=status.HTTP_200_OK)
        except Resource.DoesNotExist:
            raise ValidationError({'resource_id': 'Resource does not exist.'})
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Toggle product active status",
        description="Toggle the is_active status of a product between true and false. Only administrators can perform this action. Active products are visible to regular users, inactive products are only visible to administrators.",
        request=None,
        responses={
            200: {
                'description': 'Status toggled successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'is_active': True,
                            'message': 'Product Conference T-Shirt is now active.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Product not found'}
        },
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_name='toggle-active', url_path='toggle-active')
    def toggle_active(self, request, product_id=None):
        """Toggle the is_active status of the product."""
        product = self.get_object()
        product.is_active = not product.is_active
        product.save()
        
        return Response({
            'status': 'success',
            'is_active': product.is_active,
            'message': f'Product {product.title} is now {"active" if product.is_active else "inactive"}.'
        }, status=status.HTTP_200_OK)


# ============================================================================
# PRODUCT VARIANT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List product variants",
        description="Retrieve a paginated list of product variants. Supports filtering by size, color, stock, price ranges. Can be accessed as nested route under products or standalone.",
        tags=["Product Variants"],
    ),
    retrieve=extend_schema(
        summary="Retrieve variant details",
        description="Get detailed information about a specific product variant including stock, pricing, and product details.",
        tags=["Product Variants"],
    ),
    create=extend_schema(
        summary="Create product variant",
        description="Create a new product variant. Event administrators can create variants for their products.",
        tags=["Product Variants"],
    ),
    update=extend_schema(
        summary="Update product variant",
        description="Update an existing product variant. Only administrators can modify variants.",
        tags=["Product Variants"],
    ),
    partial_update=extend_schema(
        summary="Partially update product variant",
        description="Partially update a product variant.",
        tags=["Product Variants"],
    ),
    destroy=extend_schema(
        summary="Delete product variant",
        description="Delete a product variant. Only allowed if no orders reference this variant.",
        tags=["Product Variants"],
    ),
)
class ProductVariantViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing product variants.
    
    Provides:
    - List/Retrieve: All authenticated users
    - Create/Update/Delete: Event administrators
    - Custom actions: increment_stock, decrement_stock, set_stock, toggle_active
    
    Permissions:
    - Read: Authenticated users
    - Write: Administrative staff for the event
    - Stock operations: Administrative staff only
    """
    
    queryset = ProductVariant.objects.select_related(
        'product', 'product__event', 'added_by', 'last_updated_by'
    )
    permission_classes = [permissions.IsAuthenticated, CanManageProducts]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductVariantFilterSet
    search_fields = ['product__title', 'size', 'color']
    ordering_fields = ['added_at', 'stock_quantity', 'base_amount']
    ordering = ['-added_at']
    lookup_field = 'variant_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return ProductVariantListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProductVariantCreateUpdateSerializer
        return ProductVariantDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on URL and user permissions."""
        queryset = super().get_queryset()
        
        # If accessing through nested route, filter by product
        product_id = self.kwargs.get('product_product_id')
        if product_id:
            queryset = queryset.filter(product__product_id=product_id)
        
        user = self.request.user
        
        # Admins see all variants
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see only active variants of active products
        return queryset.filter(is_active=True, product__is_active=True)
    
    @extend_schema(
        summary="Increment variant stock",
        description="Atomically increment the stock quantity of a variant. The operation is atomic to prevent race conditions. If max_stock_quantity is set, the increment will fail if it would exceed the maximum. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'amount': {
                        'type': 'integer',
                        'description': 'Amount to increment (must be positive)',
                        'example': 10,
                        'minimum': 1
                    },
                },
                'required': ['amount'],
            }
        },
        responses={
            200: {
                'description': 'Stock incremented successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'stock_quantity': 60,
                            'message': 'Stock incremented by 10. New stock: 60'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid amount or would exceed max stock',
                'content': {
                    'application/json': {
                        'example': {
                            'amount': ['Amount must be a positive integer.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='increment-stock')
    def increment_stock(self, request, product_product_id=None, variant_id=None):
        """Increment the stock quantity of the variant."""
        variant = self.get_object()
        amount = request.data.get('amount')

        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise ValidationError({'amount': 'Amount must be a positive integer.'})
        
        if not amount or amount <= 0:
            raise ValidationError({'amount': 'Amount must be a positive amount.'})
        
        try:
            variant.increment_stock(amount)
            variant.refresh_from_db()
            return Response({
                'status': 'success',
                'stock_quantity': variant.stock_quantity,
                'message': f'Stock incremented by {amount}. New stock: {variant.stock_quantity}'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Decrement variant stock",
        description="Atomically decrement the stock quantity of a variant. The operation is atomic to prevent race conditions. Will fail if there is insufficient stock. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'amount': {
                        'type': 'integer',
                        'description': 'Amount to decrement (must be positive)',
                        'example': 5,
                        'minimum': 1
                    },
                },
                'required': ['amount'],
            }
        },
        responses={
            200: {
                'description': 'Stock decremented successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'stock_quantity': 45,
                            'message': 'Stock decremented by 5. New stock: 45'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid amount or insufficient stock',
                'content': {
                    'application/json': {
                        'example': {
                            'error': 'Insufficient stock for the selected product variant.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='decrement-stock')
    def decrement_stock(self, request, product_product_id=None, variant_id=None):
        """Decrement the stock quantity of the variant."""
        variant = self.get_object()
        amount = request.data.get('amount')

        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise ValidationError({'amount': 'Amount must be a positive integer.'})
        
        if not amount or amount <= 0:
            raise ValidationError({'amount': 'Amount must be a positive amount.'})
        
        try:
            variant.decrement_stock(amount)
            variant.refresh_from_db()
            return Response({
                'status': 'success',
                'stock_quantity': variant.stock_quantity,
                'message': f'Stock decremented by {amount}. New stock: {variant.stock_quantity}'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Set variant stock",
        description="Set the stock quantity to a specific value, overriding the current stock level. Useful for inventory adjustments or corrections. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'stock_quantity': {
                        'type': 'integer',
                        'description': 'New stock quantity (must be non-negative)',
                        'example': 50,
                        'minimum': 0
                    },
                },
                'required': ['stock_quantity'],
            }
        },
        responses={
            200: {
                'description': 'Stock set successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'stock_quantity': 50,
                            'message': 'Stock set to 50.'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid stock_quantity value',
                'content': {
                    'application/json': {
                        'example': {
                            'stock_quantity': ['Stock quantity must be a non-negative integer.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='set-stock')
    def set_stock(self, request, product_product_id=None, variant_id=None):
        """Set the stock quantity to a specific value."""
        variant = self.get_object()
        stock_quantity = request.data.get('stock_quantity')

        try:
            stock_quantity = int(stock_quantity)
        except (TypeError, ValueError):
            raise ValidationError({'stock_quantity': 'Stock quantity must be a non-negative integer.'})
        
        if stock_quantity is None or not isinstance(stock_quantity, int) or stock_quantity < 0:
            raise ValidationError({'stock_quantity': 'Stock quantity must be a non-negative integer.'})
        
        variant.stock_quantity = stock_quantity
        variant.save()
        
        return Response({
            'status': 'success',
            'stock_quantity': variant.stock_quantity,
            'message': f'Stock set to {stock_quantity}.'
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Toggle variant active status",
        description="Toggle the is_active status of a variant between true and false. Only administrators can perform this action. Inactive variants are not visible to regular users and cannot be purchased.",
        request=None,
        responses={
            200: {
                'description': 'Status toggled successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'is_active': True,
                            'message': 'Variant is now active.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def toggle_active(self, request, product_product_id=None, variant_id=None):
        """Toggle the is_active status of the variant."""
        variant = self.get_object()
        variant.is_active = not variant.is_active
        variant.save()
        
        return Response({
            'status': 'success',
            'is_active': variant.is_active,
            'message': f'Variant is now {"active" if variant.is_active else "inactive"}.'
        }, status=status.HTTP_200_OK)


# ============================================================================
# ORDER VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List orders",
        description="Retrieve a paginated list of orders. Users see their own orders, administrators see all orders for their events.",
        tags=["Orders"],
    ),
    retrieve=extend_schema(
        summary="Retrieve order details",
        description="Get detailed information about a specific order including all items and payment details.",
        tags=["Orders"],
    ),
    create=extend_schema(
        summary="Create order",
        description="Create a new order with items. Order starts in 'draft' status. Items are validated for stock and purchase eligibility.",
        tags=["Orders"],
    ),
    update=extend_schema(
        summary="Update order",
        description="Update order status. Status transitions are validated (e.g., draft → pending → processing → completed).",
        tags=["Orders"],
    ),
    partial_update=extend_schema(
        summary="Partially update order",
        description="Partially update order fields.",
        tags=["Orders"],
    ),
    destroy=extend_schema(
        summary="Delete order",
        description="Delete an order. Only draft orders can be deleted.",
        tags=["Orders"],
    ),
)
class OrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing orders.
    
    Provides:
    - List: Users see their own orders, admins see all
    - Retrieve: Order owner or administrators
    - Create: Authenticated users
    - Update: Order owner or administrators (limited to status changes)
    - Custom actions: submit, cancel, add_item
    
    Permissions:
    - List/Create: Authenticated users
    - Retrieve/Update/Delete: Order owner or administrative staff
    """
    
    queryset = Order.objects.select_related(
        'customer', 'attendee', 'attendee__event', 'payment', 'created_by', 'updated_by'
    ).prefetch_related('order_items__product_variant__product')
    permission_classes = [permissions.IsAuthenticated, IsOrderOwnerOrAdministrative]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrderFilterSet
    search_fields = ['order_reference_id', 'customer__email', 'attendee__email']
    ordering_fields = ['created_at', 'updated_at', 'total_amount', 'status']
    ordering = ['-created_at']
    lookup_field = 'order_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return OrderListSerializer
        elif self.action == 'create':
            return OrderCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return OrderUpdateSerializer
        return OrderDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all orders
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see only their own orders
        return queryset.filter(
            Q(customer=user) |
            Q(attendee__user=user)
        )
    
    @extend_schema(
        summary="Submit order",
        description="Submit an order, transitioning it from 'draft' to 'pending' status. Order must have at least one item. Stock is reserved when the order is submitted.",
        request=None,
        responses={
            200: {
                'description': 'Order submitted successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Order ORD-12345 submitted successfully.',
                            'order': {
                                'id': 1,
                                'order_id': 'uuid-here',
                                'order_reference_id': 'ORD-12345',
                                'status': 'pending',
                                'total_amount': 'GBP 50.00'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Cannot submit order (validation error)',
                'content': {
                    'application/json': {
                        'example': {
                            'error': 'Order must have at least one item before submission.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - not order owner or administrator'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'])
    def submit(self, request, order_id=None):
        """Submit the order (draft → pending)."""
        order = self.get_object()
        
        try:
            order.submit()
            serializer = self.get_serializer(order)
            return Response({
                'status': 'success',
                'message': f'Order {order.order_reference_id} submitted successfully.',
                'order': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Cancel order",
        description="Cancel an order, transitioning it to 'cancelled' status. Stock is automatically restored for all items in the order. Only non-completed orders can be cancelled.",
        request=None,
        responses={
            200: {
                'description': 'Order cancelled successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Order ORD-12345 cancelled successfully.',
                            'order': {
                                'id': 1,
                                'order_id': 'uuid-here',
                                'order_reference_id': 'ORD-12345',
                                'status': 'cancelled',
                                'total_amount': 'GBP 50.00'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Cannot cancel order',
                'content': {
                    'application/json': {
                        'example': {
                            'error': 'Cannot cancel a completed order.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - not order owner or administrator'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'])
    def cancel(self, request, order_id=None):
        """Cancel the order."""
        order = self.get_object()
        
        try:
            order.cancel()
            serializer = self.get_serializer(order)
            return Response({
                'status': 'success',
                'message': f'Order {order.order_reference_id} cancelled successfully.',
                'order': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Add item to order",
        description="Add an item to a draft order. Only draft orders can have items added. Stock availability and purchase limits are validated. Order total is automatically recalculated.",
        request=OrderItemCreateSerializer,
        responses={
            200: {
                'description': 'Item added successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Item added to order.',
                            'order_item': {
                                'id': 1,
                                'product_variant': 'uuid-here',
                                'quantity': 2,
                                'unit_price': 'GBP 25.00',
                                'total_price': 'GBP 50.00'
                            },
                            'order_total': 'GBP 50.00'
                        }
                    }
                }
            },
            400: {
                'description': 'Cannot add item (validation error)',
                'content': {
                    'application/json': {
                        'examples': {
                            'not_draft': {
                                'value': {'error': 'Can only add items to draft orders.'}
                            },
                            'insufficient_stock': {
                                'value': {'error': 'Insufficient stock for the selected product variant.'}
                            },
                            'invalid_variant': {
                                'value': {'product_variant_id': ['Product variant does not exist.']}
                            }
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - not order owner or administrator'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsOrderOwnerOrAdministrative], url_path='add-item')
    def add_item(self, request, order_id=None):
        """Add an item to the order."""
        order = self.get_object()
        
        if order.status != OrderStatusChoices.DRAFT:
            raise ValidationError('Can only add items to draft orders.')
        
        serializer = OrderItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        variant_id = serializer.validated_data['product_variant_id']
        quantity = serializer.validated_data['quantity']
        
        try:
            variant = ProductVariant.objects.get(variant_id=variant_id)
            order_item = order.add_order_item(variant, quantity)

            item_serializer = OrderItemSerializer(order_item, context={'request': request})
            return Response({
                'status': 'success',
                'message': 'Item added to order.',
                'order_item': item_serializer.data,
                'order_total': str(order.total_amount)
            }, status=status.HTTP_200_OK)
        except ProductVariant.DoesNotExist:
            raise ValidationError({'product_variant_id': 'Product variant does not exist.'})
        except Exception as e:
            raise ValidationError({'error': str(e)})


# ============================================================================
# ORDER ITEM VIEWSETS (Read-only)
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List order items",
        description="Retrieve a paginated list of order items. Access controlled by order ownership.",
        tags=["Order Items"],
    ),
    retrieve=extend_schema(
        summary="Retrieve order item details",
        description="Get detailed information about a specific order item.",
        tags=["Order Items"],
    ),
)
class OrderItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for OrderItem.
    
    Order items are created and managed through the Order viewset.
    This viewset provides read-only access for viewing items.
    
    Permissions:
    - Read: Order owner or administrative staff
    """
    
    queryset = OrderItem.objects.select_related(
        'order', 'order__customer', 'order__attendee', 'product_variant', 'product_variant__product'
    )
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsOrderOwnerOrAdministrative]
    pagination_class = StandardPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['order__created_at', 'quantity', 'total_price']
    ordering = ['-order__created_at']
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all order items
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see only their own order items
        return queryset.filter(
            Q(order__customer=user) |
            Q(order__attendee__user=user)
        )
