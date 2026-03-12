"""
Event Statistics ViewSet

Provides comprehensive statistics endpoints for event-related data with dual format support.
"""
from datetime import datetime, timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from apps.events.services import statistics
from apps.events.api.serializers.statistics import (
    EventStatusDistributionSerializer,
    TypeDistributionSerializer,
    OrganizationDistributionSerializer,
    UpcomingEventsSerializer,
    EventRevenueOverviewSerializer,
    RevenueByEventSerializer,
    EventPaymentStatusDistributionSerializer,
    CapacityUtilizationSerializer,
    EventRegistrationTrendsSerializer,
    ReviewStatisticsSerializer,
    StaffAllocationSerializer,
    BookingPackagePerformanceSerializer,
    OverviewStatisticsSerializer,
)


# Common OpenAPI parameters
EVENT_ID_PARAM = OpenApiParameter(
    name='event_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Filter by specific event ID',
    required=False
)

EVENT_TYPE_PARAM = OpenApiParameter(
    name='event_type_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Filter by event type ID',
    required=False
)

ORGANIZATION_PARAM = OpenApiParameter(
    name='organization_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Filter by organization ID',
    required=False
)

STATUS_PARAM = OpenApiParameter(
    name='status',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Filter by event status (DRAFTING, PUBLISHED, OPEN, IN_PROGRESS, COMPLETED, CLOSED, CANCELLED, POSTPONED)',
    required=False
)

FORMAT_PARAM = OpenApiParameter(
    name='format',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Response format: "raw" for JSON data or "echarts" for ECharts configuration',
    required=False,
    enum=['raw', 'echarts'],
    default='raw'
)

DATE_FROM_PARAM = OpenApiParameter(
    name='date_from',
    type=OpenApiTypes.DATE,
    location=OpenApiParameter.QUERY,
    description='Start date for filtering (YYYY-MM-DD)',
    required=False
)

DATE_TO_PARAM = OpenApiParameter(
    name='date_to',
    type=OpenApiTypes.DATE,
    location=OpenApiParameter.QUERY,
    description='End date for filtering (YYYY-MM-DD)',
    required=False
)

DAYS_AHEAD_PARAM = OpenApiParameter(
    name='days_ahead',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Number of days ahead to consider for upcoming events',
    required=False,
    default=30
)

LIMIT_PARAM = OpenApiParameter(
    name='limit',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Maximum number of items to return',
    required=False,
    default=10
)

PERIOD_PARAM = OpenApiParameter(
    name='period',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Time period grouping for trends',
    required=False,
    enum=['day', 'week', 'month'],
    default='month'
)

CUMULATIVE_PARAM = OpenApiParameter(
    name='cumulative',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Include cumulative data in trends',
    required=False,
    default=False
)

SORT_BY_PARAM = OpenApiParameter(
    name='sort_by',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Sort field for results',
    required=False
)

SHOW_BREAKDOWN_PARAM = OpenApiParameter(
    name='show_breakdown',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Show detailed breakdown in results',
    required=False,
    default=False
)

import uuid

