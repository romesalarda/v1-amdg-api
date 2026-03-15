"""
Event Statistics Serializers

Provides serializers for event statistics with dual format support (raw JSON and ECharts).
"""
from decimal import Decimal
from rest_framework import serializers
from typing import Dict, Any

from apps.events import formatters


class BaseStatisticsSerializer(serializers.Serializer):
    """
    Base serializer for statistics with format transformation support.
    
    Subclasses should implement format_for_echarts() method.
    """
    
    def to_representation(self, instance):
        """Override to support format transformation based on request context."""
        data = super().to_representation(instance)
        
        # Check if ECharts format is requested
        request = self.context.get('request')
        if request and request.query_params.get('format') == 'echarts':
            return self.format_for_echarts(data)
        
        return data
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform raw data to ECharts configuration.
        Should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement format_for_echarts()")


class EventStatusDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for event status distribution statistics."""
    
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of status counts with labels and percentages"
    )
    total_events = serializers.IntegerField(
        help_text="Total number of events"
    )
    filters_applied = serializers.DictField(
        required=False,
        help_text="Filters applied to the query"
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as donut chart with status colors."""
        return formatters.format_status_distribution_chart(
            data=data['distribution'],
            title='Event Status Distribution'
        )


class TypeDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for event type distribution statistics."""
    
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of event type counts"
    )
    total_events = serializers.IntegerField()
    filters_applied = serializers.DictField(
        required=False,
        help_text="Filters applied to the query"
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as pie chart."""
        return formatters.format_pie_chart(
            data=data['distribution'],
            title='Event Type Distribution'
        )


class OrganizationDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for organization distribution statistics."""
    
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of organization event counts"
    )
    total_events = serializers.IntegerField()
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as horizontal bar chart."""
        return formatters.format_bar_chart(
            data=data['distribution'],
            title='Events by Organization',
            x_axis_label='Number of Events',
            y_axis_label='Organization',
            orientation='horizontal'
        )


class UpcomingEventsSerializer(BaseStatisticsSerializer):
    """Serializer for upcoming events list."""
    
    events = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of upcoming events with details"
    )
    total_upcoming = serializers.IntegerField(
        help_text="Total count of upcoming events"
    )
    date_range = serializers.DictField(
        help_text="Start and end date of the range"
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as timeline/calendar chart."""
        return formatters.format_event_timeline_chart(
            data=data['events'],
            title=f"Upcoming Events ({data['total_upcoming']})"
        )


class EventRevenueOverviewSerializer(BaseStatisticsSerializer):
    """Serializer for revenue overview statistics."""
    
    total_revenue = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total revenue from all sources"
    )
    booking_revenue = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Revenue from bookings"
    )
    product_revenue = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Revenue from product sales"
    )
    donation_revenue = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Revenue from donations"
    )
    sponsor_revenue = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="Revenue from sponsorship payments"
    )
    breakdown = serializers.ListField(
        child=serializers.DictField(),
        help_text="Revenue breakdown by source"
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as revenue breakdown pie chart."""
        return formatters.format_revenue_breakdown_chart(
            data=data['breakdown'],
            title='Revenue Overview',
            subtitle=f"Total: ${data['total_revenue']}"
        )


class RevenueByEventSerializer(BaseStatisticsSerializer):
    """Serializer for per-event revenue statistics."""
    
    events = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of events with revenue data"
    )
    total_events = serializers.IntegerField()
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as stacked bar chart showing revenue breakdown."""
        show_breakdown = self.context.get('request').query_params.get('show_breakdown', 'false').lower() == 'true'
        
        return formatters.format_revenue_bar_chart(
            data=data['events'],
            title='Revenue by Event',
            show_multiple=show_breakdown
        )


class EventPaymentStatusDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for payment status distribution."""
    
    distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Payment status counts and amounts"
    )
    total_bookings = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_payments = serializers.IntegerField()
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as payment status pie chart."""
        return formatters.format_payment_status_chart(
            data=data['distribution'],
            title='Payment Status Distribution'
        )


class CapacityUtilizationSerializer(BaseStatisticsSerializer):
    """Serializer for capacity utilization statistics."""
    
    events = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of events with capacity data"
    )
    average_utilization = serializers.FloatField(
        help_text="Average capacity utilization percentage"
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as horizontal bar chart with color coding."""
        return formatters.format_capacity_utilization_chart(
            data=data['events'],
            title='Capacity Utilization by Event'
        )


