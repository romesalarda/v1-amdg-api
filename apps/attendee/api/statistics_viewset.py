"""
Attendee Statistics ViewSet

Provides comprehensive statistical analysis endpoints for attendee data.
All endpoints support both raw JSON and ECharts-ready formats via ?format parameter.

Usage:
    - Raw format: /api/attendees/statistics/demographics/?format=raw
    - ECharts format: /api/attendees/statistics/demographics/?format=echarts
    - Event-specific: /api/attendees/statistics/demographics/?event_id=<uuid>
    - Date filtering: /api/attendees/statistics/registration-trends/?date_from=2026-01-01&date_to=2026-03-01
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

from apps.attendee import statistics
from apps.attendee.models import Attendee
from apps.attendee.api.serializers.statistics import (
    AgeDistributionSerializer,
    GenderDistributionSerializer,
    RelationshipDistributionSerializer,
    AreaDistributionSerializer,
    LocationBreakdownSerializer,
    MedicalConditionsStatsSerializer,
    AccessibilityRequirementsStatsSerializer,
    DietaryRequirementsStatsSerializer,
    EmergencyContactStatsSerializer,
    ConsentStatsSerializer,
    AttendeeRegistrationTrendsSerializer,
    AttendanceStatsSerializer,
    PersonalInfoCombinedSerializer,
    AttendeeOverviewStatsSerializer,
    DemographicsSerializer,
)


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
    description='Include soft-deleted attendees in statistics.',
    required=False,
    default=False,
)

AGE_GROUPING_PARAM = OpenApiParameter(
    name='age_grouping',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description='Age grouping method. "ranges" groups into standard age ranges (0-12, 13-17, etc.). "individual" shows each age separately.',
    required=False,
    enum=['ranges', 'individual'],
    default='ranges',
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


# ============================================================================
# STATISTICS VIEWSET
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Available statistics endpoints",
        description="Lists all available statistics endpoints with descriptions.",
        tags=["Attendee Statistics"],
    )
)
class AttendeeStatisticsViewSet(viewsets.GenericViewSet):
    """
    ViewSet for attendee statistics.
    
    Provides comprehensive statistical analysis of attendee data including:
    - Demographics (age, gender, relationships, areas)
    - Personal information (medical, accessibility, dietary, emergency contacts)
    - Consents and completion rates
    - Registration trends over time
    - Attendance check-in statistics
    
    All endpoints support:
    - Event-specific filtering via ?event_id parameter
    - Raw or ECharts-ready format via ?format parameter
    - Soft-deleted attendee inclusion via ?include_deleted parameter
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = AttendeeOverviewStatsSerializer  # Default serializer
    queryset = Attendee.objects.none()  # Schema generation model hint
    
    def _get_common_filters(self, request):
        """Extract common filter parameters from request."""
        return {
            'event_id': request.query_params.get('event_id'),
            'include_deleted': request.query_params.get('include_deleted', 'false').lower() == 'true',
        }
    
    def _add_filter_metadata(self, data, request):
        """Add filter metadata to response."""
        filters_applied = {}
        
        event_id = request.query_params.get('event_id')
        if event_id:
            filters_applied['event_id'] = event_id
        
        include_deleted = request.query_params.get('include_deleted', 'false').lower() == 'true'
        if include_deleted:
            filters_applied['include_deleted'] = True
        
        data['filters_applied'] = filters_applied
        data['generated_at'] = timezone.now()
        
        return data
    
    def list(self, request):
        """
        List all available statistics endpoints.
        """
        endpoints = {
            'demographics': 'Combined demographics statistics (age, gender, relationships, areas)',
            'age-distribution': 'Age distribution with configurable grouping',
            'gender-distribution': 'Gender distribution breakdown',
            'relationship-distribution': 'Relationship to user distribution',
            'area-distribution': 'Geographic area distribution',
            'location-breakdown': 'Combined location distribution by area, chapter, cluster, and country',
            'personal-info': 'Combined personal information statistics',
            'medical-conditions': 'Medical conditions breakdown with severity',
            'accessibility': 'Accessibility requirements statistics',
            'dietary': 'Dietary requirements statistics',
            'emergency-contacts': 'Emergency contact statistics',
            'consents': 'Consent completion and approval rates (requires event_id)',
            'registration-trends': 'Registration trends over time',
            'attendance': 'Check-in and attendance statistics',
            'overview': 'Combined overview for dashboard display',
        }
        
        return Response({
            'endpoints': endpoints,
            'common_parameters': {
                'event_id': 'UUID - Filter to specific event',
                'format': '"raw" or "echarts" - Response format',
                'include_deleted': 'Boolean - Include soft-deleted attendees',
            }
        })
    
    @extend_schema(
        summary="Demographics statistics",
        description="Combined demographics including age, gender, relationships, and areas.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM, AGE_GROUPING_PARAM],
        responses={200: DemographicsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'])
    def demographics(self, request):
        """Get combined demographics statistics."""
        filters = self._get_common_filters(request)
        age_grouping = request.query_params.get('age_grouping', 'ranges')
        
        data = {
            'gender': statistics.calculate_gender_distribution(**filters),
            'age': statistics.calculate_age_distribution(grouping=age_grouping, **filters),
            'relationships': statistics.calculate_relationship_distribution(**filters),
            'areas': statistics.calculate_area_distribution(**filters),
        }
        
        data = self._add_filter_metadata(data, request)
        serializer = DemographicsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Age distribution",
        description="Age distribution of attendees with configurable grouping (ranges or individual ages).",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM, AGE_GROUPING_PARAM],
        responses={200: AgeDistributionSerializer},
        tags=["Attendee Statistics"],
        examples=[
            OpenApiExample(
                'Raw Format Example',
                value={
                    'total_with_age': 150,
                    'total_without_age': 10,
                    'average_age': 32.5,
                    'distribution': [
                        {'label': '18-25', 'value': 45, 'percentage': 30.0},
                        {'label': '26-35', 'value': 60, 'percentage': 40.0},
                    ],
                    'generated_at': '2026-03-09T12:00:00Z',
                    'filters_applied': {'event_id': 'some-uuid'}
                },
                response_only=True,
            ),
        ]
    )
    @action(detail=False, methods=['get'], url_path='age-distribution')
    def age_distribution(self, request):
        """Get age distribution statistics."""
        filters = self._get_common_filters(request)
        grouping = request.query_params.get('age_grouping', 'ranges')
        
        data = statistics.calculate_age_distribution(grouping=grouping, **filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = AgeDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Gender distribution",
        description="Gender distribution breakdown of attendees.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: GenderDistributionSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='gender-distribution')
    def gender_distribution(self, request):
        """Get gender distribution statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_gender_distribution(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = GenderDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Relationship distribution",
        description="Distribution of attendee relationships to registered users.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: RelationshipDistributionSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='relationship-distribution')
    def relationship_distribution(self, request):
        """Get relationship distribution statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_relationship_distribution(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = RelationshipDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Area distribution",
        description="Geographic area distribution of attendees.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: AreaDistributionSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='area-distribution')
    def area_distribution(self, request):
        """Get area distribution statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_area_distribution(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = AreaDistributionSerializer(data, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Location breakdown",
        description="Combined attendee location breakdown by area, chapter, cluster, and country.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: LocationBreakdownSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='location-breakdown')
    def location_breakdown(self, request):
        """Get combined location breakdown statistics."""
        filters = self._get_common_filters(request)

        data = statistics.calculate_location_breakdown(**filters)
        data = self._add_filter_metadata(data, request)

        serializer = LocationBreakdownSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Personal information statistics",
        description="Combined statistics for medical conditions, accessibility, dietary, and emergency contacts.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: PersonalInfoCombinedSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='personal-info')
    def personal_info(self, request):
        """Get combined personal information statistics."""
        filters = self._get_common_filters(request)
        
        data = {
            'total_attendees': statistics._get_base_queryset(
                filters['event_id'], 
                filters['include_deleted']
            ).count(),
            'medical': statistics.calculate_medical_conditions_stats(**filters),
            'accessibility': statistics.calculate_accessibility_requirements_stats(**filters),
            'dietary': statistics.calculate_dietary_requirements_stats(**filters),
            'emergency_contacts': statistics.calculate_emergency_contact_stats(**filters),
        }
        
        data = self._add_filter_metadata(data, request)
        serializer = PersonalInfoCombinedSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Medical conditions statistics",
        description="Detailed breakdown of medical conditions with severity distribution.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: MedicalConditionsStatsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='medical-conditions')
    def medical_conditions(self, request):
        """Get medical conditions statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_medical_conditions_stats(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = MedicalConditionsStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Accessibility requirements statistics",
        description="Breakdown of accessibility requirements by type.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: AccessibilityRequirementsStatsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'])
    def accessibility(self, request):
        """Get accessibility requirements statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_accessibility_requirements_stats(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = AccessibilityRequirementsStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Dietary requirements statistics",
        description="Breakdown of dietary requirements by type.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: DietaryRequirementsStatsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'])
    def dietary(self, request):
        """Get dietary requirements statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_dietary_requirements_stats(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = DietaryRequirementsStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Emergency contacts statistics",
        description="Statistics about emergency contacts and relationship types.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: EmergencyContactStatsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='emergency-contacts')
    def emergency_contacts(self, request):
        """Get emergency contacts statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_emergency_contact_stats(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = EmergencyContactStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Consent statistics",
        description="Consent completion and approval rates. Requires event_id parameter.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: ConsentStatsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'])
    def consents(self, request):
        """Get consent statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_consent_stats(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = ConsentStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Registration trends",
        description="Attendee registration trends over time with configurable grouping.",
        parameters=[
            EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM,
            GROUP_BY_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM
        ],
        responses={200: AttendeeRegistrationTrendsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'], url_path='registration-trends')
    def registration_trends(self, request):
        """Get registration trends statistics."""
        filters = self._get_common_filters(request)
        
        # Parse date parameters
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        if date_from:
            try:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date_from format. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if date_to:
            try:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date_to format. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        group_by = request.query_params.get('group_by', 'day')
        
        data = statistics.calculate_registration_trends(
            group_by=group_by,
            date_from=date_from,
            date_to=date_to,
            **filters
        )
        data = self._add_filter_metadata(data, request)
        
        serializer = AttendeeRegistrationTrendsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Attendance statistics",
        description="Check-in and attendance statistics with trends over time.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: AttendanceStatsSerializer},
        tags=["Attendee Statistics"],
    )
    @action(detail=False, methods=['get'])
    def attendance(self, request):
        """Get attendance statistics."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_attendance_stats(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = AttendanceStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Overview statistics",
        description="Combined overview statistics ideal for dashboard display.",
        parameters=[EVENT_ID_PARAM, FORMAT_PARAM, INCLUDE_DELETED_PARAM],
        responses={200: AttendeeOverviewStatsSerializer},
        tags=["Attendee Statistics"],
        examples=[
            OpenApiExample(
                'Overview Response',
                value={
                    'total_attendees': 250,
                    'demographics': {
                        'gender': {'total': 250, 'distribution': []},
                        'age': {'total_with_age': 240, 'distribution': []},
                        'relationships': {'total': 250, 'distribution': []},
                    },
                    'personal_info': {
                        'medical_conditions': 45,
                        'accessibility_requirements': 12,
                        'dietary_requirements': 78,
                        'emergency_contacts': 230
                    },
                    'generated_at': '2026-03-09T12:00:00Z'
                },
                response_only=True,
            ),
        ]
    )
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get overview statistics for dashboard."""
        filters = self._get_common_filters(request)
        
        data = statistics.calculate_overview_stats(**filters)
        data = self._add_filter_metadata(data, request)
        
        serializer = AttendeeOverviewStatsSerializer(data, context={'request': request})
        return Response(serializer.data)
