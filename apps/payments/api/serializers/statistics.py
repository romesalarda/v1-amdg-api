"""
Payment Statistics Serializers Module

Serializers for payment statistics endpoints.
Support both raw data format and ECharts-ready format based on context.
"""
from rest_framework import serializers
from django.utils import timezone
from typing import Dict, Any

from apps.attendee import formatters


class BasePaymentStatisticsSerializer(serializers.Serializer):
    """
    Base serializer for all payment statistics responses.
    Includes common metadata fields.
    """
    generated_at = serializers.DateTimeField(read_only=True, default=timezone.now)
    filters_applied = serializers.DictField(read_only=True, required=False)
    
    def to_representation(self, instance):
        """
        Transform data based on format parameter.
        If format=echarts, apply appropriate ECharts transformation.
        """
        representation = super().to_representation(instance)
        
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


# ============================================================================
# PAYMENT STATISTICS SERIALIZERS
# ============================================================================

class PaymentStatusDistributionSerializer(BasePaymentStatisticsSerializer):
    """Serializer for payment status distribution statistics."""
    total = serializers.IntegerField()
    distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format status distribution as pie chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_pie_chart(
            data=distribution,
            title='Payment Status Distribution',
            subtitle=f"Total: {instance.get('total', 0)} payments"
        )


class PaymentMethodDistributionSerializer(BasePaymentStatisticsSerializer):
    """Serializer for payment method distribution statistics."""
    total = serializers.IntegerField()
    total_with_method = serializers.IntegerField()
    total_without_method = serializers.IntegerField()
    distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format method distribution as donut chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_donut_chart(
            data=distribution,
            title='Payment Method Distribution',
            subtitle=f"Total: {instance.get('total_with_method', 0)} payments with method"
        )


class PaymentTrendsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for payment trends over time."""
    trends = serializers.ListField(
        child=serializers.DictField()
    )
    total = serializers.IntegerField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format trends as line chart."""
        trends = instance.get('trends', [])
        return formatters.format_line_chart(
            data=trends,
            title='Payment Registration Trends',
            x_axis_label='Date',
            y_axis_label='Number of Payments'
        )


class PaymentOverviewSerializer(BasePaymentStatisticsSerializer):
    """Serializer for payment overview statistics."""
    total_payments = serializers.IntegerField()
    total_amount = serializers.FloatField(allow_null=True)
    average_amount = serializers.FloatField(allow_null=True)
    status_breakdown = serializers.DictField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format overview with status breakdown as stacked bar."""
        status_breakdown = instance.get('status_breakdown', {})
        # Convert status breakdown to distribution format
        distribution = [
            {
                'label': data['label'],
                'value': data['count']
            }
            for status, data in status_breakdown.items()
            if data['count'] > 0
        ]
        return formatters.format_pie_chart(
            data=distribution,
            title='Payment Status Overview',
            subtitle=f"Total: {instance.get('total_payments', 0)} payments"
        )


# ============================================================================
# DISCOUNT STATISTICS SERIALIZERS
# ============================================================================

class DiscountUsageSerializer(BasePaymentStatisticsSerializer):
    """Serializer for discount usage statistics."""
    total_discounts = serializers.IntegerField()
    type_distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format discount types as pie chart."""
        distribution = instance.get('type_distribution', [])
        return formatters.format_pie_chart(
            data=distribution,
            title='Discount Type Distribution',
            subtitle=f"Total: {instance.get('total_discounts', 0)} active discounts"
        )


