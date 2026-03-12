"""
Product Statistics ViewSet

Provides comprehensive statistical analysis endpoints for product data.
All endpoints support both raw JSON and ECharts-ready formats via ?format parameter.

Usage:
    - Raw format: /api/products/statistics/product-overview/?format=raw
    - ECharts format: /api/products/statistics/product-overview/?format=echarts
    - Event-specific: /api/products/statistics/product-overview/?event_id=<uuid>
    - Date filtering: /api/products/statistics/order-trends/?date_from=2026-01-01&date_to=2026-03-01
    
Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, exceptions, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from django.utils import timezone
from datetime import datetime

from apps.products import statistics
from apps.products.api.serializers.statistics import (
    ProductOverviewSerializer,
    CategoryDistributionSerializer,
    ProductStatusDistributionSerializer,
    ProductTrendsSerializer,
    VariantStockOverviewSerializer,
    SizeDistributionSerializer,
    ColorDistributionSerializer,
    StockLevelsSerializer,
    OrderStatusDistributionSerializer,
    OrderTrendsSerializer,
    OrdersByProductSerializer,
    OrdersByCategorySerializer,
    ProductRevenueOverviewSerializer,
    RevenueByProductSerializer,
    RevenueByCategorySerializer,
    ProductRevenueTrendsSerializer,
    ProductRevenueBreakdownSerializer,
    ProductOverviewStatisticsSerializer,
)

import uuid


# ============================================================================
# COMMON PARAMETERS FOR DOCUMENTATION
# ============================================================================

EVENT_ID_PARAM = OpenApiParameter(
    name='event_id',
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.QUERY,
    description='Filter statistics to a specific event. If omitted, returns global statistics across all events.',
    required=False,
)

ORGANIZATION_ID_PARAM = OpenApiParameter(
    name='organization_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Filter statistics to a specific organization.',
    required=False,
)

CATEGORY_ID_PARAM = OpenApiParameter(
    name='category_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Filter statistics to a specific product category.',
    required=False,
)

IS_ACTIVE_PARAM = OpenApiParameter(
    name='is_active',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Filter by active/inactive status.',
    required=False,
)

VERIFIED_PARAM = OpenApiParameter(
    name='verified',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Filter by verified/unverified status.',
    required=False,
)

INCLUDE_DELETED_PARAM = OpenApiParameter(
    name='include_deleted',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Include soft-deleted records in statistics.',
    required=False,
    default=False,
)

DATE_FROM_PARAM = OpenApiParameter(
    name='date_from',
    type=OpenApiTypes.DATE,
    location=OpenApiParameter.QUERY,
    description='Start date for filtering (YYYY-MM-DD format). Applies to order/revenue statistics.',
    required=False,
)

DATE_TO_PARAM = OpenApiParameter(
    name='date_to',
    type=OpenApiTypes.DATE,
    location=OpenApiParameter.QUERY,
    description='End date for filtering (YYYY-MM-DD format). Applies to order/revenue statistics.',
    required=False,
)

GROUP_BY_PARAM = OpenApiParameter(
    name='group_by',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Time grouping for trends. "day" groups by day, "week" by week, "month" by month.',
    required=False,
    enum=['day', 'week', 'month'],
    default='day',
)

FORMAT_PARAM = OpenApiParameter(
    name='format',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Response format. "raw" returns plain JSON data. "echarts" returns ECharts-ready configuration.',
    required=False,
    enum=['raw', 'echarts'],
    default='raw',
)

LIMIT_PARAM = OpenApiParameter(
    name='limit',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Maximum number of items to return in results.',
    required=False,
    default=10,
)

CUMULATIVE_PARAM = OpenApiParameter(
    name='cumulative',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Include cumulative counts in trend data.',
    required=False,
    default=False,
)

STATUS_PARAM = OpenApiParameter(
    name='status',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Filter by order status (draft, pending, processing, completed, cancelled, refunded).',
    required=False,
)


# ============================================================================
# STATISTICS VIEWSET
# ============================================================================

import uuid
from rest_framework import exceptions

@extend_schema_view(
    list=extend_schema(
        summary="Available statistics endpoints",
        description="Lists all available product statistics endpoints with descriptions.",
        tags=["Product Statistics"],
    )
)
class ProductStatisticsViewSet(viewsets.GenericViewSet):
    """
    ViewSet for product statistics.
    
    Provides comprehensive statistical analysis of product data including:
    - Product overview and distribution (by category, status)
    - Product creation trends over time
    - Variant analytics (stock levels, size/color distribution)
    - Order analytics (status distribution, trends, top products)
    - Revenue analytics (overview, trends, breakdown by product/category)
    
    All endpoints support:
    - Event-specific filtering via ?event_id parameter
    - Organization filtering via ?organization_id parameter
    - Category filtering via ?category_id parameter
    - Raw or ECharts-ready format via ?format parameter
    - Soft-deleted record inclusion via ?include_deleted parameter
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ProductOverviewStatisticsSerializer  # Default serializer
    queryset = None  # Statistics viewset doesn't use queryset
    
    def get_queryset(self):
        # Statistics viewset doesn't use querysets, but this is required for schema generation
        if getattr(self, 'swagger_fake_view', False):
            return None
        return None
    
    def _get_common_filters(self, request):
        """Extract common filter parameters from request."""
        filters = {
            'event_id': request.query_params.get('event_id'),
            'organization_id': request.query_params.get('organization_id'),
            'include_deleted': request.query_params.get('include_deleted', 'false').lower() == 'true',
        }

        try:
            if filters['event_id']:
                filters['event_id'] = uuid.UUID(filters['event_id'])
        except (ValueError, TypeError):
            raise exceptions.ValidationError("Invalid event_id format. Must be a valid UUID.")
        
        # Optional integer fields
        if request.query_params.get('category_id'):
            try:
                filters['category_id'] = int(request.query_params.get('category_id'))
            except ValueError:
                pass
        
        # Optional boolean fields
        if request.query_params.get('is_active'):
            filters['is_active'] = request.query_params.get('is_active', '').lower() == 'true'
        
        if request.query_params.get('verified'):
            filters['verified'] = request.query_params.get('verified', '').lower() == 'true'
        
        # Date filters
        if request.query_params.get('date_from'):
            try:
                filters['date_from'] = datetime.strptime(
                    request.query_params.get('date_from'), '%Y-%m-%d'
                ).date()
            except ValueError:
                pass
        
        if request.query_params.get('date_to'):
            try:
                filters['date_to'] = datetime.strptime(
                    request.query_params.get('date_to'), '%Y-%m-%d'
                ).date()
            except ValueError:
                pass
        
        # Group by
        if request.query_params.get('group_by'):
            filters['group_by'] = request.query_params.get('group_by', 'day')
        
        # Limit
        if request.query_params.get('limit'):
            try:
                filters['limit'] = int(request.query_params.get('limit', 10))
            except ValueError:
                filters['limit'] = 10
        
        # Cumulative
        if request.query_params.get('cumulative'):
            filters['cumulative'] = request.query_params.get('cumulative', 'false').lower() == 'true'
        
        # Status
        if request.query_params.get('status'):
            filters['status'] = request.query_params.get('status')
        
        return filters
    
    def _add_filter_metadata(self, data, request):
        """Add filters_applied metadata to response."""
        filters_applied = {}
        
        if request.query_params.get('event_id'):
            filters_applied['event_id'] = request.query_params.get('event_id')
        
        if request.query_params.get('organization_id'):
            filters_applied['organization_id'] = request.query_params.get('organization_id')
        
        if request.query_params.get('category_id'):
            filters_applied['category_id'] = request.query_params.get('category_id')
        
        if request.query_params.get('is_active'):
            filters_applied['is_active'] = request.query_params.get('is_active')
        
        if request.query_params.get('verified'):
            filters_applied['verified'] = request.query_params.get('verified')
        
        if request.query_params.get('include_deleted'):
            filters_applied['include_deleted'] = request.query_params.get('include_deleted')
        
        if request.query_params.get('date_from'):
            filters_applied['date_from'] = request.query_params.get('date_from')
        
        if request.query_params.get('date_to'):
            filters_applied['date_to'] = request.query_params.get('date_to')
        
        if request.query_params.get('group_by'):
            filters_applied['group_by'] = request.query_params.get('group_by')
        
        if request.query_params.get('limit'):
            filters_applied['limit'] = request.query_params.get('limit')
        
        if request.query_params.get('cumulative'):
            filters_applied['cumulative'] = request.query_params.get('cumulative')
        
        if request.query_params.get('status'):
            filters_applied['status'] = request.query_params.get('status')
        
        if filters_applied:
            data['filters_applied'] = filters_applied
        
        return data
    
    def list(self, request):
        """List all available statistics endpoints."""
        endpoints = [
            {
                'name': 'Product Overview',
                'url': 'product-overview',
                'description': 'Overview of product counts by active/inactive status'
            },
            {
                'name': 'Category Distribution',
                'url': 'category-distribution',
                'description': 'Distribution of products across categories'
            },
            {
                'name': 'Status Distribution',
                'url': 'status-distribution',
                'description': 'Distribution by combined active/verified status'
            },
            {
                'name': 'Product Trends',
                'url': 'product-trends',
                'description': 'Product creation trends over time'
            },
            {
                'name': 'Variant Stock Overview',
                'url': 'variant-stock-overview',
                'description': 'Overview of variant stock levels'
            },
            {
                'name': 'Size Distribution',
                'url': 'size-distribution',
                'description': 'Distribution of variants by size'
            },
            {
                'name': 'Color Distribution',
                'url': 'color-distribution',
                'description': 'Distribution of variants by color'
            },
            {
                'name': 'Stock Levels',
                'url': 'stock-levels',
                'description': 'Distribution of variants by stock level ranges'
            },
            {
                'name': 'Order Status Distribution',
                'url': 'order-status-distribution',
                'description': 'Distribution of orders by status'
            },
            {
                'name': 'Order Trends',
                'url': 'order-trends',
                'description': 'Order creation trends over time'
            },
            {
                'name': 'Orders by Product',
                'url': 'orders-by-product',
                'description': 'Top products by order count'
            },
            {
                'name': 'Orders by Category',
                'url': 'orders-by-category',
                'description': 'Order count by product category'
            },
            {
                'name': 'Revenue Overview',
                'url': 'revenue-overview',
                'description': 'Overview of total revenue and metrics'
            },
            {
                'name': 'Revenue by Product',
                'url': 'revenue-by-product',
                'description': 'Top products by revenue'
            },
            {
                'name': 'Revenue by Category',
                'url': 'revenue-by-category',
                'description': 'Revenue breakdown by category'
            },
            {
                'name': 'Revenue Trends',
                'url': 'revenue-trends',
                'description': 'Revenue trends over time'
            },
            {
                'name': 'Revenue Breakdown',
                'url': 'revenue-breakdown',
                'description': 'Revenue breakdown by source (standalone vs package-linked)'
            },
            {
                'name': 'Overview',
                'url': 'overview',
                'description': 'Comprehensive dashboard with all key metrics'
            }
        ]
        return Response({
            'count': len(endpoints),
            'endpoints': endpoints
        })
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ProductOverviewSerializer},
        description="Get overview of product statistics including active/inactive counts.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='product-overview')
    def product_overview(self, request):
        """Get product overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_product_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
        )
        data = self._add_filter_metadata(data, request)
        serializer = ProductOverviewSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            IS_ACTIVE_PARAM,
            VERIFIED_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: CategoryDistributionSerializer},
        description="Get distribution of products across categories.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='category-distribution')
    def category_distribution(self, request):
        """Get category distribution statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_category_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            is_active=filters.get('is_active'),
            verified=filters.get('verified'),
        )
        data = self._add_filter_metadata(data, request)
        serializer = CategoryDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ProductStatusDistributionSerializer},
        description="Get distribution by active/inactive and verified/unverified status combinations.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='status-distribution')
    def status_distribution(self, request):
        """Get status distribution statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_status_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
        )
        data = self._add_filter_metadata(data, request)
        serializer = ProductStatusDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            GROUP_BY_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ProductTrendsSerializer},
        description="Get product creation trends over time grouped by day, week, or month.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='product-trends')
    def product_trends(self, request):
        """Get product trends statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_product_trends(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            group_by=filters.get('group_by', 'day'),
        )
        data = self._add_filter_metadata(data, request)
        serializer = ProductTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            IS_ACTIVE_PARAM,
            VERIFIED_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: VariantStockOverviewSerializer},
        description="Get overview of variant stock statistics including low stock and out of stock counts.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='variant-stock-overview')
    def variant_stock_overview(self, request):
        """Get variant stock overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_variant_stock_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
            is_active=filters.get('is_active'),
            verified=filters.get('verified'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = VariantStockOverviewSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            IS_ACTIVE_PARAM,
            VERIFIED_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: SizeDistributionSerializer},
        description="Get distribution of variants by size.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='size-distribution')
    def size_distribution(self, request):
        """Get size distribution statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_size_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
            is_active=filters.get('is_active'),
            verified=filters.get('verified'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = SizeDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            IS_ACTIVE_PARAM,
            VERIFIED_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ColorDistributionSerializer},
        description="Get distribution of variants by color with hex codes.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='color-distribution')
    def color_distribution(self, request):
        """Get color distribution statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_color_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
            is_active=filters.get('is_active'),
            verified=filters.get('verified'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = ColorDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            IS_ACTIVE_PARAM,
            VERIFIED_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: StockLevelsSerializer},
        description="Get distribution of variants by stock level ranges (out of stock, low, medium, high).",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='stock-levels')
    def stock_levels(self, request):
        """Get stock levels statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_stock_levels(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
            is_active=filters.get('is_active'),
            verified=filters.get('verified'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = StockLevelsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: OrderStatusDistributionSerializer},
        description="Get distribution of orders by status (draft, pending, processing, completed, etc.).",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='order-status-distribution')
    def order_status_distribution(self, request):
        """Get order status distribution statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_order_status_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = OrderStatusDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            STATUS_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            GROUP_BY_PARAM,
            CUMULATIVE_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: OrderTrendsSerializer},
        description="Get order creation trends over time with optional cumulative counts.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='order-trends')
    def order_trends(self, request):
        """Get order trends statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_order_trends(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            status=filters.get('status'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            group_by=filters.get('group_by', 'day'),
            cumulative=filters.get('cumulative', False),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = OrderTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            LIMIT_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: OrdersByProductSerializer},
        description="Get top products ranked by order count.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='orders-by-product')
    def orders_by_product(self, request):
        """Get orders by product statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_orders_by_product(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            limit=filters.get('limit', 10),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = OrdersByProductSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: OrdersByCategorySerializer},
        description="Get order counts grouped by product category.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='orders-by-category')
    def orders_by_category(self, request):
        """Get orders by category statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_orders_by_category(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = OrdersByCategorySerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ProductRevenueOverviewSerializer},
        description="Get comprehensive revenue overview including total revenue, order count, and average order value. Only counts completed orders.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-overview')
    def revenue_overview(self, request):
        """Get revenue overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = ProductRevenueOverviewSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            CATEGORY_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            LIMIT_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: RevenueByProductSerializer},
        description="Get top products ranked by revenue. Only counts completed orders.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-by-product')
    def revenue_by_product(self, request):
        """Get revenue by product statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_by_product(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            category_id=filters.get('category_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            limit=filters.get('limit', 10),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = RevenueByProductSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: RevenueByCategorySerializer},
        description="Get revenue grouped by product category. Only counts completed orders.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-by-category')
    def revenue_by_category(self, request):
        """Get revenue by category statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_by_category(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = RevenueByCategorySerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            GROUP_BY_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ProductRevenueTrendsSerializer},
        description="Get revenue trends over time. Only counts completed orders.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-trends')
    def revenue_trends(self, request):
        """Get revenue trends statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_trends(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            group_by=filters.get('group_by', 'day'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = ProductRevenueTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ProductRevenueBreakdownSerializer},
        description="Get revenue breakdown by source (standalone products vs package-linked products). Only counts completed orders.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-breakdown')
    def revenue_breakdown(self, request):
        """Get revenue breakdown statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_breakdown_by_source(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = ProductRevenueBreakdownSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            EVENT_ID_PARAM,
            ORGANIZATION_ID_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            INCLUDE_DELETED_PARAM,
            FORMAT_PARAM,
        ],
        responses={200: ProductOverviewStatisticsSerializer},
        description="Get comprehensive overview dashboard with all key metrics including products, variants, orders, and revenue.",
        tags=["Product Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        """Get comprehensive overview statistics."""
        filters = self._get_common_filters(request)

        data = statistics.calculate_overview_statistics(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = ProductOverviewStatisticsSerializer(data, context={'request': request})
        return Response(serializer.data)
