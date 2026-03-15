"""
Payment Statistics ViewSet

Provides comprehensive statistical analysis endpoints for payment data.
All endpoints support both raw JSON and ECharts-ready formats via ?format parameter.

Usage:
    - Raw format: /api/payments/statistics/overview/?format=raw
    - ECharts format: /api/payments/statistics/overview/?format=echarts
    - Event-specific: /api/payments/statistics/overview/?event_id=<uuid>
    - Date filtering: /api/payments/statistics/revenue-trends/?date_from=2026-01-01&date_to=2026-03-01

Permissions:
    - All endpoints require IsAuthenticated
    - Global statistics (no event_id) require superuser permissions
    - Event-specific statistics allowed for authenticated users
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import exceptions
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
import uuid

from apps.payments import statistics
from apps.payments.api.serializers.statistics import (
    PaymentStatusDistributionSerializer,
    PaymentMethodDistributionSerializer,
    PaymentTrendsSerializer,
    PaymentOverviewSerializer,
    DiscountUsageSerializer,
    DiscountRuleEffectivenessSerializer,
    TopDiscountsSerializer,
    RefundRequestStatsSerializer,
    RefundTrendsSerializer,
    RefundProcessingTimesSerializer,
    DonationStatsSerializer,
    DonationTrendsSerializer,
    TopDonorsSerializer,
    PaymentRevenueOverviewSerializer,
    PaymentRevenueTrendsSerializer,
    RevenueByMethodSerializer,
    PaymentRevenueBreakdownSerializer,
    SponsorPackagePaymentStatusSerializer,
    PaymentOverviewStatsSerializer,
)


# ============================================================================
# COMMON PARAMETERS FOR DOCUMENTATION
# ============================================================================

EVENT_ID_PARAM = OpenApiParameter(
    name='event_id',
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.QUERY,
    description='Filter statistics to a specific event. If omitted, returns global statistics (superuser only).',
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
    description='Include soft-deleted orders in statistics. NOTE: Payment model does not support soft-delete, only Order model does.',
    required=False,
    default=False,
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
    description='Maximum number of results to return.',
    required=False,
    default=10,
)


# ============================================================================
# STATISTICS VIEWSET
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Available statistics endpoints",
        description="Lists all available payment statistics endpoints with descriptions.",
        tags=["Payment Statistics"],
    )
)
class PaymentStatisticsViewSet(viewsets.GenericViewSet):
    """
    ViewSet for payment statistics.
    
    Provides comprehensive statistical analysis of payment data including:
    - Payment status and method distributions
    - Discount usage and effectiveness
    - Refund requests and processing
    - Donation tracking
    - Revenue analysis (only COMPLETED payments)
    - Trends over time
    
    All endpoints support:
    - Event-specific filtering via ?event_id parameter
    - Global statistics (superuser only when event_id is omitted)
    - Raw or ECharts-ready format via ?format parameter
    - Soft-deleted order inclusion via ?include_deleted parameter (only affects order-related stats)
    
    Permissions:
    - All endpoints require authentication
    - Global statistics (no event_id) require superuser permissions
    - Event-specific statistics allowed for any authenticated user
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentOverviewStatsSerializer  # Default serializer
    queryset = None  # Statistics viewset doesn't use queryset
    
    def _check_global_access(self, request):
        """
        Check if user has permission for global statistics.
        Global statistics (no event_id) require superuser permissions.
        
        Args:
            request: The request object
        
        Raises:
            PermissionDenied: If user is not superuser and no event_id provided
        """
        event_id = request.query_params.get('event_id')
        if not event_id and not request.user.is_superuser:
            raise exceptions.PermissionDenied(
                "Global statistics require superuser permissions. Provide an event_id parameter for event-specific statistics."
            )
    
    def _get_common_filters(self, request):
        """Extract and validate common filter parameters from request."""
        filters = {}
        
        # Event ID (validate UUID format)
        event_id = request.query_params.get('event_id')
        if event_id:
            try:
                # Validate UUID format
                uuid.UUID(event_id)
                filters['event_id'] = event_id
            except ValueError:
                raise exceptions.ValidationError({
                    'event_id': 'Invalid UUID format.'
                })
        
        # Include deleted (boolean)
        include_deleted = request.query_params.get('include_deleted', 'false').lower() == 'true'
        filters['include_deleted'] = include_deleted
        
        # Date filters
        date_from = request.query_params.get('date_from')
        if date_from:
            try:
                filters['date_from'] = datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                raise exceptions.ValidationError({
                    'date_from': 'Invalid date format. Use YYYY-MM-DD.'
                })
        
        date_to = request.query_params.get('date_to')
        if date_to:
            try:
                filters['date_to'] = datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                raise exceptions.ValidationError({
                    'date_to': 'Invalid date format. Use YYYY-MM-DD.'
                })
        
        # Group by (validate enum)
        group_by = request.query_params.get('group_by', 'day')
        if group_by not in ['day', 'week', 'month']:
            raise exceptions.ValidationError({
                'group_by': 'Invalid value. Must be one of: day, week, month.'
            })
        filters['group_by'] = group_by
        
        # Limit (validate integer)
        limit = request.query_params.get('limit', '10')
        try:
            filters['limit'] = int(limit)
            if filters['limit'] < 1:
                raise ValueError
        except ValueError:
            raise exceptions.ValidationError({
                'limit': 'Invalid value. Must be a positive integer.'
            })
        
        return filters
    
    def _add_filter_metadata(self, data, request):
        """Add filter metadata to response."""
        filters_applied = {}
        
        event_id = request.query_params.get('event_id')
        if event_id:
            filters_applied['event_id'] = event_id
        
        include_deleted = request.query_params.get('include_deleted', 'false').lower() == 'true'
        if include_deleted:
            filters_applied['include_deleted'] = True
        
        date_from = request.query_params.get('date_from')
        if date_from:
            filters_applied['date_from'] = date_from
        
        date_to = request.query_params.get('date_to')
        if date_to:
            filters_applied['date_to'] = date_to
        
        group_by = request.query_params.get('group_by')
        if group_by:
            filters_applied['group_by'] = group_by
        
        limit = request.query_params.get('limit')
        if limit:
            filters_applied['limit'] = limit
        
        data['filters_applied'] = filters_applied
        data['generated_at'] = timezone.now()
    
    def list(self, request):
        """List all available statistics endpoints."""
        endpoints = {
            'overview': 'Combined overview statistics ideal for dashboard display',
            'payment-status': 'Payment status distribution',
            'payment-methods': 'Payment method distribution',
            'payment-trends': 'Payment creation trends over time',
            'payment-overview': 'Payment overview with totals and averages',
            'discount-usage': 'Discount usage and type distribution',
            'discount-rules': 'Discount rule effectiveness by type',
            'top-discounts': 'Most configured discounts',
            'refund-requests': 'Refund request statistics and status',
            'refund-trends': 'Refund trends over time',
            'refund-processing': 'Refund processing time statistics',
            'donations': 'Donation statistics and status',
            'donation-trends': 'Donation trends over time',
            'top-donors': 'Top donors by total amount',
            'revenue-overview': 'Revenue overview (completed payments only)',
            'revenue-trends': 'Revenue trends over time',
            'revenue-by-method': 'Revenue breakdown by payment method',
            'revenue-breakdown': 'Detailed revenue breakdown with refunds',
            'sponsor-packages': 'Sponsor package payment status and revenue metrics',
        }
        
        return Response({
            'endpoints': endpoints,
            'base_url': '/api/payments/statistics/',
            'supported_parameters': {
                'event_id': 'Filter to specific event (UUID)',
                'format': 'Response format: raw or echarts',
                'include_deleted': 'Include soft-deleted orders (boolean)',
                'date_from': 'Start date filter (YYYY-MM-DD)',
                'date_to': 'End date filter (YYYY-MM-DD)',
                'group_by': 'Time grouping: day, week, or month',
                'limit': 'Maximum results for top/limit queries'
            }
        })
    
    # ========================================================================
    # COMBINED OVERVIEW
    # ========================================================================
    
    @extend_schema(
        summary="Overview statistics",
        description="Combined overview statistics ideal for dashboard display. Includes payments, revenue, discounts, refunds, and donations.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: PaymentOverviewStatsSerializer},
        tags=["Payment Statistics"],
        examples=[
            OpenApiExample(
                'Overview Response',
                value={
                    'payments': {
                        'total': 250,
                        'total_amount': 50000.00,
                        'average_amount': 200.00,
                        'by_status': {}
                    },
                    'revenue': {
                        'gross': 45000.00,
                        'net': 43000.00,
                        'refunded': 2000.00,
                        'completed_count': 225
                    },
                    'discounts': {
                        'total_active': 15,
                        'by_type': []
                    },
                    'refunds': {
                        'total_requests': 10,
                        'total_amount': 2000.00,
                        'by_status': []
                    },
                    'donations': {
                        'total': 30,
                        'total_amount': 5000.00,
                        'average_amount': 166.67
                    },
                    'generated_at': '2026-03-11T12:00:00Z'
                },
                response_only=True,
            ),
        ]
    )
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get combined overview statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_overview_stats(
            event_id=filters.get('event_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentOverviewStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    # ========================================================================
    # PAYMENT STATISTICS
    # ========================================================================
    
    @extend_schema(
        summary="Payment status distribution",
        description="Distribution of payment statuses (COMPLETED, PENDING, FAILED, etc.).",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: PaymentStatusDistributionSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='payment-status')
    def payment_status(self, request):
        """Get payment status distribution."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_payment_status_distribution(
            event_id=filters.get('event_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentStatusDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Payment method distribution",
        description="Distribution of payment methods (Stripe, Bank Transfer, Cash, etc.).",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: PaymentMethodDistributionSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='payment-methods')
    def payment_methods(self, request):
        """Get payment method distribution."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_payment_method_distribution(
            event_id=filters.get('event_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentMethodDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Payment trends",
        description="Payment creation trends over time with configurable grouping.",
        parameters=[
            EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: PaymentTrendsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='payment-trends')
    def payment_trends(self, request):
        """Get payment creation trends."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_payment_trends(
            event_id=filters.get('event_id'),
            group_by=filters.get('group_by', 'day'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Payment overview",
        description="Payment overview with totals, averages, and status breakdown.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: PaymentOverviewSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='payment-overview')
    def payment_overview(self, request):
        """Get payment overview statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_payment_overview(
            event_id=filters.get('event_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentOverviewSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    # ========================================================================
    # DISCOUNT STATISTICS
    # ========================================================================
    
    @extend_schema(
        summary="Discount usage statistics",
        description="Statistics about discount usage and type distribution.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM],
        responses={200: DiscountUsageSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='discount-usage')
    def discount_usage(self, request):
        """Get discount usage statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_discount_usage(
            event_id=filters.get('event_id')
        )
        self._add_filter_metadata(data, request)
        
        serializer = DiscountUsageSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Discount rule effectiveness",
        description="Statistics about which discount rule types are most commonly used.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM],
        responses={200: DiscountRuleEffectivenessSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='discount-rules')
    def discount_rules(self, request):
        """Get discount rule effectiveness statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_discount_rule_effectiveness(
            event_id=filters.get('event_id')
        )
        self._add_filter_metadata(data, request)
        
        serializer = DiscountRuleEffectivenessSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Top discounts",
        description="Most recently created active discounts.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, LIMIT_PARAM],
        responses={200: TopDiscountsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='top-discounts')
    def top_discounts(self, request):
        """Get top discounts."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_top_discounts(
            event_id=filters.get('event_id'),
            limit=filters.get('limit', 10)
        )
        self._add_filter_metadata(data, request)
        
        serializer = TopDiscountsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    # ========================================================================
    # REFUND STATISTICS
    # ========================================================================
    
    @extend_schema(
        summary="Refund request statistics",
        description="Statistics about refund requests including status distribution and amounts.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM],
        responses={200: RefundRequestStatsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='refund-requests')
    def refund_requests(self, request):
        """Get refund request statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_refund_request_stats(
            event_id=filters.get('event_id')
        )
        self._add_filter_metadata(data, request)
        
        serializer = RefundRequestStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Refund trends",
        description="Refund request trends over time.",
        parameters=[
            EVENT_ID_PARAM, FORMAT_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: RefundTrendsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='refund-trends')
    def refund_trends(self, request):
        """Get refund trends over time."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_refund_trends(
            event_id=filters.get('event_id'),
            group_by=filters.get('group_by', 'day'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to')
        )
        self._add_filter_metadata(data, request)
        
        serializer = RefundTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Refund processing times",
        description="Statistics about refund processing times (average, median, min, max).",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM],
        responses={200: RefundProcessingTimesSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='refund-processing')
    def refund_processing(self, request):
        """Get refund processing time statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_refund_processing_times(
            event_id=filters.get('event_id')
        )
        self._add_filter_metadata(data, request)
        
        serializer = RefundProcessingTimesSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    # ========================================================================
    # DONATION STATISTICS
    # ========================================================================
    
    @extend_schema(
        summary="Donation statistics",
        description="Statistics about donations including totals, averages, and status distribution.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM],
        responses={200: DonationStatsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'])
    def donations(self, request):
        """Get donation statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_donation_stats(
            event_id=filters.get('event_id')
        )
        self._add_filter_metadata(data, request)
        
        serializer = DonationStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Donation trends",
        description="Donation trends over time.",
        parameters=[
            EVENT_ID_PARAM, FORMAT_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: DonationTrendsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='donation-trends')
    def donation_trends(self, request):
        """Get donation trends over time."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_donation_trends(
            event_id=filters.get('event_id'),
            group_by=filters.get('group_by', 'day'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to')
        )
        self._add_filter_metadata(data, request)
        
        serializer = DonationTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Top donors",
        description="Top donors by total donation amount.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, LIMIT_PARAM],
        responses={200: TopDonorsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='top-donors')
    def top_donors(self, request):
        """Get top donors."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_top_donors(
            event_id=filters.get('event_id'),
            limit=filters.get('limit', 10)
        )
        self._add_filter_metadata(data, request)
        
        serializer = TopDonorsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    # ========================================================================
    # REVENUE STATISTICS (CRITICAL - Only COMPLETED payments)
    # ========================================================================
    
    @extend_schema(
        summary="Revenue overview",
        description="Revenue overview statistics. CRITICAL: Only COMPLETED payments count toward revenue.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: PaymentRevenueOverviewSerializer},
        tags=["Payment Statistics"],
        examples=[
            OpenApiExample(
                'Revenue Overview',
                value={
                    'total_revenue': 45000.00,
                    'total_completed_payments': 225,
                    'average_payment': 200.00,
                    'total_refunded': 2000.00,
                    'refunded_payment_count': 10,
                    'net_revenue': 43000.00,
                    'generated_at': '2026-03-11T12:00:00Z'
                },
                response_only=True,
            ),
        ]
    )
    @action(detail=False, methods=['get'], url_path='revenue-overview')
    def revenue_overview(self, request):
        """Get revenue overview statistics."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_overview(
            event_id=filters.get('event_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentRevenueOverviewSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Revenue trends",
        description="Revenue trends over time. CRITICAL: Only COMPLETED payments count toward revenue.",
        parameters=[
            EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: PaymentRevenueTrendsSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-trends')
    def revenue_trends(self, request):
        """Get revenue trends over time."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_trends(
            event_id=filters.get('event_id'),
            group_by=filters.get('group_by', 'day'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentRevenueTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Revenue by payment method",
        description="Revenue breakdown by payment method. CRITICAL: Only COMPLETED payments count toward revenue.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: RevenueByMethodSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-by-method')
    def revenue_by_method(self, request):
        """Get revenue by payment method."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_by_method(
            event_id=filters.get('event_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = RevenueByMethodSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Revenue breakdown",
        description="Detailed revenue breakdown including gross, refunded, and net revenue. CRITICAL: Only COMPLETED payments count toward revenue.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: PaymentRevenueBreakdownSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='revenue-breakdown')
    def revenue_breakdown(self, request):
        """Get detailed revenue breakdown."""
        self._check_global_access(request)
        
        filters = self._get_common_filters(request)
        data = statistics.calculate_revenue_breakdown(
            event_id=filters.get('event_id'),
            include_deleted=filters.get('include_deleted', False)
        )
        self._add_filter_metadata(data, request)
        
        serializer = PaymentRevenueBreakdownSerializer(data, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Sponsor package payment status",
        description="Payment status distribution and revenue totals for sponsor packages.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM],
        responses={200: SponsorPackagePaymentStatusSerializer},
        tags=["Payment Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='sponsor-packages')
    def sponsor_packages(self, request):
        """Get sponsor package payment status metrics."""
        self._check_global_access(request)

        filters = self._get_common_filters(request)
        data = statistics.calculate_sponsor_package_payment_status(
            event_id=filters.get('event_id')
        )
        self._add_filter_metadata(data, request)

        serializer = SponsorPackagePaymentStatusSerializer(data, context={'request': request})
        return Response(serializer.data)