class DiscountRuleEffectivenessSerializer(BasePaymentStatisticsSerializer):
    """Serializer for discount rule effectiveness statistics."""
    total_rules = serializers.IntegerField()
    rules = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format rules as horizontal bar chart."""
        rules = instance.get('rules', [])
        # Convert to distribution format
        distribution = [
            {'label': rule['label'], 'value': rule['count']}
            for rule in rules
        ]
        return formatters.format_bar_chart(
            data=distribution,
            title='Discount Rule Types',
            x_axis_label='Number of Rules',
            y_axis_label='Rule Type',
            orientation='horizontal'
        )


class TopDiscountsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for top discounts statistics."""
    total_returned = serializers.IntegerField()
    limit = serializers.IntegerField()
    discounts = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format top discounts as bar chart."""
        discounts = instance.get('discounts', [])
        # Convert to distribution format
        distribution = [
            {'label': disc['name'], 'value': disc['rule_count']}
            for disc in discounts
        ]
        return formatters.format_bar_chart(
            data=distribution,
            title='Top Discounts by Rule Count',
            x_axis_label='Discount Name',
            y_axis_label='Number of Rules'
        )


# ============================================================================
# REFUND STATISTICS SERIALIZERS
# ============================================================================

class RefundRequestStatsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for refund request statistics."""
    total_requests = serializers.IntegerField()
    total_amount = serializers.FloatField(allow_null=True)
    status_distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format refund status as pie chart."""
        distribution = instance.get('status_distribution', [])
        return formatters.format_pie_chart(
            data=distribution,
            title='Refund Request Status Distribution',
            subtitle=f"Total: {instance.get('total_requests', 0)} requests"
        )


class RefundTrendsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for refund trends over time."""
    trends = serializers.ListField(
        child=serializers.DictField()
    )
    total_count = serializers.IntegerField()
    total_amount = serializers.FloatField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format trends as line chart with amount."""
        trends = instance.get('trends', [])
        # Use count for the chart
        chart_data = [
            {'date': t['date'], 'count': t['count']}
            for t in trends
        ]
        return formatters.format_line_chart(
            data=chart_data,
            title='Refund Request Trends',
            x_axis_label='Date',
            y_axis_label='Number of Refund Requests'
        )


class RefundProcessingTimesSerializer(BasePaymentStatisticsSerializer):
    """Serializer for refund processing time statistics."""
    total_processed = serializers.IntegerField()
    average_days = serializers.FloatField(allow_null=True)
    median_days = serializers.IntegerField(allow_null=True)
    min_days = serializers.IntegerField(allow_null=True)
    max_days = serializers.IntegerField(allow_null=True)
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format processing times as gauge chart."""
        avg_days = instance.get('average_days', 0)
        if avg_days is None:
            return None
        
        return formatters.format_gauge_chart(
            value=avg_days,
            title='Average Refund Processing Time',
            max_value=30,  # Assume 30 days is the maximum
            unit=' days'
        )


# ============================================================================
# DONATION STATISTICS SERIALIZERS
# ============================================================================

class DonationStatsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for donation statistics."""
    total_donations = serializers.IntegerField()
    total_amount = serializers.FloatField(allow_null=True)
    average_amount = serializers.FloatField(allow_null=True)
    status_distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format donation status as pie chart."""
        distribution = instance.get('status_distribution', [])
        return formatters.format_pie_chart(
            data=distribution,
            title='Donation Status Distribution',
            subtitle=f"Total: {instance.get('total_donations', 0)} donations"
        )


class DonationTrendsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for donation trends over time."""
    trends = serializers.ListField(
        child=serializers.DictField()
    )
    total_count = serializers.IntegerField()
    total_amount = serializers.FloatField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format trends as line chart with amount."""
        trends = instance.get('trends', [])
        # Use count for the chart
        chart_data = [
            {'date': t['date'], 'count': t['count']}
            for t in trends
        ]
        return formatters.format_line_chart(
            data=chart_data,
            title='Donation Trends',
            x_axis_label='Date',
            y_axis_label='Number of Donations'
        )


class TopDonorsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for top donors statistics."""
    total_returned = serializers.IntegerField()
    limit = serializers.IntegerField()
    donors = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format top donors as bar chart."""
        donors = instance.get('donors', [])
        # Convert to distribution format
        distribution = [
            {'label': donor['name'], 'value': donor['total_donated']}
            for donor in donors
        ]
        return formatters.format_bar_chart(
            data=distribution,
            title='Top Donors',
            x_axis_label='Donor',
            y_axis_label='Total Donated (£)',
            orientation='horizontal'
        )


# ============================================================================
# REVENUE STATISTICS SERIALIZERS
# ============================================================================