class EventStatisticsViewSet(viewsets.GenericViewSet):
    """
    ViewSet for retrieving event statistics with dual format support.
    
    All endpoints support ?format=raw (default) or ?format=echarts for
    ECharts-compatible chart configurations.
    """
    
    permission_classes = [IsAuthenticated]
    
    def _get_common_filters(self, request):
        """Extract common filter parameters from request."""
        from datetime import datetime
        from rest_framework.exceptions import ValidationError
        
        filters = {}
        
        if request.query_params.get('event_id'):
            try:
                event_id = request.query_params['event_id']
                uuid_obj = uuid.UUID(event_id, version=4)
                filters['event_id'] = str(uuid_obj)
            except ValueError:
                raise ValidationError({'event_id': 'Invalid UUID format for event_id.'})
            
        if request.query_params.get('event_type_id'):
            filters['event_type_id'] = int(request.query_params['event_type_id'])
        
        if request.query_params.get('organization_id'):
            filters['organization_id'] = int(request.query_params['organization_id'])
        
        if request.query_params.get('status'):
            filters['status'] = request.query_params['status']
        
        if request.query_params.get('date_from'):
            date_str = request.query_params['date_from']
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
                filters['date_from'] = date_str
            except ValueError:
                raise ValidationError({'date_from': 'Invalid date format. Use YYYY-MM-DD.'})
        
        if request.query_params.get('date_to'):
            date_str = request.query_params['date_to']
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
                filters['date_to'] = date_str
            except ValueError:
                raise ValidationError({'date_to': 'Invalid date format. Use YYYY-MM-DD.'})
        
        return filters
    
    def _add_filter_metadata(self, data, request):
        """Add applied filters to response metadata."""
        filters = self._get_common_filters(request)
        if filters:
            data['filters_applied'] = filters
        return data
    
    @extend_schema(
        summary='Get comprehensive event statistics overview',
        description='Returns a dashboard-style overview of all event statistics including counts, revenue, capacity, and ratings.',
        parameters=[
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            STATUS_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            FORMAT_PARAM
        ],
        responses={200: OverviewStatisticsSerializer},
        examples=[
            OpenApiExample(
                'Overview Example',
                value={
                    'total_events': 45,
                    'active_events': 12,
                    'upcoming_events': 8,
                    'completed_events': 20,
                    'total_revenue': '125000.00',
                    'total_bookings': 450,
                    'total_attendees': 389,
                    'average_capacity_utilization': 78.5,
                    'average_rating': 4.3,
                    'total_reviews': 67
                },
                response_only=True
            )
        ]
    )
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get comprehensive overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_overview_statistics(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = OverviewStatisticsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get event status distribution',
        description='Returns the distribution of events across different statuses (drafting, published, open, etc.).',
        parameters=[
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            FORMAT_PARAM
        ],
        responses={200: EventStatusDistributionSerializer},
        examples=[
            OpenApiExample(
                'Status Distribution Example',
                value={
                    'distribution': [
                        {'label': 'Open', 'code': 'OPEN', 'value': 15, 'percentage': 33.3},
                        {'label': 'Published', 'code': 'PUBLISHED', 'value': 10, 'percentage': 22.2},
                        {'label': 'Completed', 'code': 'COMPLETED', 'value': 20, 'percentage': 44.4}
                    ],
                    'total_events': 45
                },
                response_only=True
            )
        ]
    )
    @action(detail=False, methods=['get'], url_path='status-distribution')
    def status_distribution(self, request):
        """Get event status distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_status_distribution(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = EventStatusDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get event type distribution',
        description='Returns the distribution of events by type (workshop, conference, etc.).',
        parameters=[
            ORGANIZATION_PARAM,
            STATUS_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            FORMAT_PARAM
        ],
        responses={200: TypeDistributionSerializer},
        examples=[
            OpenApiExample(
                'Type Distribution Example',
                value={
                    'distribution': [
                        {'label': 'Workshop', 'value': 20, 'percentage': 44.4},
                        {'label': 'Conference', 'value': 15, 'percentage': 33.3},
                        {'label': 'Seminar', 'value': 10, 'percentage': 22.2}
                    ],
                    'total_events': 45
                },
                response_only=True
            )
        ]
    )
    @action(detail=False, methods=['get'], url_path='type-distribution')
    def type_distribution(self, request):
        """Get event type distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_type_distribution(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = TypeDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get organization distribution',
        description='Returns the distribution of events by organization.',
        parameters=[
            EVENT_TYPE_PARAM,
            STATUS_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            LIMIT_PARAM,
            FORMAT_PARAM
        ],
        responses={200: OrganizationDistributionSerializer}
    )
    @action(detail=False, methods=['get'], url_path='organization-distribution')
    def organization_distribution(self, request):
        """Get organization distribution."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 10))
        
        data = statistics.calculate_organization_distribution(limit=limit, **filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = OrganizationDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get upcoming events',
        description='Returns list of upcoming events within specified timeframe.',
        parameters=[
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            DAYS_AHEAD_PARAM,
            FORMAT_PARAM
        ],
        responses={200: UpcomingEventsSerializer},
        examples=[
            OpenApiExample(
                'Upcoming Events Example',
                value={
                    'events': [
                        {
                            'id': 1,
                            'title': 'Spring Workshop',
                            'start_datetime': '2024-03-15T10:00:00Z',
                            'end_datetime': '2024-03-15T16:00:00Z',
                            'type': 'Workshop',
                            'status': 'OPEN'
                        }
                    ],
                    'total_upcoming': 8,
                    'date_range': {
                        'from': '2024-03-01',
                        'to': '2024-03-31'
                    }
                },
                response_only=True
            )
        ]
    )
    @action(detail=False, methods=['get'], url_path='upcoming')
    def upcoming_events(self, request):
        """Get upcoming events."""
        filters = self._get_common_filters(request)
        days_ahead = int(request.query_params.get('days_ahead', 30))
        
        data = statistics.calculate_upcoming_events(days_ahead=days_ahead, **filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = UpcomingEventsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get revenue overview',
        description='Returns comprehensive revenue overview including total and breakdown by source (bookings, products, donations).',
        parameters=[
            EVENT_ID_PARAM,
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            STATUS_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            FORMAT_PARAM
        ],
        responses={200: EventRevenueOverviewSerializer},
        examples=[
            OpenApiExample(
                'Revenue Overview Example',
                value={
                    'total_revenue': '125000.00',
                    'booking_revenue': '95000.00',
                    'product_revenue': '20000.00',
                    'donation_revenue': '10000.00',
                    'breakdown': [
                        {'source': 'Bookings', 'value': 95000.00},
                        {'source': 'Products', 'value': 20000.00},
                        {'source': 'Donations', 'value': 10000.00}
                    ]
                },
                response_only=True
            )
        ]
    )
    @action(detail=False, methods=['get'], url_path='revenue-overview')
    def revenue_overview(self, request):
        """Get revenue overview."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_overview(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = EventRevenueOverviewSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get revenue by event',
        description='Returns revenue data for each event, with optional breakdown by source.',
        parameters=[
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            STATUS_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            LIMIT_PARAM,
            SORT_BY_PARAM,
            SHOW_BREAKDOWN_PARAM,
            FORMAT_PARAM
        ],
        responses={200: RevenueByEventSerializer}
    )
    @action(detail=False, methods=['get'], url_path='revenue-by-event')
    def revenue_by_event(self, request):
        """Get revenue by event."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 15))
        sort_by = request.query_params.get('sort_by', 'total_revenue')
        
        data = statistics.calculate_revenue_by_event(
            limit=limit,
            sort_by=sort_by,
            **filters
        )
        data = self._add_filter_metadata(data, request)
        
        serializer = RevenueByEventSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get payment status distribution',
        description='Returns distribution of booking payment statuses.',
        parameters=[
            EVENT_ID_PARAM,
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            FORMAT_PARAM
        ],
        responses={200: EventPaymentStatusDistributionSerializer}
    )
    @action(detail=False, methods=['get'], url_path='payment-status')
    def payment_status(self, request):
        """Get payment status distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_payment_status_distribution(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = EventPaymentStatusDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get capacity utilization',
        description='Returns capacity utilization data showing registered vs maximum attendance for each event.',
        parameters=[
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            STATUS_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            FORMAT_PARAM
        ],
        responses={200: CapacityUtilizationSerializer}
    )
    @action(detail=False, methods=['get'], url_path='capacity-utilization')
    def capacity_utilization(self, request):
        """Get capacity utilization."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_capacity_utilization(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = CapacityUtilizationSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get registration trends',
        description='Returns registration trends over time, grouped by specified period.',
        parameters=[
            EVENT_ID_PARAM,
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            DATE_FROM_PARAM,
            DATE_TO_PARAM,
            PERIOD_PARAM,
            CUMULATIVE_PARAM,
            FORMAT_PARAM
        ],
        responses={200: EventRegistrationTrendsSerializer}
    )
    @action(detail=False, methods=['get'], url_path='registration-trends')
    def registration_trends(self, request):
        """Get registration trends."""
        filters = self._get_common_filters(request)
        period = request.query_params.get('period', 'month')
        cumulative = request.query_params.get('cumulative', 'false').lower() == 'true'
        
        data = statistics.calculate_registration_trends(
            event_id=filters.get('event_id'),
            period=period,
            cumulative=cumulative
        )
        data = self._add_filter_metadata(data, request)
        
        serializer = EventRegistrationTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get review statistics',
        description='Returns event review statistics including ratings distribution and top-rated events.',
        parameters=[
            EVENT_ID_PARAM,
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            LIMIT_PARAM,
            FORMAT_PARAM
        ],
        responses={200: ReviewStatisticsSerializer}
    )
    @action(detail=False, methods=['get'], url_path='reviews')
    def reviews(self, request):
        """Get review statistics."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 10))
        
        data = statistics.calculate_review_statistics(limit=limit, **filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = ReviewStatisticsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get staff allocation',
        description='Returns staff allocation data showing staff distribution across events.',
        parameters=[
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            STATUS_PARAM,
            LIMIT_PARAM,
            FORMAT_PARAM
        ],
        responses={200: StaffAllocationSerializer}
    )
    @action(detail=False, methods=['get'], url_path='staff-allocation')
    def staff_allocation(self, request):
        """Get staff allocation."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 10))
        
        data = statistics.calculate_staff_allocation(limit=limit, **filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = StaffAllocationSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary='Get booking package performance',
        description='Returns performance statistics for booking packages including usage and revenue.',
        parameters=[
            EVENT_ID_PARAM,
            EVENT_TYPE_PARAM,
            ORGANIZATION_PARAM,
            LIMIT_PARAM,
            FORMAT_PARAM
        ],
        responses={200: BookingPackagePerformanceSerializer}
    )
    @action(detail=False, methods=['get'], url_path='booking-packages')
    def booking_packages(self, request):
        """Get booking package performance."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 10))
        
        data = statistics.calculate_booking_package_performance(limit=limit, **filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = BookingPackagePerformanceSerializer(data, context={'request': request})
        return Response(serializer.data)
