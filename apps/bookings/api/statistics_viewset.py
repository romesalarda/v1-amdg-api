"""
Booking Statistics ViewSet

Provides comprehensive statistical analysis endpoints for booking data.
All endpoints support both raw JSON and ECharts-ready formats via ?format parameter.

Usage:
    - Raw format: /api/bookings/statistics/booking-overview/?format=raw
    - ECharts format: /api/bookings/statistics/booking-overview/?format=echarts
    - Event-specific: /api/bookings/statistics/booking-overview/?event_id=<uuid>
    - Date filtering: /api/bookings/statistics/booking-trends/?date_from=2026-01-01&date_to=2026-03-01
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes
from django.utils import timezone
from datetime import datetime, date

from apps.bookings.services import statistics
from apps.bookings.models import Booking
from apps.bookings.api.serializers.statistics import (
    BookingOverviewSerializer,
    BookingStatusDistributionSerializer,
    BookingTrendsSerializer,
    BookingsByPackageSerializer,
    AttendeesPerBookingSerializer,
    BookingCompletionRateSerializer,
    BookingReferenceTypesSerializer,
    BookingTimelineSerializer,
    TicketOverviewSerializer,
    TicketStatusDistributionSerializer,
    TicketTypeDistributionSerializer,
    TicketUsageStatsSerializer,
    TicketScopeDistributionSerializer,
    PackageOverviewSerializer,
    PackagePopularitySerializer,
    PackageRuleDistributionSerializer,
    PackagePricingAnalysisSerializer,
    IntentOverviewSerializer,
    IntentConversionRateSerializer,
    IntentTrendsSerializer,
    BookingRevenueOverviewSerializer,
    RevenueByPackageSerializer,
    RevenueByTicketTypeSerializer,
    BookingRevenueTrendsSerializer,
    BookingRevenueBreakdownSerializer,
    BookingStatisticsOverviewSerializer,
)
from apps.attendee import formatters


# ============================================================================
# COMMON PARAMETERS FOR DOCUMENTATION
# ============================================================================

EVENT_ID_PARAM = OpenApiParameter(
    name='event_id',
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.QUERY,
    description='Filter statistics to a specific event (using event_id UUID). If omitted, returns global statistics across all events.',
    required=False,
)

ORGANIZATION_ID_PARAM = OpenApiParameter(
    name='organization_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Filter statistics to a specific organization.',
    required=False,
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

INCLUDE_DELETED_PARAM = OpenApiParameter(
    name='include_deleted',
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description='Include soft-deleted records in statistics.',
    required=False,
    default=False,
)

STATUS_PARAM = OpenApiParameter(
    name='status',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Filter by payment/ticket/intent status.',
    required=False,
)

DATE_FROM_PARAM = OpenApiParameter(
    name='date_from',
    type=OpenApiTypes.DATE,
    location=OpenApiParameter.QUERY,
    description='Start date for filtering (YYYY-MM-DD format).',
    required=False,
)

DATE_TO_PARAM = OpenApiParameter(
    name='date_to',
    type=OpenApiTypes.DATE,
    location=OpenApiParameter.QUERY,
    description='End date for filtering (YYYY-MM-DD format).',
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

LIMIT_PARAM = OpenApiParameter(
    name='limit',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description='Maximum number of items to return.',
    required=False,
    default=10,
)


# ============================================================================
# STATISTICS VIEWSET
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Available statistics endpoints",
        description="Lists all available booking statistics endpoints with descriptions.",
        tags=["Booking Statistics"],
    )
)
class BookingStatisticsViewSet(viewsets.GenericViewSet):
    """
    ViewSet for booking statistics.
    
    Provides comprehensive statistical analysis of booking data including:
    - Bookings (overview, status, trends, packages, attendees, completion)
    - Tickets (overview, status, types, usage, scope)
    - Packages (overview, popularity, rules, pricing)
    - Intents (overview, conversion, trends)
    - Revenue (overview, by package, by ticket type, trends, breakdown)
    
    All endpoints support:
    - Event-specific filtering via ?event_id parameter (UUID)
    - Organization filtering via ?organization_id parameter
    - Raw or ECharts-ready format via ?format parameter
    - Soft-deleted record inclusion via ?include_deleted parameter
    - Date range filtering via ?date_from and ?date_to parameters
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = BookingStatisticsOverviewSerializer  # Default serializer
    queryset = Booking.objects.none()  # Schema generation model hint
    
    def _get_common_filters(self, request):
        """Extract common filter parameters from request."""
        from apps.utils.querying import get_event_or_url_safe_title
        event = request.query_params.get('event_id')
        filters = {
            'event_id': get_event_or_url_safe_title(event).event_id if event else None,
            'organization_id': request.query_params.get('organization_id'),
            'include_deleted': request.query_params.get('include_deleted', 'false').lower() == 'true',
        }
        
        # Optional filters
        status = request.query_params.get('status')
        if status:
            filters['status'] = status
        
        date_from = request.query_params.get('date_from')
        if date_from:
            try:
                filters['date_from'] = datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        date_to = request.query_params.get('date_to')
        if date_to:
            try:
                filters['date_to'] = datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        return filters
    
    def _add_filter_metadata(self, data, request):
        """Add filter metadata to response."""
        filters_applied = {}
        
        event_id = request.query_params.get('event_id')
        if event_id:
            filters_applied['event_id'] = event_id
        
        organization_id = request.query_params.get('organization_id')
        if organization_id:
            filters_applied['organization_id'] = organization_id
        
        include_deleted = request.query_params.get('include_deleted', 'false').lower() == 'true'
        if include_deleted:
            filters_applied['include_deleted'] = True
        
        status = request.query_params.get('status')
        if status:
            filters_applied['status'] = status
        
        date_from = request.query_params.get('date_from')
        if date_from:
            filters_applied['date_from'] = date_from
        
        date_to = request.query_params.get('date_to')
        if date_to:
            filters_applied['date_to'] = date_to
        
        data['filters_applied'] = filters_applied
        data['generated_at'] = timezone.now().isoformat()
        
        return data
    
    def _format_response(self, data, request, chart_type='pie', title='Statistics'):
        """Format response based on format parameter."""
        format_type = request.query_params.get('format', 'raw')
        
        if format_type == 'echarts':
            # Check if data has distribution for chart formatting
            if 'distribution' in data:
                if chart_type == 'pie':
                    chart_data = formatters.format_pie_chart(
                        data['distribution'],
                        title=title
                    )
                elif chart_type == 'bar':
                    chart_data = formatters.format_bar_chart(
                        data['distribution'],
                        title=title
                    )
                elif chart_type == 'line':
                    # For trends
                    if 'trends' in data:
                        chart_data = formatters.format_line_chart(
                            data['trends'],
                            title=title
                        )
                    else:
                        chart_data = formatters.format_line_chart(
                            data['distribution'],
                            title=title
                        )
                else:
                    chart_data = data
                
                return chart_data
            elif 'trends' in data:
                chart_data = formatters.format_line_chart(
                    data['trends'],
                    title=title
                )
                return chart_data
        
        return data
    
    def list(self, request):
        """List all available statistics endpoints."""
        endpoints = {
            'overview': 'Combined overview statistics for dashboard',
            'booking-overview': 'Booking overview with attendee and ticket counts',
            'booking-status': 'Booking status distribution',
            'booking-trends': 'Booking creation trends over time',
            'bookings-by-package': 'Booking distribution by package',
            'attendees-per-booking': 'Distribution of attendees per booking',
            'completion-rate': 'Booking completion rate from intents',
            'booking-references': 'Booking reference pattern distribution',
            'booking-timeline': 'Booking timeline analysis',
            'ticket-overview': 'Ticket overview with status and scope',
            'ticket-status': 'Ticket status distribution',
            'ticket-types': 'Ticket type distribution',
            'ticket-usage': 'Ticket usage statistics',
            'ticket-scope': 'Ticket scope distribution',
            'package-overview': 'Package overview with usage statistics',
            'package-popularity': 'Most popular packages by usage',
            'package-rules': 'Package rule type distribution',
            'package-pricing': 'Package pricing analysis',
            'intent-overview': 'Booking intent overview',
            'intent-conversion': 'Intent conversion rate analysis',
            'intent-trends': 'Intent creation trends over time',
            'revenue-overview': 'Revenue overview (completed payments only)',
            'revenue-by-package': 'Revenue breakdown by package',
            'revenue-by-ticket-type': 'Revenue breakdown by ticket type',
            'revenue-trends': 'Revenue trends over time',
            'revenue-breakdown': 'Revenue breakdown by payment status',
        }
        
        return Response({
            'available_endpoints': endpoints,
            'base_path': '/api/bookings/statistics/',
            'common_parameters': {
                'event_id': 'Filter by event UUID',
                'organization_id': 'Filter by organization ID',
                'format': 'Response format (raw/echarts)',
                'include_deleted': 'Include soft-deleted records',
                'date_from': 'Start date (YYYY-MM-DD)',
                'date_to': 'End date (YYYY-MM-DD)',
                'group_by': 'Time grouping (day/week/month) for trends',
                'limit': 'Maximum items to return',
            }
        })
    
    # ========================================================================
    # BOOKING STATISTICS ENDPOINTS
    # ========================================================================
    
    @extend_schema(
        summary="Booking overview statistics",
        description="Overview of bookings including total counts, attendees, tickets, and status breakdown.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingOverviewSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='booking-overview')
    def booking_overview(self, request):
        """Get booking overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_booking_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingOverviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Booking status distribution",
        description="Distribution of bookings by payment status.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingStatusDistributionSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='booking-status')
    def booking_status(self, request):
        """Get booking status distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_booking_status_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        data = self._format_response(data, request, chart_type='pie', title='Booking Status Distribution')
        serializer = BookingStatusDistributionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Booking trends",
        description="Booking creation trends over time with configurable grouping.",
        parameters=[
            EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: BookingTrendsSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='booking-trends')
    def booking_trends(self, request):
        """Get booking trends over time."""
        filters = self._get_common_filters(request)
        group_by = request.query_params.get('group_by', 'day')
        
        data = statistics.calculate_booking_trends(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            group_by=group_by,
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        data = self._format_response(data, request, chart_type='line', title='Booking Trends')
        serializer = BookingTrendsSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Bookings by package",
        description="Distribution of bookings by booking package.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM, LIMIT_PARAM],
        responses={200: BookingsByPackageSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='bookings-by-package')
    def bookings_by_package(self, request):
        """Get bookings by package distribution."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 10))
        
        data = statistics.calculate_bookings_by_package(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False),
            limit=limit
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingsByPackageSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Attendees per booking",
        description="Distribution of number of attendees per booking.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: AttendeesPerBookingSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='attendees-per-booking')
    def attendees_per_booking(self, request):
        """Get attendees per booking distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_attendees_per_booking(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = AttendeesPerBookingSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Booking completion rate",
        description="Conversion rate from booking intents to completed bookings.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingCompletionRateSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='completion-rate')
    def completion_rate(self, request):
        """Get booking completion rate."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_booking_completion_rate(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingCompletionRateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Booking reference types",
        description="Distribution of booking reference patterns by event code.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingReferenceTypesSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='booking-references')
    def booking_references(self, request):
        """Get booking reference types distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_booking_reference_types(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingReferenceTypesSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Booking timeline",
        description="Timeline analysis of booking creation dates.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingTimelineSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='booking-timeline')
    def booking_timeline(self, request):
        """Get booking timeline."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_booking_timeline(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingTimelineSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    # ========================================================================
    # TICKET STATISTICS ENDPOINTS
    # ========================================================================
    
    @extend_schema(
        summary="Ticket overview statistics",
        description="Overview of tickets including status, scope, and usage statistics.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: TicketOverviewSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='ticket-overview')
    def ticket_overview(self, request):
        """Get ticket overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_ticket_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = TicketOverviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Ticket status distribution",
        description="Distribution of tickets by status (ACTIVE, CANCELLED, USED).",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: TicketStatusDistributionSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='ticket-status')
    def ticket_status(self, request):
        """Get ticket status distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_ticket_status_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        data = self._format_response(data, request, chart_type='pie', title='Ticket Status Distribution')
        serializer = TicketStatusDistributionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Ticket type distribution",
        description="Distribution of tickets by ticket type and scope.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: TicketTypeDistributionSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='ticket-types')
    def ticket_types(self, request):
        """Get ticket type distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_ticket_type_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = TicketTypeDistributionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Ticket usage statistics",
        description="Detailed ticket usage statistics including valid, used, and cancelled tickets.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: TicketUsageStatsSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='ticket-usage')
    def ticket_usage(self, request):
        """Get ticket usage statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_ticket_usage_stats(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = TicketUsageStatsSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Ticket scope distribution",
        description="Distribution of tickets by scope (FULL_EVENT, SINGLE_DAY, WORKSHOP_ONLY).",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: TicketScopeDistributionSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='ticket-scope')
    def ticket_scope(self, request):
        """Get ticket scope distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_ticket_scope_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        data = self._format_response(data, request, chart_type='pie', title='Ticket Scope Distribution')
        serializer = TicketScopeDistributionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    # ========================================================================
    # PACKAGE STATISTICS ENDPOINTS
    # ========================================================================
    
    @extend_schema(
        summary="Package overview statistics",
        description="Overview of booking packages including usage and rule statistics.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM],
        responses={200: PackageOverviewSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='package-overview')
    def package_overview(self, request):
        """Get package overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_package_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id')
        )
        data = self._add_filter_metadata(data, request)
        serializer = PackageOverviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Package popularity",
        description="Most popular packages ranked by usage.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM, LIMIT_PARAM],
        responses={200: PackagePopularitySerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='package-popularity')
    def package_popularity(self, request):
        """Get package popularity statistics."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 10))
        
        data = statistics.calculate_package_popularity(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False),
            limit=limit
        )
        data = self._add_filter_metadata(data, request)
        serializer = PackagePopularitySerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Package rule distribution",
        description="Distribution of package rules by rule type.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM],
        responses={200: PackageRuleDistributionSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='package-rules')
    def package_rules(self, request):
        """Get package rule distribution."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_package_rule_distribution(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id')
        )
        data = self._add_filter_metadata(data, request)
        data = self._format_response(data, request, chart_type='bar', title='Package Rule Distribution')
        serializer = PackageRuleDistributionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Package pricing analysis",
        description="Pricing analysis for booking packages including base amounts and modifiers.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM],
        responses={200: PackagePricingAnalysisSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='package-pricing')
    def package_pricing(self, request):
        """Get package pricing analysis."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_package_pricing_analysis(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id')
        )
        data = self._add_filter_metadata(data, request)
        serializer = PackagePricingAnalysisSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    # ========================================================================
    # INTENT STATISTICS ENDPOINTS
    # ========================================================================
    
    @extend_schema(
        summary="Intent overview statistics",
        description="Overview of booking intents including status breakdown and capacity statistics.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: IntentOverviewSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='intent-overview')
    def intent_overview(self, request):
        """Get intent overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_intent_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = IntentOverviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Intent conversion rate",
        description="Conversion rate analysis from booking intents to completed bookings.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: IntentConversionRateSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='intent-conversion')
    def intent_conversion(self, request):
        """Get intent conversion rate."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_intent_conversion_rate(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = IntentConversionRateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Intent trends",
        description="Booking intent creation trends over time with configurable grouping.",
        parameters=[
            EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: IntentTrendsSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='intent-trends')
    def intent_trends(self, request):
        """Get intent trends over time."""
        filters = self._get_common_filters(request)
        group_by = request.query_params.get('group_by', 'day')
        
        data = statistics.calculate_intent_trends(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            group_by=group_by,
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        data = self._format_response(data, request, chart_type='line', title='Intent Trends')
        serializer = IntentTrendsSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    # ========================================================================
    # REVENUE STATISTICS ENDPOINTS
    # ========================================================================
    
    @extend_schema(
        summary="Revenue overview statistics",
        description="Revenue overview including total, average, and payment statistics. Only COMPLETED payments are counted.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingRevenueOverviewSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-overview')
    def revenue_overview(self, request):
        """Get revenue overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingRevenueOverviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Revenue by package",
        description="Revenue breakdown by booking package. Only COMPLETED payments are counted.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM, LIMIT_PARAM],
        responses={200: RevenueByPackageSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-by-package')
    def revenue_by_package(self, request):
        """Get revenue by package."""
        filters = self._get_common_filters(request)
        limit = int(request.query_params.get('limit', 10))
        
        data = statistics.calculate_revenue_by_package(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False),
            limit=limit
        )
        data = self._add_filter_metadata(data, request)
        serializer = RevenueByPackageSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Revenue by ticket type",
        description="Revenue breakdown by ticket type. Only COMPLETED payments are counted.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: RevenueByTicketTypeSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-by-ticket-type')
    def revenue_by_ticket_type(self, request):
        """Get revenue by ticket type."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_by_ticket_type(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = RevenueByTicketTypeSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Revenue trends",
        description="Revenue trends over time with configurable grouping. Only COMPLETED payments are counted.",
        parameters=[
            EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: BookingRevenueTrendsSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-trends')
    def revenue_trends(self, request):
        """Get revenue trends over time."""
        filters = self._get_common_filters(request)
        group_by = request.query_params.get('group_by', 'day')
        
        data = statistics.calculate_revenue_trends(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            group_by=group_by,
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        data = self._format_response(data, request, chart_type='line', title='Revenue Trends')
        serializer = BookingRevenueTrendsSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Revenue breakdown",
        description="Revenue breakdown by payment status including all statuses.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingRevenueBreakdownSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-breakdown')
    def revenue_breakdown(self, request):
        """Get revenue breakdown by status."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_breakdown(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingRevenueBreakdownSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    
    # ========================================================================
    # COMBINED OVERVIEW ENDPOINT
    # ========================================================================
    
    @extend_schema(
        summary="Combined overview statistics",
        description="Combined overview statistics for dashboard display including bookings, tickets, packages, intents, and revenue.",
        parameters=[EVENT_ID_PARAM, ORGANIZATION_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: BookingStatisticsOverviewSerializer},
        tags=["Booking Statistics"],
    )
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get combined overview statistics."""
        filters = self._get_common_filters(request)
        data = statistics.calculate_booking_statistics_overview(
            event_id=filters.get('event_id'),
            organization_id=filters.get('organization_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        data = self._add_filter_metadata(data, request)
        serializer = BookingStatisticsOverviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
