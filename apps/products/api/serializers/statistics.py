"""
Product Statistics Serializers

Provides serializers for product statistics endpoints with dual format support (raw JSON and ECharts).
Each serializer supports format transformation between raw data and ECharts configurations.

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from django.utils import timezone
from typing import Dict, Any

from apps.attendee.services import formatters

# IMPORTANT: This module contains product-specific statistics serializers.
# The ProductOverviewStatisticsSerializer is deliberately named to avoid
# conflicts with event statistics (OverviewStatistics) in OpenAPI schema generation.


class BaseProductStatisticsSerializer(serializers.Serializer):
    """
    Base serializer for all product statistics responses.
    Includes common metadata fields and format transformation support.
    """
    currency = serializers.DictField(read_only=True)
    generated_at = serializers.DateTimeField(
        read_only=True,
        default=timezone.now,
        help_text="Timestamp when statistics were generated"
    )
    filters_applied = serializers.DictField(
        read_only=True,
        required=False,
        help_text="Filters applied to the query"
    )
    
    def to_representation(self, instance):
        """
        Transform data based on format parameter.
        If format=echarts, apply appropriate ECharts transformation.
        """
        representation = super().to_representation(instance)
        representation['currency'] = self.context.get('currency', {})
        
        # Check if ECharts format is requested
        request = self.context.get('request')
        if request and request.query_params.get('format') == 'echarts':
            chart_data = self.format_for_echarts(representation, instance)
            if chart_data:
                representation['chart'] = chart_data
        
        return representation
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Override in subclasses to provide ECharts formatting.
        
        Args:
            representation: Serialized data representation
            instance: Original data instance
        
        Returns:
            ECharts configuration dict or None
        """
        return None


class ProductOverviewSerializer(BaseProductStatisticsSerializer):
    """Serializer for product overview statistics."""
    
    total_products = serializers.IntegerField(
        help_text="Total number of products"
    )
    active_products = serializers.IntegerField(
        help_text="Number of active products"
    )
    inactive_products = serializers.IntegerField(
        help_text="Number of inactive products"
    )
    verified_products = serializers.IntegerField(
        help_text="Number of verified products"
    )
    unverified_products = serializers.IntegerField(
        help_text="Number of unverified products"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Active/Inactive distribution breakdown"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format product overview as donut chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_donut_chart(
            data=distribution,
            title='Product Status Distribution',
            subtitle=f"Total: {instance.get('total_products', 0)} products"
        )


class CategoryDistributionSerializer(BaseProductStatisticsSerializer):
    """Serializer for category distribution statistics."""
    
    total_products = serializers.IntegerField(
        help_text="Total number of products"
    )
    total_categories = serializers.IntegerField(
        help_text="Total number of categories"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Product count per category"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format category distribution as pie chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_pie_chart(
            data=distribution,
            title='Products by Category',
            subtitle=f"Total: {instance.get('total_products', 0)} products"
        )


