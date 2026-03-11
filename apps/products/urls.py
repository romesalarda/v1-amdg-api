"""
URL configuration for products app.

Defines API routes for all product-related endpoints with nested routing support.

Routes:
    - /api/products/categories/ - Product category management
    - /api/products/event-categories/ - Event-category associations
    - /api/products/list/ - Products with nested variants
    - /api/products/list/{product_product_id}/variants/ - Nested variants under products
    - /api/products/orders/ - Order management
    - /api/products/order-items/ - Read-only order items
    
Note: URL parameter names use underscores (product_product_id) for valid Python identifiers,
while action paths use hyphens (increment-stock) for URL readability.

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.urls import path, include, re_path
from rest_framework.routers import DefaultRouter

from apps.products.api.viewsets import (
    ProductCategoryViewSet,
    EventProductCategoryViewSet,
    ProductViewSet,
    ProductVariantViewSet,
    OrderViewSet,
    OrderItemViewSet,
)
from apps.products.api.statistics_viewsets import ProductStatisticsViewSet

app_name = 'products'

# Main router for top-level resources
router = DefaultRouter()

# Register category endpoints
router.register(r'categories', ProductCategoryViewSet, basename='productcategory')
router.register(r'event-categories', EventProductCategoryViewSet, basename='eventproductcategory')

# Register product endpoints (main route)
router.register(r'list', ProductViewSet, basename='product')

# Register order endpoints
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'order-items', OrderItemViewSet, basename='orderitem')

# Register statistics endpoints
router.register(r'statistics', ProductStatisticsViewSet, basename='product-statistics')

# Manually define nested routes for product variants
# This creates: /api/products/list/{product_product_id}/variants/
variant_list = ProductVariantViewSet.as_view({
    'get': 'list',
    'post': 'create'
})
variant_detail = ProductVariantViewSet.as_view({
    'get': 'retrieve',
    'put': 'update',
    'patch': 'partial_update',
    'delete': 'destroy'
})
variant_increment_stock = ProductVariantViewSet.as_view({
    'post': 'increment_stock'
})
variant_decrement_stock = ProductVariantViewSet.as_view({
    'post': 'decrement_stock'
})
variant_set_stock = ProductVariantViewSet.as_view({
    'post': 'set_stock'
})
variant_toggle_active = ProductVariantViewSet.as_view({
    'post': 'toggle_active'
})
variant_add_image = ProductVariantViewSet.as_view({
    'post': 'add_image'
})
variant_remove_image = ProductVariantViewSet.as_view({
    'post': 'remove_image'
})
variant_list_discounts = ProductVariantViewSet.as_view({
    'get': 'list_discounts'
})
variant_add_discount = ProductVariantViewSet.as_view({
    'post': 'add_discount'
})
variant_update_discount = ProductVariantViewSet.as_view({
    'patch': 'update_discount'
})
variant_remove_discount = ProductVariantViewSet.as_view({
    'delete': 'remove_discount'
})
variant_availability_windows = ProductVariantViewSet.as_view({
    'get': 'availability_windows'
})
variant_add_availability_window = ProductVariantViewSet.as_view({
    'post': 'add_availability_window'
})
variant_update_availability_window = ProductVariantViewSet.as_view({
    'patch': 'update_availability_window',
    'put': 'update_availability_window'
})
variant_remove_availability_window = ProductVariantViewSet.as_view({
    'delete': 'remove_availability_window'
})

urlpatterns = [
    # Include main router
    path('products/', include(router.urls)),
    
    # Nested routes for product variants
    path('products/list/<uuid:product_product_id>/variants/', variant_list, name='product-variants-list'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/', variant_detail, name='product-variants-detail'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/increment-stock/', variant_increment_stock, name='product-variants-increment-stock'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/decrement-stock/', variant_decrement_stock, name='product-variants-decrement-stock'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/set-stock/', variant_set_stock, name='product-variants-set-stock'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/toggle-active/', variant_toggle_active, name='product-variants-toggle-active'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/add-image/', variant_add_image, name='product-variants-add-image'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/remove-image/', variant_remove_image, name='product-variants-remove-image'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/discounts/', variant_list_discounts, name='product-variants-list-discounts'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/add-discount/', variant_add_discount, name='product-variants-add-discount'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/update-discount/<uuid:discount_id>/', variant_update_discount, name='product-variants-update-discount'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/remove-discount/<uuid:discount_id>/', variant_remove_discount, name='product-variants-remove-discount'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/availability-windows/', variant_availability_windows, name='product-variants-availability-windows'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/add-availability-window/', variant_add_availability_window, name='product-variants-add-availability-window'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/update-availability-window/', variant_update_availability_window, name='product-variants-update-availability-window'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/remove-availability-window/', variant_remove_availability_window, name='product-variants-remove-availability-window'),
]