class PaymentRevenueOverviewSerializer(BasePaymentStatisticsSerializer):
    """Serializer for revenue overview statistics."""
    total_revenue = serializers.FloatField(allow_null=True)
    total_completed_payments = serializers.IntegerField()
    average_payment = serializers.FloatField(allow_null=True)
    total_refunded = serializers.FloatField(allow_null=True)
    refunded_payment_count = serializers.IntegerField()
    net_revenue = serializers.FloatField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue overview as bar chart."""
        distribution = [
            {'label': 'Gross Revenue', 'value': instance.get('total_revenue', 0) or 0},
            {'label': 'Refunded', 'value': instance.get('total_refunded', 0) or 0},
            {'label': 'Net Revenue', 'value': instance.get('net_revenue', 0) or 0}
        ]
        return formatters.format_bar_chart(
            data=distribution,
            title='Revenue Overview',
            x_axis_label='Category',
            y_axis_label='Amount (£)'
        )


class PaymentRevenueTrendsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for revenue trends over time."""
    trends = serializers.ListField(
        child=serializers.DictField()
    )
    total_revenue = serializers.FloatField()
    total_payments = serializers.IntegerField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue trends as area line chart."""
        trends = instance.get('trends', [])
        # Create data for line chart with revenue
        chart_data = [
            {'date': t['date'], 'count': t['revenue'] or 0}
            for t in trends
        ]
        return formatters.format_line_chart(
            data=chart_data,
            title='Revenue Trends',
            x_axis_label='Date',
            y_axis_label='Revenue (£)',
            smooth=True
        )


class RevenueByMethodSerializer(BasePaymentStatisticsSerializer):
    """Serializer for revenue by payment method statistics."""
    total_revenue = serializers.FloatField()
    methods = serializers.ListField(
        child=serializers.DictField()
    )
    without_method_revenue = serializers.FloatField(allow_null=True)
    without_method_count = serializers.IntegerField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue by method as pie chart."""
        methods = instance.get('methods', [])
        # Convert to distribution format
        distribution = [
            {'label': method['method'], 'value': method['revenue']}
            for method in methods
        ]
        # Add without method if present
        without_revenue = instance.get('without_method_revenue', 0)
        if without_revenue:
            distribution.append({
                'label': 'Without Method',
                'value': without_revenue
            })
        
        return formatters.format_pie_chart(
            data=distribution,
            title='Revenue by Payment Method',
            subtitle=f"Total: £{instance.get('total_revenue', 0):.2f}"
        )


class PaymentRevenueBreakdownSerializer(BasePaymentStatisticsSerializer):
    """Serializer for detailed revenue breakdown statistics."""
    gross_revenue = serializers.FloatField()
    completed_payment_count = serializers.IntegerField()
    refunded_amount = serializers.FloatField()
    refunded_payment_count = serializers.IntegerField()
    pending_refund_amount = serializers.FloatField()
    pending_refund_count = serializers.IntegerField()
    net_revenue = serializers.FloatField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format revenue breakdown as stacked bar chart."""
        distribution = [
            {'label': 'Gross Revenue', 'value': instance.get('gross_revenue', 0)},
            {'label': 'Refunded', 'value': -(instance.get('refunded_amount', 0))},  # Negative for visual
            {'label': 'Pending Refund', 'value': -(instance.get('pending_refund_amount', 0))},
            {'label': 'Net Revenue', 'value': instance.get('net_revenue', 0)}
        ]
        return formatters.format_bar_chart(
            data=distribution,
            title='Revenue Breakdown',
            x_axis_label='Category',
            y_axis_label='Amount (£)'
        )


class SponsorPackagePaymentStatusSerializer(BasePaymentStatisticsSerializer):
    """Serializer for sponsor package payment status statistics."""
    total_packages = serializers.IntegerField()
    total_payments = serializers.IntegerField()
    total_amount = serializers.FloatField()
    distribution = serializers.ListField(child=serializers.DictField())
    packages = serializers.ListField(child=serializers.DictField())

    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        distribution = instance.get('distribution', [])
        chart_data = [
            {'label': item.get('status', 'UNKNOWN'), 'value': item.get('count', 0)}
            for item in distribution
        ]
        return formatters.format_pie_chart(
            data=chart_data,
            title='Sponsor Package Payment Status',
            subtitle=f"Total Payments: {instance.get('total_payments', 0)}"
        )


# ============================================================================
# COMBINED OVERVIEW SERIALIZER
# ============================================================================

class PaymentOverviewStatsSerializer(BasePaymentStatisticsSerializer):
    """Serializer for combined overview statistics."""
    payments = serializers.DictField()
    revenue = serializers.DictField()
    credits = serializers.DictField(required=False)
    net_flow = serializers.DictField(required=False)
    discounts = serializers.DictField()
    refunds = serializers.DictField()
    donations = serializers.DictField()
    sponsors = serializers.DictField(required=False)
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format overview as multiple chart sections.
        For overview, we return None and let the frontend render multiple charts.
        """
        return None
