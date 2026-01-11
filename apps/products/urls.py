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

urlpatterns = [
    # Include main router
    path('products/', include(router.urls)),
    
    # Nested routes for product variants
    path('products/list/<uuid:product_product_id>/variants/', variant_list, name='product-variants-list'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/', variant_detail, name='product-variants-detail'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/increment_stock/', variant_increment_stock, name='product-variants-increment-stock'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/decrement_stock/', variant_decrement_stock, name='product-variants-decrement-stock'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/set_stock/', variant_set_stock, name='product-variants-set-stock'),
    path('products/list/<uuid:product_product_id>/variants/<uuid:variant_id>/toggle_active/', variant_toggle_active, name='product-variants-toggle-active'),
]