class ProductStatusDistributionSerializer(BaseProductStatisticsSerializer):
    """Serializer for status distribution statistics (active/inactive + verified/unverified combinations)."""
    
    total_products = serializers.IntegerField(
        help_text="Total number of products"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Distribution by status combinations"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format status distribution as donut chart with status colors."""
        distribution = instance.get('distribution', [])
        
        # Create donut chart with custom colors
        config = formatters.format_donut_chart(
            data=distribution,
            title='Product Status Breakdown',
            subtitle=f"Total: {instance.get('total_products', 0)} products"
        )
        
        # Apply custom colors based on status codes
        status_colors = {
            'active_verified': '#91cc75',      # Green
            'active_unverified': '#fac858',   # Yellow
            'inactive_verified': '#73c0de',   # Blue
            'inactive_unverified': '#ee6666'  # Red
        }
        
        series_data = config['series'][0]['data']
        for i, item in enumerate(distribution):
            code = item.get('code', '')
            if code in status_colors and i < len(series_data):
                series_data[i]['itemStyle'] = {'color': status_colors[code]}
        
        return config


class ProductTrendsSerializer(BaseProductStatisticsSerializer):
    """Serializer for product creation trends over time."""
    
    total_products = serializers.IntegerField(
        help_text="Total number of products in the filtered period"
    )
    group_by = serializers.CharField(
        help_text="Time grouping method (day, week, month)"
    )
    date_from = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Start date of the period"
    )
    date_to = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="End date of the period"
    )
    trends = serializers.ListField(
        child=serializers.DictField(),
        help_text="Product creation counts over time"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format product trends as line chart."""
        trends = instance.get('trends', [])
        return formatters.format_line_chart(
            data=trends,
            title='Product Creation Trends',
            x_axis_label='Date',
            y_axis_label='Products Created'
        )


class VariantStockOverviewSerializer(BaseProductStatisticsSerializer):
    """Serializer for variant stock overview statistics."""
    
    total_variants = serializers.IntegerField(
        help_text="Total number of product variants"
    )
    total_stock = serializers.IntegerField(
        help_text="Total stock quantity across all variants"
    )
    low_stock_count = serializers.IntegerField(
        help_text="Number of variants with stock < 10"
    )
    out_of_stock_count = serializers.IntegerField(
        help_text="Number of variants with stock = 0"
    )
    average_stock = serializers.FloatField(
        help_text="Average stock quantity per variant"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format variant stock overview as multiple gauge charts."""
        total_variants = instance.get('total_variants', 1)
        low_stock_count = instance.get('low_stock_count', 0)
        out_of_stock_count = instance.get('out_of_stock_count', 0)
        
        # Calculate percentages for gauges
        low_stock_percentage = (low_stock_count / total_variants * 100) if total_variants > 0 else 0
        out_of_stock_percentage = (out_of_stock_count / total_variants * 100) if total_variants > 0 else 0
        in_stock_percentage = 100 - low_stock_percentage - out_of_stock_percentage
        
        # Return data for multiple gauges (client will render them)
        return {
            'type': 'multiple_gauges',
            'gauges': [
                {
                    'title': 'In Stock',
                    'value': round(in_stock_percentage, 2),
                    'max': 100,
                    'unit': '%',
                    'color': '#91cc75'
                },
                {
                    'title': 'Low Stock',
                    'value': round(low_stock_percentage, 2),
                    'max': 100,
                    'unit': '%',
                    'color': '#fac858'
                },
                {
                    'title': 'Out of Stock',
                    'value': round(out_of_stock_percentage, 2),
                    'max': 100,
                    'unit': '%',
                    'color': '#ee6666'
                }
            ]
        }


class SizeDistributionSerializer(BaseProductStatisticsSerializer):
    """Serializer for size distribution statistics."""
    
    total_variants = serializers.IntegerField(
        help_text="Total number of product variants"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Variant count per size"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format size distribution as bar chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_bar_chart(
            data=distribution,
            title='Variants by Size',
            x_axis_label='Size',
            y_axis_label='Number of Variants'
        )


class ColorDistributionSerializer(BaseProductStatisticsSerializer):
    """Serializer for color distribution statistics."""
    
    total_variants = serializers.IntegerField(
        help_text="Total number of product variants"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Variant count per color with hex codes"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format color distribution as bar chart with color indicators."""
        distribution = instance.get('distribution', [])
        
        config = formatters.format_bar_chart(
            data=distribution,
            title='Variants by Color',
            x_axis_label='Color',
            y_axis_label='Number of Variants'
        )
        
        # Apply actual colors to bars based on hex codes
        series_data = config['series'][0]['data']
        for i, item in enumerate(distribution):
            color_code = item.get('code', '#5470c6')
            if i < len(series_data):
                config['series'][0]['data'][i] = {
                    'value': item['value'],
                    'itemStyle': {'color': color_code}
                }
        
        return config


class StockLevelsSerializer(BaseProductStatisticsSerializer):
    """Serializer for stock level distribution statistics."""
    
    total_variants = serializers.IntegerField(
        help_text="Total number of product variants"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Variant count per stock level range"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format stock levels as bar chart with color coding."""
        distribution = instance.get('distribution', [])
        
        config = formatters.format_bar_chart(
            data=distribution,
            title='Stock Level Distribution',
            x_axis_label='Stock Range',
            y_axis_label='Number of Variants'
        )
        
        # Apply color coding based on stock ranges
        stock_colors = {
            '0': '#ee6666',        # Red for out of stock
            '1-10': '#fac858',     # Yellow for low stock
            '11-50': '#91cc75',    # Green for medium
            '51-100': '#5470c6',   # Blue for good
            '100+': '#73c0de'      # Light blue for high
        }
        
        series_data = config['series'][0]['data']
        for i, item in enumerate(distribution):
            code = item.get('code', '')
            if code in stock_colors and i < len(series_data):
                config['series'][0]['data'][i] = {
                    'value': item['value'],
                    'itemStyle': {'color': stock_colors[code]}
                }
        
        return config


class OrderStatusDistributionSerializer(BaseProductStatisticsSerializer):
    """Serializer for order status distribution statistics."""
    
    total_orders = serializers.IntegerField(
        help_text="Total number of orders"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Order count per status"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format order status distribution as donut chart with status colors."""
        distribution = instance.get('distribution', [])
        
        config = formatters.format_donut_chart(
            data=distribution,
            title='Order Status Distribution',
            subtitle=f"Total: {instance.get('total_orders', 0)} orders"
        )
        
        # Apply status colors
        status_colors = {
            'draft': '#999999',
            'pending': '#fac858',
            'processing': '#5470c6',
            'completed': '#91cc75',
            'cancelled': '#ee6666',
            'refunded': '#fc8452'
        }
        
        series_data = config['series'][0]['data']
        for i, item in enumerate(distribution):
            code = item.get('code', '')
            if code in status_colors and i < len(series_data):
                series_data[i]['itemStyle'] = {'color': status_colors[code]}
        
        return config


class OrderTrendsSerializer(BaseProductStatisticsSerializer):
    """Serializer for order trends over time."""
    
    total_orders = serializers.IntegerField(
        help_text="Total number of orders in the filtered period"
    )
    group_by = serializers.CharField(
        help_text="Time grouping method (day, week, month)"
    )
    cumulative = serializers.BooleanField(
        help_text="Whether cumulative counts are included"
    )
    date_from = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Start date of the period"
    )
    date_to = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="End date of the period"
    )
    trends = serializers.ListField(
        child=serializers.DictField(),
        help_text="Order counts over time with optional cumulative"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format order trends as line chart with optional cumulative line."""
        trends = instance.get('trends', [])
        cumulative = instance.get('cumulative', False)
        
        if cumulative and trends and 'cumulative' in trends[0]:
            # Create multi-line chart with both regular and cumulative
            return formatters.format_multi_line_chart(
                data={
                    'Orders': trends,
                    'Cumulative': [{'date': t['date'], 'count': t.get('cumulative', 0)} for t in trends]
                },
                title='Order Trends',
                x_axis_label='Date',
                y_axis_label='Order Count'
            )
        else:
            # Single line chart
            return formatters.format_line_chart(
                data=trends,
                title='Order Trends',
                x_axis_label='Date',
                y_axis_label='Order Count'
            )


class OrdersByProductSerializer(BaseProductStatisticsSerializer):
    """Serializer for top products by order count."""
    
    total_products = serializers.IntegerField(
        help_text="Number of products in results"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Products ranked by order count"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format orders by product as horizontal bar chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_bar_chart(
            data=distribution,
            title='Top Products by Orders',
            x_axis_label='Number of Orders',
            y_axis_label='Product',
            orientation='horizontal'
        )


class OrdersByCategorySerializer(BaseProductStatisticsSerializer):
    """Serializer for orders by category."""
    
    total_orders = serializers.IntegerField(
        help_text="Total number of orders"
    )
    total_categories = serializers.IntegerField(
        help_text="Number of categories"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Order count per category"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format orders by category as bar chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_bar_chart(
            data=distribution,
            title='Orders by Category',
            x_axis_label='Category',
            y_axis_label='Number of Orders'
        )


class ProductRevenueOverviewSerializer(BaseProductStatisticsSerializer):
    """Serializer for revenue overview statistics."""
    
    total_revenue = serializers.FloatField(
        help_text="Total revenue from completed orders"
    )
    total_orders = serializers.IntegerField(
        help_text="Total number of orders"
    )
    average_order_value = serializers.FloatField(
        help_text="Average order value"
    )
    completed_orders = serializers.IntegerField(
        help_text="Number of completed orders"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue overview as metrics display."""
        return {
            'type': 'metrics',
            'metrics': [
                {
                    'title': 'Total Revenue',
                    'value': f"£{instance.get('total_revenue', 0):,.2f}",
                    'icon': 'currency'
                },
                {
                    'title': 'Completed Orders',
                    'value': instance.get('completed_orders', 0),
                    'icon': 'check'
                },
                {
                    'title': 'Average Order Value',
                    'value': f"£{instance.get('average_order_value', 0):,.2f}",
                    'icon': 'average'
                }
            ]
        }


class RevenueByProductSerializer(BaseProductStatisticsSerializer):
    """Serializer for revenue by product."""
    
    total_products = serializers.IntegerField(
        help_text="Number of products in results"
    )
    total_revenue = serializers.FloatField(
        help_text="Total revenue"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Products ranked by revenue"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue by product as horizontal bar chart with currency."""
        distribution = instance.get('distribution', [])
        
        config = formatters.format_bar_chart(
            data=distribution,
            title='Top Products by Revenue',
            x_axis_label='Revenue (£)',
            y_axis_label='Product',
            orientation='horizontal'
        )
        
        # Add currency formatting to tooltip
        config['tooltip'] = {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
            'formatter': '{b}: £{c}'
        }
        
        return config


class RevenueByCategorySerializer(BaseProductStatisticsSerializer):
    """Serializer for revenue by category."""
    
    total_revenue = serializers.FloatField(
        help_text="Total revenue"
    )
    total_categories = serializers.IntegerField(
        help_text="Number of categories"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Revenue per category"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue by category as bar chart with currency."""
        distribution = instance.get('distribution', [])
        
        config = formatters.format_bar_chart(
            data=distribution,
            title='Revenue by Category',
            x_axis_label='Category',
            y_axis_label='Revenue (£)'
        )
        
        # Add currency formatting to tooltip
        config['tooltip'] = {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
            'formatter': '{b}: £{c}'
        }
        
        return config


class ProductRevenueTrendsSerializer(BaseProductStatisticsSerializer):
    """Serializer for revenue trends over time."""
    
    total_revenue = serializers.FloatField(
        help_text="Total revenue in the filtered period"
    )
    group_by = serializers.CharField(
        help_text="Time grouping method (day, week, month)"
    )
    date_from = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Start date of the period"
    )
    date_to = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="End date of the period"
    )
    trends = serializers.ListField(
        child=serializers.DictField(),
        help_text="Revenue over time"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue trends as line chart with currency."""
        trends = instance.get('trends', [])
        
        # Transform trends for line chart (use 'revenue' as 'count')
        chart_data = [
            {'date': t['date'], 'count': t.get('revenue', 0)}
            for t in trends
        ]
        
        config = formatters.format_line_chart(
            data=chart_data,
            title='Revenue Trends',
            x_axis_label='Date',
            y_axis_label='Revenue (£)'
        )
        
        # Add currency formatting to tooltip
        config['tooltip'] = {
            'trigger': 'axis',
            'axisPointer': {'type': 'cross'},
            'formatter': '{b}: £{c}'
        }
        
        return config


class ProductRevenueBreakdownSerializer(BaseProductStatisticsSerializer):
    """Serializer for revenue breakdown by source."""
    
    total_revenue = serializers.FloatField(
        help_text="Total revenue"
    )
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Revenue breakdown by source (standalone vs package-linked)"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue breakdown as pie chart with currency."""
        distribution = instance.get('distribution', [])
        
        config = formatters.format_pie_chart(
            data=distribution,
            title='Revenue Breakdown by Source',
            subtitle=f"Total: £{instance.get('total_revenue', 0):,.2f}"
        )
        
        # Add currency formatting to tooltip
        config['tooltip'] = {
            'trigger': 'item',
            'formatter': '{a} <br/>{b}: £{c} ({d}%)'
        }
        
        return config


class ProductOverviewStatisticsSerializer(BaseProductStatisticsSerializer):
    """Serializer for comprehensive product overview statistics."""
    
    product_summary = serializers.DictField(
        help_text="Product count summary"
    )
    variant_summary = serializers.DictField(
        help_text="Variant and stock summary"
    )
    order_summary = serializers.DictField(
        help_text="Order count by status"
    )
    revenue_summary = serializers.DictField(
        help_text="Revenue metrics"
    )
    top_products_by_revenue = serializers.ListField(
        child=serializers.DictField(),
        help_text="Top 5 products by revenue"
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format overview as dashboard with multiple charts."""
        return {
            'type': 'dashboard',
            'sections': [
                {
                    'title': 'Product Summary',
                    'type': 'metrics',
                    'data': instance.get('product_summary', {})
                },
                {
                    'title': 'Stock Summary',
                    'type': 'metrics',
                    'data': instance.get('variant_summary', {})
                },
                {
                    'title': 'Order Summary',
                    'type': 'donut',
                    'data': [
                        {'label': k.replace('_', ' ').title(), 'value': v}
                        for k, v in instance.get('order_summary', {}).items()
                        if k != 'total_orders'
                    ]
                },
                {
                    'title': 'Top Products by Revenue',
                    'type': 'bar',
                    'data': instance.get('top_products_by_revenue', [])
                },
                {
                    'title': 'Revenue Summary',
                    'type': 'metrics',
                    'data': instance.get('revenue_summary', {})
                }
            ]
        }
