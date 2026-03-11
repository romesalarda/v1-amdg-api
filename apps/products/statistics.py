"""
Product Statistics Calculation Module

This module provides calculation functions for product-related statistics.
Each function returns structured data suitable for both raw JSON and ECharts formatting.

Functions are designed to be:
- Event-scoped or global (via optional event_id parameter)
- Organization-scoped (via optional organization_id parameter)
- Category-scoped (via optional category_id parameter)
- Efficient (using Django ORM aggregations)
- Extensible (easy to add new statistics)
- Testable (pure functions with clear inputs/outputs)
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import (
    Count, Sum, Avg, F, Q, Case, When, Value, 
    IntegerField, FloatField, DecimalField
)
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, Coalesce
from django.utils import timezone

from apps.products.models.product import Product, ProductVariant, ProductSizeChoices
from apps.products.models.orders import Order, OrderItem, OrderStatusChoices
from apps.products.models.category import EventProductCategory


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_base_queryset(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    verified: Optional[bool] = None,
    **kwargs
):
    """
    Get base product queryset with common filters applied.
    
    Args:
        event_id: Optional event UUID to filter products
        organization_id: Optional organization ID to filter by event's organization
        category_id: Optional category ID to filter products
        is_active: Optional filter for active/inactive products
        verified: Optional filter for verified/unverified products
    
    Returns:
        Filtered queryset of products
    """
    queryset = Product.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    if category_id:
        # Products are linked to categories through EventProductCategory
        queryset = queryset.filter(event_product_categories__category_id=category_id).distinct()
    
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)
    
    if verified is not None:
        queryset = queryset.filter(verified=verified)
    
    return queryset


def _get_orders_base_queryset(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_deleted: bool = False
):
    """
    Get base order queryset with common filters applied.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID to filter by event's organization
        status: Optional order status filter
        date_from: Start date for filtering (filters created_at)
        date_to: End date for filtering (filters created_at)
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Filtered queryset of orders
    """
    queryset = Order.all_objects.all()
    
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    
    if event_id:
        queryset = queryset.filter(attendee__event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(attendee__event__organisation_id=organization_id)
    
    if status:
        queryset = queryset.filter(status=status)
    
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    
    return queryset


# ============================================================================
# PRODUCT STATISTICS (Step 1)
# ============================================================================

def calculate_product_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calculate overview of product statistics.
    
    Args:
        event_id: Optional event UUID to filter products
        organization_id: Optional organization ID
        category_id: Optional category ID
    
    Returns:
        Dictionary with product overview data:
        {
            'total_products': int,
            'active_products': int,
            'inactive_products': int,
            'verified_products': int,
            'unverified_products': int,
            'distribution': [
                {'label': 'Active', 'value': int, 'percentage': float},
                {'label': 'Inactive', 'value': int, 'percentage': float}
            ],
            'generated_at': str
        }
    """
    queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        category_id=category_id
    )
    
    total_products = queryset.count()
    active_products = queryset.filter(is_active=True).count()
    inactive_products = queryset.filter(is_active=False).count()
    verified_products = queryset.filter(verified=True).count()
    unverified_products = queryset.filter(verified=False).count()
    
    distribution = [
        {
            'label': 'Active',
            'value': active_products,
            'percentage': round((active_products / total_products * 100), 2) if total_products > 0 else 0
        },
        {
            'label': 'Inactive',
            'value': inactive_products,
            'percentage': round((inactive_products / total_products * 100), 2) if total_products > 0 else 0
        }
    ]
    
    return {
        'total_products': total_products,
        'active_products': active_products,
        'inactive_products': inactive_products,
        'verified_products': verified_products,
        'unverified_products': unverified_products,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_category_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    verified: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Calculate distribution of products by category.
    
    Args:
        event_id: Optional event UUID to filter products
        organization_id: Optional organization ID
        is_active: Optional filter for active/inactive products
        verified: Optional filter for verified/unverified products
    
    Returns:
        Dictionary with category distribution data:
        {
            'total_products': int,
            'total_categories': int,
            'distribution': [
                {
                    'label': str,  # category name
                    'value': int,  # product count
                    'percentage': float,
                    'category_id': int
                },
                ...
            ],
            'generated_at': str
        }
    """
    queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        is_active=is_active,
        verified=verified
    )
    
    total_products = queryset.count()
    
    # Get category counts through EventProductCategory
    category_counts = EventProductCategory.objects.filter(
        product__in=queryset
    ).values(
        'category__name',
        'category_id'
    ).annotate(
        count=Count('product', distinct=True)
    ).order_by('-count')
    
    distribution = []
    for item in category_counts:
        count = item['count']
        distribution.append({
            'label': item['category__name'],
            'value': count,
            'percentage': round((count / total_products * 100), 2) if total_products > 0 else 0,
            'category_id': item['category_id']
        })
    
    total_categories = len(distribution)
    
    return {
        'total_products': total_products,
        'total_categories': total_categories,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_status_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Calculate distribution of products by active/inactive and verification status.
    
    Args:
        event_id: Optional event UUID to filter products
        organization_id: Optional organization ID
        category_id: Optional category ID
    
    Returns:
        Dictionary with status distribution data:
        {
            'total_products': int,
            'distribution': [
                {
                    'label': str,  # e.g., 'Active & Verified'
                    'value': int,
                    'percentage': float,
                    'code': str  # e.g., 'active_verified'
                },
                ...
            ],
            'generated_at': str
        }
    """
    queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        category_id=category_id
    )
    
    total_products = queryset.count()
    
    # Calculate all combinations
    active_verified = queryset.filter(is_active=True, verified=True).count()
    active_unverified = queryset.filter(is_active=True, verified=False).count()
    inactive_verified = queryset.filter(is_active=False, verified=True).count()
    inactive_unverified = queryset.filter(is_active=False, verified=False).count()
    
    distribution = [
        {
            'label': 'Active & Verified',
            'value': active_verified,
            'percentage': round((active_verified / total_products * 100), 2) if total_products > 0 else 0,
            'code': 'active_verified'
        },
        {
            'label': 'Active & Unverified',
            'value': active_unverified,
            'percentage': round((active_unverified / total_products * 100), 2) if total_products > 0 else 0,
            'code': 'active_unverified'
        },
        {
            'label': 'Inactive & Verified',
            'value': inactive_verified,
            'percentage': round((inactive_verified / total_products * 100), 2) if total_products > 0 else 0,
            'code': 'inactive_verified'
        },
        {
            'label': 'Inactive & Unverified',
            'value': inactive_unverified,
            'percentage': round((inactive_unverified / total_products * 100), 2) if total_products > 0 else 0,
            'code': 'inactive_unverified'
        }
    ]
    
    return {
        'total_products': total_products,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_product_trends(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    group_by: str = 'day'
) -> Dict[str, Any]:
    """
    Calculate product creation trends over time.
    
    Args:
        event_id: Optional event UUID to filter products
        organization_id: Optional organization ID
        category_id: Optional category ID
        date_from: Start date for filtering
        date_to: End date for filtering
        group_by: 'day', 'week', or 'month'
    
    Returns:
        Dictionary with product trend data:
        {
            'total_products': int,
            'group_by': str,
            'date_from': str or None,
            'date_to': str or None,
            'trends': [
                {'date': str, 'count': int},
                ...
            ],
            'generated_at': str
        }
    """
    queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        category_id=category_id
    )
    
    # Apply date filtering
    if date_from:
        queryset = queryset.filter(added_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(added_at__date__lte=date_to)
    
    # Group by time period
    if group_by == 'week':
        trunc_func = TruncWeek
    elif group_by == 'month':
        trunc_func = TruncMonth
    else:  # day
        trunc_func = TruncDate
    
    trends = queryset.annotate(
        period=trunc_func('added_at')
    ).values('period').annotate(
        count=Count('id')
    ).order_by('period')
    
    trend_data = [
        {
            'date': item['period'].isoformat() if item['period'] else None,
            'count': item['count']
        }
        for item in trends
    ]
    
    return {
        'total_products': queryset.count(),
        'group_by': group_by,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'trends': trend_data,
        'generated_at': timezone.now().isoformat(),
        'period_days': (date_to - date_from).days if date_from and date_to else None
    }


# ============================================================================
# VARIANT ANALYTICS (Step 2)
# ============================================================================

def calculate_variant_stock_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    verified: Optional[bool] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate overview of variant stock statistics.
    
    Args:
        event_id: Optional event UUID to filter by product's event
        organization_id: Optional organization ID
        category_id: Optional category ID
        is_active: Optional filter for active/inactive variants
        verified: Optional filter for verified/unverified variants
        include_deleted: Whether to include soft-deleted variants
    
    Returns:
        Dictionary with variant stock overview:
        {
            'total_variants': int,
            'total_stock': int,
            'low_stock_count': int,  # stock < 10
            'out_of_stock_count': int,  # stock == 0
            'average_stock': float,
            'generated_at': str
        }
    """
    product_queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        category_id=category_id,
        # include_deleted=include_deleted
    )
    
    variant_queryset = ProductVariant.objects.filter(product__in=product_queryset)
        
    if is_active is not None:
        variant_queryset = variant_queryset.filter(is_active=is_active)
    
    if verified is not None:
        variant_queryset = variant_queryset.filter(verified=verified)
    
    total_variants = variant_queryset.count()
    total_stock = variant_queryset.aggregate(
        total=Coalesce(Sum('stock_quantity'), 0)
    )['total']
    
    low_stock_count = variant_queryset.filter(
        stock_quantity__lt=10,
        stock_quantity__gt=0
    ).count()
    
    out_of_stock_count = variant_queryset.filter(stock_quantity=0).count()
    
    average_stock = variant_queryset.aggregate(
        avg=Avg('stock_quantity')
    )['avg']
    
    return {
        'total_variants': total_variants,
        'total_stock': total_stock,
        'in_stock_count': total_variants - out_of_stock_count,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'average_stock': round(average_stock, 2) if average_stock else 0,
        'generated_at': timezone.now().isoformat()
    }


def calculate_size_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    verified: Optional[bool] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of variants by size.
    
    Args:
        event_id: Optional event UUID to filter by product's event
        organization_id: Optional organization ID
        category_id: Optional category ID
        is_active: Optional filter for active/inactive variants
        verified: Optional filter for verified/unverified variants
        include_deleted: Whether to include soft-deleted variants
    
    Returns:
        Dictionary with size distribution data:
        {
            'total_variants': int,
            'distribution': [
                {
                    'label': str,  # size label (e.g., 'Small')
                    'value': int,  # variant count
                    'percentage': float,
                    'code': str  # size code (e.g., 'SM')
                },
                ...
            ],
            'generated_at': str
        }
    """
    product_queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        category_id=category_id,
    )
    
    variant_queryset = ProductVariant.objects.filter(product__in=product_queryset)
        
    if is_active is not None:
        variant_queryset = variant_queryset.filter(is_active=is_active)
    
    if verified is not None:
        variant_queryset = variant_queryset.filter(verified=verified)
    
    total_variants = variant_queryset.count()
    
    # Get size counts
    size_counts = variant_queryset.values('size').annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in size_counts:
        size_code = item['size']
        count = item['count']
        # Get display label from choices
        size_label = dict(ProductSizeChoices.choices).get(size_code, size_code)
        
        distribution.append({
            'label': size_label,
            'value': count,
            'percentage': round((count / total_variants * 100), 2) if total_variants > 0 else 0,
            'code': size_code
        })
    
    return {
        'total_variants': total_variants,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_color_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    verified: Optional[bool] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of variants by color.
    
    Args:
        event_id: Optional event UUID to filter by product's event
        organization_id: Optional organization ID
        category_id: Optional category ID
        is_active: Optional filter for active/inactive variants
        verified: Optional filter for verified/unverified variants
        include_deleted: Whether to include soft-deleted variants
    
    Returns:
        Dictionary with color distribution data:
        {
            'total_variants': int,
            'distribution': [
                {
                    'label': str,  # color hex (e.g., '#FF0000')
                    'value': int,  # variant count
                    'percentage': float,
                    'code': str  # same as label (hex value)
                },
                ...
            ],
            'generated_at': str
        }
    """
    product_queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        category_id=category_id,
        include_deleted=include_deleted
    )
    
    variant_queryset = ProductVariant.objects.filter(product__in=product_queryset)
    
    # if not include_deleted:
    #     variant_queryset = variant_queryset.filter(deleted_at__isnull=True)
    
    if is_active is not None:
        variant_queryset = variant_queryset.filter(is_active=is_active)
    
    if verified is not None:
        variant_queryset = variant_queryset.filter(verified=verified)
    
    total_variants = variant_queryset.count()
    
    # Get color counts
    color_counts = variant_queryset.values('color').annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in color_counts:
        color_hex = item['color']
        count = item['count']
        
        distribution.append({
            'label': color_hex,
            'value': count,
            'percentage': round((count / total_variants * 100), 2) if total_variants > 0 else 0,
            'code': color_hex
        })
    
    return {
        'total_variants': total_variants,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_stock_levels(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    verified: Optional[bool] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of variants by stock level ranges.
    
    Args:
        event_id: Optional event UUID to filter by product's event
        organization_id: Optional organization ID
        category_id: Optional category ID
        is_active: Optional filter for active/inactive variants
        verified: Optional filter for verified/unverified variants
        include_deleted: Whether to include soft-deleted variants
    
    Returns:
        Dictionary with stock level distribution:
        {
            'total_variants': int,
            'distribution': [
                {
                    'label': str,  # range label (e.g., '1-10')
                    'value': int,  # variant count
                    'percentage': float,
                    'code': str  # range code
                },
                ...
            ],
            'generated_at': str
        }
    """
    product_queryset = _get_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        category_id=category_id,
    )
    
    variant_queryset = ProductVariant.objects.filter(product__in=product_queryset)
        
    if is_active is not None:
        variant_queryset = variant_queryset.filter(is_active=is_active)
    
    if verified is not None:
        variant_queryset = variant_queryset.filter(verified=verified)
    
    total_variants = variant_queryset.count()
    
    # Calculate stock level ranges
    stock_0 = variant_queryset.filter(stock_quantity=0).count()
    stock_1_10 = variant_queryset.filter(stock_quantity__gte=1, stock_quantity__lte=10).count()
    stock_11_50 = variant_queryset.filter(stock_quantity__gte=11, stock_quantity__lte=50).count()
    stock_51_100 = variant_queryset.filter(stock_quantity__gte=51, stock_quantity__lte=100).count()
    stock_100_plus = variant_queryset.filter(stock_quantity__gt=100).count()
    
    distribution = [
        {
            'label': 'Out of Stock (0)',
            'value': stock_0,
            'percentage': round((stock_0 / total_variants * 100), 2) if total_variants > 0 else 0,
            'code': '0'
        },
        {
            'label': 'Low Stock (1-10)',
            'value': stock_1_10,
            'percentage': round((stock_1_10 / total_variants * 100), 2) if total_variants > 0 else 0,
            'code': '1-10'
        },
        {
            'label': 'Medium Stock (11-50)',
            'value': stock_11_50,
            'percentage': round((stock_11_50 / total_variants * 100), 2) if total_variants > 0 else 0,
            'code': '11-50'
        },
        {
            'label': 'Good Stock (51-100)',
            'value': stock_51_100,
            'percentage': round((stock_51_100 / total_variants * 100), 2) if total_variants > 0 else 0,
            'code': '51-100'
        },
        {
            'label': 'High Stock (100+)',
            'value': stock_100_plus,
            'percentage': round((stock_100_plus / total_variants * 100), 2) if total_variants > 0 else 0,
            'code': '100+'
        }
    ]
    
    return {
        'total_variants': total_variants,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


# ============================================================================
# ORDER ANALYTICS (Step 3)
# ============================================================================

def calculate_order_status_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of orders by status.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with order status distribution:
        {
            'total_orders': int,
            'distribution': [
                {
                    'label': str,  # status label (e.g., 'Completed')
                    'value': int,  # order count
                    'percentage': float,
                    'code': str  # status code (e.g., 'completed')
                },
                ...
            ],
            'generated_at': str
        }
    """
    queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    total_orders = queryset.count()
    
    # Get status counts
    status_counts = queryset.values('status').annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in status_counts:
        status_code = item['status']
        count = item['count']
        # Get display label from choices
        status_label = dict(OrderStatusChoices.choices).get(status_code, status_code)
        
        distribution.append({
            'label': status_label,
            'value': count,
            'percentage': round((count / total_orders * 100), 2) if total_orders > 0 else 0,
            'code': status_code
        })
    
    return {
        'total_orders': total_orders,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_order_trends(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    group_by: str = 'day',
    cumulative: bool = False,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate order creation trends over time.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        status: Optional order status filter
        date_from: Start date for filtering
        date_to: End date for filtering
        group_by: 'day', 'week', or 'month'
        cumulative: Whether to include cumulative counts
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with order trend data:
        {
            'total_orders': int,
            'group_by': str,
            'cumulative': bool,
            'date_from': str or None,
            'date_to': str or None,
            'trends': [
                {'date': str, 'count': int, 'cumulative': int (if cumulative=True)},
                ...
            ],
            'generated_at': str
        }
    """
    queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Group by time period
    if group_by == 'week':
        trunc_func = TruncWeek
    elif group_by == 'month':
        trunc_func = TruncMonth
    else:  # day
        trunc_func = TruncDate
    
    trends = queryset.annotate(
        period=trunc_func('created_at')
    ).values('period').annotate(
        count=Count('id')
    ).order_by('period')
    
    # Calculate cumulative if requested
    cumulative_count = 0
    trend_data = []
    for item in trends:
        cumulative_count += item['count']
        data_point = {
            'date': item['period'].isoformat() if item['period'] else None,
            'count': item['count']
        }
        if cumulative:
            data_point['cumulative'] = cumulative_count
        trend_data.append(data_point)
    
    return {
        'total_orders': queryset.count(),
        'group_by': group_by,
        'cumulative': cumulative,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'trends': trend_data,
        'generated_at': timezone.now().isoformat(),
        'period_days': (date_to - date_from).days if date_from and date_to else None
    }


def calculate_orders_by_product(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 10,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate top products by order count.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        category_id: Optional category ID to filter products
        date_from: Start date for filtering
        date_to: End date for filtering
        limit: Maximum number of products to return
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with products ranked by order count:
        {
            'total_products': int,
            'distribution': [
                {
                    'label': str,  # product title
                    'value': int,  # order count
                    'product_id': str,
                    'percentage': float
                },
                ...
            ],
            'generated_at': str
        }
    """
    order_queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Get product filter for category
    product_filter = Q()
    if category_id:
        product_filter = Q(product_variant__product__event_product_categories__category_id=category_id)
    
    # Count orders per product
    order_items = OrderItem.objects.filter(
        order__in=order_queryset,
        product_variant__isnull=False
    ).filter(product_filter)
    
    product_counts = order_items.values(
        'product_variant__product__title',
        'product_variant__product__product_id'
    ).annotate(
        count=Count('order', distinct=True)
    ).order_by('-count')[:limit]
    
    total_products = product_counts.count()
    total_orders = order_queryset.count()
    
    distribution = []
    for item in product_counts:
        count = item['count']
        distribution.append({
            'label': item['product_variant__product__title'],
            'value': count,
            'product_id': str(item['product_variant__product__product_id']),
            'percentage': round((count / total_orders * 100), 2) if total_orders > 0 else 0
        })
    
    return {
        'total_products': total_products,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_orders_by_category(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate orders grouped by product category.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with orders by category:
        {
            'total_orders': int,
            'total_categories': int,
            'distribution': [
                {
                    'label': str,  # category name
                    'value': int,  # order count
                    'category_id': int,
                    'percentage': float
                },
                ...
            ],
            'generated_at': str
        }
    """
    order_queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    total_orders = order_queryset.count()
    
    # Count orders per category through order items
    order_items = OrderItem.objects.filter(
        order__in=order_queryset,
        product_variant__isnull=False
    )
    
    category_counts = order_items.values(
        'product_variant__product__event_product_categories__category__name',
        'product_variant__product__event_product_categories__category_id'
    ).annotate(
        count=Count('order', distinct=True)
    ).order_by('-count')
    
    distribution = []
    for item in category_counts:
        if item['product_variant__product__event_product_categories__category__name']:
            count = item['count']
            distribution.append({
                'label': item['product_variant__product__event_product_categories__category__name'],
                'value': count,
                'category_id': item['product_variant__product__event_product_categories__category_id'],
                'percentage': round((count / total_orders * 100), 2) if total_orders > 0 else 0
            })
    
    total_categories = len(distribution)
    
    return {
        'total_orders': total_orders,
        'total_categories': total_categories,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


# ============================================================================
# REVENUE ANALYTICS (Step 4)
# ============================================================================

def calculate_revenue_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate comprehensive revenue overview.
    ONLY counts orders with status='completed'.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with revenue overview:
        {
            'total_revenue': float,
            'total_orders': int,
            'average_order_value': float,
            'completed_orders': int,
            'generated_at': str
        }
    """
    # Only count completed orders for revenue
    queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        status=OrderStatusChoices.COMPLETED,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    total_orders = queryset.count()
    
    # Calculate total revenue from completed orders
    revenue_data = queryset.aggregate(
        total=Coalesce(Sum('total_amount'), Decimal('0.00'))
    )
    
    total_revenue = float(revenue_data['total'])
    average_order_value = (total_revenue / total_orders) if total_orders > 0 else 0
    
    return {
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'average_order_value': round(average_order_value, 2),
        'completed_orders': total_orders,
        'generated_at': timezone.now().isoformat()
    }


def calculate_revenue_by_product(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    category_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 10,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate top products by revenue.
    ONLY counts orders with status='completed'.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        category_id: Optional category ID to filter products
        date_from: Start date for filtering
        date_to: End date for filtering
        limit: Maximum number of products to return
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with products ranked by revenue:
        {
            'total_products': int,
            'total_revenue': float,
            'distribution': [
                {
                    'label': str,  # product title
                    'value': float,  # revenue
                    'product_id': str,
                    'percentage': float
                },
                ...
            ],
            'generated_at': str
        }
    """
    # Only count completed orders for revenue
    order_queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        status=OrderStatusChoices.COMPLETED,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Get product filter for category
    product_filter = Q()
    if category_id:
        product_filter = Q(product_variant__product__event_product_categories__category_id=category_id)
    
    # Calculate revenue per product
    order_items = OrderItem.objects.filter(
        order__in=order_queryset,
        product_variant__isnull=False
    ).filter(product_filter)
    
    product_revenue = order_items.values(
        'product_variant__product__title',
        'product_variant__product__product_id'
    ).annotate(
        revenue=Coalesce(Sum('total_price'), Decimal('0.00'))
    ).order_by('-revenue')[:limit]
    
    # Calculate total revenue for percentage
    total_revenue_data = order_items.aggregate(
        total=Coalesce(Sum('total_price'), Decimal('0.00'))
    )
    total_revenue = float(total_revenue_data['total'])
    
    distribution = []
    for item in product_revenue:
        revenue = float(item['revenue'])
        distribution.append({
            'label': item['product_variant__product__title'],
            'value': revenue,
            'product_id': str(item['product_variant__product__product_id']),
            'percentage': round((revenue / total_revenue * 100), 2) if total_revenue > 0 else 0
        })
    
    total_products = len(distribution)
    
    return {
        'total_products': total_products,
        'total_revenue': total_revenue,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_revenue_by_category(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue grouped by product category.
    ONLY counts orders with status='completed'.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with revenue by category:
        {
            'total_revenue': float,
            'total_categories': int,
            'distribution': [
                {
                    'label': str,  # category name
                    'value': float,  # revenue
                    'category_id': int,
                    'percentage': float
                },
                ...
            ],
            'generated_at': str
        }
    """
    # Only count completed orders for revenue
    order_queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        status=OrderStatusChoices.COMPLETED,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Calculate revenue per category through order items
    order_items = OrderItem.objects.filter(
        order__in=order_queryset,
        product_variant__isnull=False
    )
    
    category_revenue = order_items.values(
        'product_variant__product__event_product_categories__category__name',
        'product_variant__product__event_product_categories__category_id'
    ).annotate(
        revenue=Coalesce(Sum('total_price'), Decimal('0.00'))
    ).order_by('-revenue')
    
    # Calculate total revenue for percentage
    total_revenue_data = order_items.aggregate(
        total=Coalesce(Sum('total_price'), Decimal('0.00'))
    )
    total_revenue = float(total_revenue_data['total'])
    
    distribution = []
    for item in category_revenue:
        if item['product_variant__product__event_product_categories__category__name']:
            revenue = float(item['revenue'])
            distribution.append({
                'label': item['product_variant__product__event_product_categories__category__name'],
                'value': revenue,
                'category_id': item['product_variant__product__event_product_categories__category_id'],
                'percentage': round((revenue / total_revenue * 100), 2) if total_revenue > 0 else 0
            })
    
    total_categories = len(distribution)
    
    return {
        'total_revenue': total_revenue,
        'total_categories': total_categories,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


def calculate_revenue_trends(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    group_by: str = 'day',
    include_deleted: bool = False,
) -> Dict[str, Any]:
    """
    Calculate revenue trends over time.
    ONLY counts orders with status='completed'.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
        group_by: 'day', 'week', or 'month'
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with revenue trend data:
        {
            'total_revenue': float,
            'group_by': str,
            'date_from': str or None,
            'date_to': str or None,
            'trends': [
                {'date': str, 'revenue': float, 'count': int},
                ...
            ],
            'generated_at': str
        }
    """
    # Only count completed orders for revenue
    queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        status=OrderStatusChoices.COMPLETED,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Group by time period
    if group_by == 'week':
        trunc_func = TruncWeek
    elif group_by == 'month':
        trunc_func = TruncMonth
    else:  # day
        trunc_func = TruncDate
    
    trends = queryset.annotate(
        period=trunc_func('created_at')
    ).values('period').annotate(
        revenue=Coalesce(Sum('total_amount'), Decimal('0.00')),
        count=Count('id')
    ).order_by('period')
    
    trend_data = []
    total_revenue = 0
    for item in trends:
        revenue = float(item['revenue'])
        total_revenue += revenue
        trend_data.append({
            'date': item['period'].isoformat() if item['period'] else None,
            'revenue': revenue,
            'count': item['count']
        })

    period_days = (date_to - date_from).days if date_from and date_to else None
    return {
        'total_revenue': total_revenue,
        'group_by': group_by,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'trends': trend_data,
        'generated_at': timezone.now().isoformat(),
        'period_days': period_days
    }


def calculate_revenue_breakdown_by_source(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue breakdown by source (standalone vs package-linked).
    ONLY counts orders with status='completed'.
    
    Args:
        event_id: Optional event UUID to filter orders
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Dictionary with revenue breakdown by source:
        {
            'total_revenue': float,
            'distribution': [
                {
                    'label': 'Standalone Products',
                    'value': float,
                    'percentage': float,
                    'code': 'standalone'
                },
                {
                    'label': 'Package-Linked Products',
                    'value': float,
                    'percentage': float,
                    'code': 'package'
                }
            ],
            'generated_at': str
        }
    """
    # Only count completed orders for revenue
    queryset = _get_orders_base_queryset(
        event_id=event_id,
        organization_id=organization_id,
        status=OrderStatusChoices.COMPLETED,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Calculate standalone revenue (no booking_package)
    standalone_revenue = queryset.filter(
        booking_package__isnull=True
    ).aggregate(
        total=Coalesce(Sum('total_amount'), Decimal('0.00'))
    )['total']
    
    # Calculate package-linked revenue (has booking_package)
    package_revenue = queryset.filter(
        booking_package__isnull=False
    ).aggregate(
        total=Coalesce(Sum('total_amount'), Decimal('0.00'))
    )['total']
    
    total_revenue = float(standalone_revenue) + float(package_revenue)
    
    distribution = [
        {
            'label': 'Standalone Products',
            'value': float(standalone_revenue),
            'percentage': round((float(standalone_revenue) / total_revenue * 100), 2) if total_revenue > 0 else 0,
            'code': 'standalone'
        },
        {
            'label': 'Package-Linked Products',
            'value': float(package_revenue),
            'percentage': round((float(package_revenue) / total_revenue * 100), 2) if total_revenue > 0 else 0,
            'code': 'package'
        }
    ]
    
    return {
        'total_revenue': total_revenue,
        'distribution': distribution,
        'generated_at': timezone.now().isoformat()
    }


# ============================================================================
# COMPREHENSIVE OVERVIEW (Step 5)
# ============================================================================

def calculate_overview_statistics(
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate comprehensive overview statistics for dashboard.
    Combines all metrics from product, variant, order, and revenue statistics.
    
    Args:
        event_id: Optional event UUID to filter data
        organization_id: Optional organization ID
        date_from: Start date for filtering (applies to orders/revenue)
        date_to: End date for filtering (applies to orders/revenue)
        include_deleted: Whether to include soft-deleted records
    
    Returns:
        Dictionary with comprehensive overview:
        {
            'product_summary': {
                'total_products': int,
                'active_products': int,
                'inactive_products': int,
                'verified_products': int,
                'unverified_products': int
            },
            'variant_summary': {
                'total_variants': int,
                'total_stock': int,
                'low_stock_count': int,
                'out_of_stock_count': int
            },
            'order_summary': {
                'total_orders': int,
                'draft': int,
                'pending': int,
                'processing': int,
                'completed': int,
                'cancelled': int,
                'refunded': int
            },
            'revenue_summary': {
                'total_revenue': float,
                'completed_orders': int,
                'average_order_value': float
            },
            'top_products_by_revenue': [
                {'label': str, 'value': float, 'product_id': str},
                ...
            ],
            'generated_at': str
        }
    """

    

    # Get product summary
    product_overview = calculate_product_overview(
        event_id=event_id,
        organization_id=organization_id,
    )
    
    # Get variant summary
    variant_overview = calculate_variant_stock_overview(
        event_id=event_id,
        organization_id=organization_id,
        include_deleted=include_deleted
    )
    
    # Get order status breakdown
    order_status = calculate_order_status_distribution(
        event_id=event_id,
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Get revenue overview
    revenue_overview = calculate_revenue_overview(
        event_id=event_id,
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        include_deleted=include_deleted
    )
    
    # Get top 5 products by revenue
    top_products = calculate_revenue_by_product(
        event_id=event_id,
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        limit=5,
        include_deleted=include_deleted
    )
    
    # Build order summary from distribution
    order_summary = {'total_orders': order_status['total_orders']}
    for item in order_status['distribution']:
        order_summary[item['code']] = item['value']
    
    return {
        'product_summary': {
            'total_products': product_overview['total_products'],
            'active_products': product_overview['active_products'],
            'inactive_products': product_overview['inactive_products'],
            'verified_products': product_overview['verified_products'],
            'unverified_products': product_overview['unverified_products']
        },
        'variant_summary': {
            'total_variants': variant_overview['total_variants'],
            'total_stock': variant_overview['total_stock'],
            'low_stock_count': variant_overview['low_stock_count'],
            'out_of_stock_count': variant_overview['out_of_stock_count']
        },
        'order_summary': order_summary,
        'revenue_summary': {
            'total_revenue': revenue_overview['total_revenue'],
            'completed_orders': revenue_overview['completed_orders'],
            'average_order_value': revenue_overview['average_order_value']
        },
        'top_products_by_revenue': top_products['distribution'],
        'generated_at': timezone.now().isoformat()
    }
