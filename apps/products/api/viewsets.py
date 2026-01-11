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
        description="Create a new product. Event administrators can create products for their events. Supports image upload via resource IDs and category associations.",
        tags=["Products"],
    ),
    update=extend_schema(
        summary="Update product",
        description="Update an existing product. Only administrators can modify products.",
        tags=["Products"],
    ),
    partial_update=extend_schema(
        summary="Partially update product",
        description="Partially update a product.",
        tags=["Products"],
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
        description="Add an image to the product. Provide a resource ID that points to an uploaded image resource.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'resource_id': {'type': 'integer', 'description': 'ID of the image resource'},
                    'is_main': {'type': 'boolean', 'description': 'Whether this should be the main product image'},
                },
                'required': ['resource_id'],
            }
        },
        responses={200: {'description': 'Image added successfully'}},
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def add_image(self, request, product_id=None):
        """Add an image to the product."""
        product = self.get_object()
        resource_id = request.data.get('resource_id')
        is_main = request.data.get('is_main', False)
        
        if not resource_id:
            raise ValidationError({'resource_id': 'Resource ID is required.'})
        
        try:
            resource = Resource.objects.get(id=resource_id)
            product.add_product_image(resource, is_main=is_main)
            return Response({
                'status': 'success',
                'message': f'Image added to product {product.title}.'
            }, status=status.HTTP_200_OK)
        except Resource.DoesNotExist:
            raise ValidationError({'resource_id': 'Resource does not exist.'})
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Remove image from product",
        description="Remove an image from the product.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'resource_id': {'type': 'integer', 'description': 'ID of the image resource to remove'},
                },
                'required': ['resource_id'],
            }
        },
        responses={200: {'description': 'Image removed successfully'}},
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
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
        description="Toggle the is_active status of a product. Only administrators can perform this action.",
        responses={200: {'description': 'Status toggled successfully'}},
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
        description="Atomically increment the stock quantity of a variant. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'amount': {'type': 'integer', 'description': 'Amount to increment (must be positive)', 'example': 10},
                },
                'required': ['amount'],
            }
        },
        responses={
            200: {'description': 'Stock incremented successfully'},
            400: {'description': 'Invalid amount or would exceed max stock'},
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
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
        description="Atomically decrement the stock quantity of a variant. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'amount': {'type': 'integer', 'description': 'Amount to decrement (must be positive)', 'example': 5},
                },
                'required': ['amount'],
            }
        },
        responses={
            200: {'description': 'Stock decremented successfully'},
            400: {'description': 'Invalid amount or insufficient stock'},
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
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
        description="Set the stock quantity to a specific value. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'stock_quantity': {'type': 'integer', 'description': 'New stock quantity (must be non-negative)', 'example': 50},
                },
                'required': ['stock_quantity'],
            }
        },
        responses={200: {'description': 'Stock set successfully'}},
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
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
        description="Toggle the is_active status of a variant. Only administrators can perform this action.",
        responses={200: {'description': 'Status toggled successfully'}},
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
        description="Submit an order, transitioning it from 'draft' to 'pending' status. Order must have at least one item.",
        responses={
            200: {'description': 'Order submitted successfully'},
            400: {'description': 'Cannot submit order (validation error)'},
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
        description="Cancel an order, transitioning it to 'cancelled' status. Stock is automatically restored.",
        responses={
            200: {'description': 'Order cancelled successfully'},
            400: {'description': 'Cannot cancel order'},
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
        description="Add an item to a draft order. Only draft orders can have items added.",
        request=OrderItemCreateSerializer,
        responses={
            200: {'description': 'Item added successfully'},
            400: {'description': 'Cannot add item (validation error)'},
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsOrderOwnerOrAdministrative])
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