class EventRegistrationTrendsSerializer(BaseStatisticsSerializer):
    """Serializer for registration trends over time."""
    
    trends = serializers.ListField(
        child=serializers.DictField(),
        help_text="Registration data points over time"
    )
    total_registrations = serializers.IntegerField()
    period = serializers.CharField(
        help_text="Time period (day, week, month)"
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as line chart with optional cumulative."""
        show_cumulative = self.context.get('request').query_params.get('cumulative', 'false').lower() == 'true'
        
        if show_cumulative and data.get('trends') and len(data['trends']) > 0 and 'cumulative' in data['trends'][0]:
            # Multi-line chart
            return {
                'title': {
                    'text': 'Registration Trends',
                    'left': 'center'
                },
                'tooltip': {
                    'trigger': 'axis'
                },
                'legend': {
                    'data': ['New Registrations', 'Cumulative'],
                    'top': 30
                },
                'xAxis': {
                    'type': 'category',
                    'data': [item['period'] for item in data['trends']]
                },
                'yAxis': {
                    'type': 'value'
                },
                'series': [
                    {
                        'name': 'New Registrations',
                        'type': 'line',
                        'data': [item['count'] for item in data['trends']],
                        'smooth': True
                    },
                    {
                        'name': 'Cumulative',
                        'type': 'line',
                        'data': [item['cumulative'] for item in data['trends']],
                        'smooth': True,
                        'itemStyle': {'color': '#91cc75'}
                    }
                ]
            }
        else:
            # Simple line chart
            chart_data = [
                {'label': item['period'], 'value': item['count']}
                for item in data['trends']
            ]
            return formatters.format_line_chart(
                data=chart_data,
                title='Registration Trends',
                x_axis_label='Period',
                y_axis_label='Registrations'
            )


class ReviewStatisticsSerializer(BaseStatisticsSerializer):
    """Serializer for event review statistics."""
    
    total_reviews = serializers.IntegerField()
    average_rating = serializers.FloatField()
    rating_distribution = serializers.ListField(
        child=serializers.DictField(),
        help_text="Count of reviews per rating (1-5)"
    )
    approval_status = serializers.DictField(
        help_text="Count of approved vs pending reviews"
    )
    top_rated_events = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of highest-rated events",
        required=False
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as rating distribution bar chart."""
        return formatters.format_rating_distribution_chart(
            data=data['rating_distribution'],
            title='Review Rating Distribution',
            average_rating=data['average_rating']
        )


class StaffAllocationSerializer(BaseStatisticsSerializer):
    """Serializer for staff allocation statistics."""
    
    events = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of events with staff counts"
    )
    total_staff_assignments = serializers.IntegerField()
    average_staff_per_event = serializers.FloatField()
    most_active_staff = serializers.ListField(
        child=serializers.DictField(),
        help_text="Staff members with most event assignments",
        required=False
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as horizontal bar chart."""
        return formatters.format_staff_allocation_chart(
            data=data['events'],
            title='Staff Allocation per Event'
        )


class BookingPackagePerformanceSerializer(BaseStatisticsSerializer):
    """Serializer for booking package performance statistics."""
    
    packages = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of packages with booking and revenue data"
    )
    total_packages = serializers.IntegerField()
    total_bookings = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=10, decimal_places=2)
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format as dual-axis chart (bookings + revenue)."""
        return formatters.format_booking_package_chart(
            data=data['packages'],
            title='Booking Package Performance'
        )


class SponsorPackagePerformanceSerializer(BaseStatisticsSerializer):
    """Serializer for sponsorship package performance statistics."""

    packages = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of sponsorship packages with utilization and revenue data"
    )
    total_packages = serializers.IntegerField()
    total_sponsors = serializers.IntegerField()
    status_summary = serializers.DictField()
    total_completed_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_refunded_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_net_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)

    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        distribution = [
            {'label': item.get('package_name', 'Unknown'), 'value': item.get('sponsors_count', 0)}
            for item in data.get('packages', [])
        ]
        return formatters.format_bar_chart(
            data=distribution,
            title='Sponsorship Package Utilization',
            x_axis_label='Package',
            y_axis_label='Sponsors'
        )


class OverviewStatisticsSerializer(BaseStatisticsSerializer):
    """Serializer for comprehensive overview statistics (dashboard)."""
    
    total_events = serializers.IntegerField()
    active_events = serializers.IntegerField()
    upcoming_events = serializers.IntegerField()
    completed_events = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_bookings = serializers.IntegerField()
    total_attendees = serializers.IntegerField()
    average_capacity_utilization = serializers.FloatField()
    average_rating = serializers.FloatField(required=False, allow_null=True)
    total_reviews = serializers.IntegerField()
    sponsorship = serializers.DictField(
        required=False,
        help_text="Sponsorship metrics including package utilization and revenue"
    )
    recent_trends = serializers.DictField(
        help_text="Recent activity trends",
        required=False
    )
    filters_applied = serializers.DictField(
        required=False,
        help_text="Filters applied to the query"
    )
    
    def format_for_echarts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format as dashboard grid with multiple charts.
        Returns a configuration for multiple chart containers.
        """
        # For overview, return structured data for multiple chart sections
        return {
            'dashboard': {
                'metrics': {
                    'total_events': data['total_events'],
                    'active_events': data['active_events'],
                    'upcoming_events': data['upcoming_events'],
                    'completed_events': data['completed_events'],
                    'total_revenue': str(data['total_revenue']),
                    'total_bookings': data['total_bookings'],
                    'total_attendees': data['total_attendees'],
                    'average_capacity_utilization': data['average_capacity_utilization'],
                    'average_rating': data.get('average_rating'),
                    'total_reviews': data['total_reviews']
                },
                'charts': {
                    'capacity_gauge': formatters.format_gauge_chart(
                        value=data['average_capacity_utilization'],
                        title='Average Capacity Utilization',
                        max_value=100,
                        unit='%'
                    ),
                    'rating_gauge': formatters.format_gauge_chart(
                        value=data.get('average_rating', 0) * 20,  # Convert to 0-100
                        title='Average Rating',
                        max_value=100,
                        unit='/5'
                    ) if data.get('average_rating') else None
                },
                'trends': data.get('recent_trends', {})
            }
        }
