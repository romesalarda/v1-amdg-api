"""
Statistics Serializers Module

Serializers for attendee statistics endpoints.
Support both raw data format and ECharts-ready format based on context.
"""
from rest_framework import serializers
from django.utils import timezone
from typing import Dict, Any

from apps.attendee import formatters


class BaseStatisticsSerializer(serializers.Serializer):
    """
    Base serializer for all statistics responses.
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


class AgeDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for age distribution statistics."""
    total_with_age = serializers.IntegerField()
    total_without_age = serializers.IntegerField()
    average_age = serializers.FloatField(allow_null=True)
    distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format age distribution as bar chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_bar_chart(
            data=distribution,
            title='Age Distribution',
            x_axis_label='Age Range',
            y_axis_label='Number of Attendees'
        )


class GenderDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for gender distribution statistics."""
    total = serializers.IntegerField()
    distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format gender distribution as pie chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_pie_chart(
            data=distribution,
            title='Gender Distribution',
            subtitle=f"Total: {instance.get('total', 0)} attendees"
        )


class RelationshipDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for relationship distribution statistics."""
    total = serializers.IntegerField()
    distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format relationship distribution as pie chart."""
        distribution = instance.get('distribution', [])
        return formatters.format_pie_chart(
            data=distribution,
            title='Relationship to User Distribution',
            subtitle=f"Total: {instance.get('total', 0)} attendees"
        )


class AreaDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for area distribution statistics."""
    total = serializers.IntegerField()
    total_with_area = serializers.IntegerField()
    total_without_area = serializers.IntegerField()
    distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format area distribution as horizontal bar chart."""
        distribution = instance.get('distribution', [])
        # Sort by value descending for better visualization
        sorted_data = sorted(distribution, key=lambda x: x['value'], reverse=True)
        return formatters.format_bar_chart(
            data=sorted_data[:15],  # Top 15 areas
            title='Top Areas by Attendee Count',
            x_axis_label='Number of Attendees',
            y_axis_label='Area',
            orientation='horizontal'
        )


class LocationBreakdownSerializer(BaseStatisticsSerializer):
    """Serializer for combined location breakdown statistics."""
    total = serializers.IntegerField()
    by_area = serializers.DictField()
    by_chapter = serializers.DictField()
    by_cluster = serializers.DictField()
    by_country = serializers.DictField()

    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format each location level as a horizontal bar chart."""
        chart_map = {}
        sections = {
            'areas': ('by_area', 'Areas'),
            'chapters': ('by_chapter', 'Chapters'),
            'clusters': ('by_cluster', 'Clusters'),
            'countries': ('by_country', 'Countries'),
        }

        for key, (section_key, title_name) in sections.items():
            distribution = instance.get(section_key, {}).get('distribution', [])
            if not distribution:
                continue

            sorted_data = sorted(distribution, key=lambda x: x['value'], reverse=True)
            chart_map[key] = formatters.format_bar_chart(
                data=sorted_data[:15],
                title=f'Top {title_name} by Attendee Count',
                x_axis_label='Number of Attendees',
                y_axis_label=title_name[:-1] if title_name.endswith('s') else title_name,
                orientation='horizontal'
            )

        return chart_map


class MedicalConditionsStatsSerializer(BaseStatisticsSerializer):
    """Serializer for medical conditions statistics."""
    total_attendees = serializers.IntegerField()
    attendees_with_conditions = serializers.IntegerField()
    attendees_without_conditions = serializers.IntegerField()
    conditions = serializers.ListField(
        child=serializers.DictField()
    )
    severity_distribution = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format medical conditions with severity breakdown."""
        conditions = instance.get('conditions', [])
        severity = instance.get('severity_distribution', [])
        
        # Create main conditions bar chart
        conditions_chart = formatters.format_bar_chart(
            data=sorted(conditions, key=lambda x: x['value'], reverse=True)[:10],
            title='Top 10 Medical Conditions',
            x_axis_label='Condition',
            y_axis_label='Number of Attendees'
        )
        
        # Create severity pie chart
        severity_chart = formatters.format_severity_pie_chart(
            data=severity,
            title='Severity Distribution'
        )
        
        return {
            'conditions': conditions_chart,
            'severity': severity_chart
        }


class AccessibilityRequirementsStatsSerializer(BaseStatisticsSerializer):
    """Serializer for accessibility requirements statistics."""
    total_attendees = serializers.IntegerField()
    attendees_with_requirements = serializers.IntegerField()
    attendees_without_requirements = serializers.IntegerField()
    requirements = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format accessibility requirements as bar chart."""
        requirements = instance.get('requirements', [])
        return formatters.format_bar_chart(
            data=sorted(requirements, key=lambda x: x['value'], reverse=True),
            title='Accessibility Requirements',
            x_axis_label='Requirement Type',
            y_axis_label='Number of Attendees'
        )


class DietaryRequirementsStatsSerializer(BaseStatisticsSerializer):
    """Serializer for dietary requirements statistics."""
    total_attendees = serializers.IntegerField()
    attendees_with_requirements = serializers.IntegerField()
    attendees_without_requirements = serializers.IntegerField()
    requirements = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format dietary requirements as bar chart."""
        requirements = instance.get('requirements', [])
        return formatters.format_bar_chart(
            data=sorted(requirements, key=lambda x: x['value'], reverse=True),
            title='Dietary Requirements',
            x_axis_label='Requirement Type',
            y_axis_label='Number of Attendees'
        )


class EmergencyContactStatsSerializer(BaseStatisticsSerializer):
    """Serializer for emergency contact statistics."""
    total_attendees = serializers.IntegerField()
    attendees_with_contacts = serializers.IntegerField()
    attendees_without_contacts = serializers.IntegerField()
    relationships = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format emergency contact relationships as pie chart."""
        relationships = instance.get('relationships', [])
        return formatters.format_pie_chart(
            data=relationships,
            title='Emergency Contact Relationships',
            subtitle=f"Total contacts: {sum(r['value'] for r in relationships)}"
        )


class ConsentStatsSerializer(BaseStatisticsSerializer):
    """Serializer for consent statistics."""
    total_attendees = serializers.IntegerField()
    total_consents = serializers.IntegerField()
    consent_breakdown = serializers.ListField(
        child=serializers.DictField()
    )
    message = serializers.CharField(required=False)
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format consent statistics with completion and approval rates."""
        consent_breakdown = instance.get('consent_breakdown', [])
        
        if not consent_breakdown:
            return None
        
        # Create completion rate chart
        completion_data = [
            {
                'label': item['consent_title'][:30] + '...' if len(item['consent_title']) > 30 else item['consent_title'],
                'value': item['completion_rate']
            }
            for item in consent_breakdown
        ]
        
        completion_chart = formatters.format_bar_chart(
            data=completion_data,
            title='Consent Completion Rates',
            x_axis_label='Consent Type',
            y_axis_label='Completion Rate (%)'
        )
        
        # Create approval rate chart
        approval_data = [
            {
                'label': item['consent_title'][:30] + '...' if len(item['consent_title']) > 30 else item['consent_title'],
                'value': item['approval_rate']
            }
            for item in consent_breakdown
        ]
        
        approval_chart = formatters.format_bar_chart(
            data=approval_data,
            title='Consent Approval Rates',
            x_axis_label='Consent Type',
            y_axis_label='Approval Rate (%)'
        )
        
        return {
            'completion': completion_chart,
            'approval': approval_chart
        }


class AttendeeRegistrationTrendsSerializer(BaseStatisticsSerializer):
    """Serializer for registration trends statistics."""
    total_attendees = serializers.IntegerField()
    group_by = serializers.CharField()
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)
    trends = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format registration trends as line chart."""
        trends = instance.get('trends', [])
        group_by = instance.get('group_by', 'day')
        
        return formatters.format_line_chart(
            data=trends,
            title=f'Registration Trends (by {group_by})',
            x_axis_label='Date',
            y_axis_label='Number of Registrations',
            smooth=True
        )


class AttendanceStatsSerializer(BaseStatisticsSerializer):
    """Serializer for attendance check-in statistics."""
    total_attendees = serializers.IntegerField()
    checked_in = serializers.IntegerField()
    not_checked_in = serializers.IntegerField()
    check_in_rate = serializers.FloatField()
    check_in_trends = serializers.ListField(
        child=serializers.DictField()
    )
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format attendance stats with gauge and line chart."""
        check_in_rate = instance.get('check_in_rate', 0)
        trends = instance.get('check_in_trends', [])
        
        # Create gauge for overall check-in rate
        gauge_chart = formatters.format_gauge_chart(
            value=check_in_rate,
            title='Overall Check-in Rate',
            max_value=100,
            unit='%'
        )
        
        # Create line chart for check-in trends
        line_chart = None
        if trends:
            line_chart = formatters.format_line_chart(
                data=trends,
                title='Check-in Trends Over Time',
                x_axis_label='Date',
                y_axis_label='Check-ins',
                smooth=True
            )
        
        return {
            'gauge': gauge_chart,
            'trends': line_chart
        }


class PersonalInfoCombinedSerializer(BaseStatisticsSerializer):
    """Serializer for combined personal info statistics."""
    total_attendees = serializers.IntegerField()
    medical = serializers.DictField()
    accessibility = serializers.DictField()
    dietary = serializers.DictField()
    emergency_contacts = serializers.DictField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format combined personal info as overview chart."""
        total = instance.get('total_attendees', 0)
        
        # Create summary data for pie chart showing coverage
        summary_data = [
            {
                'label': 'Medical Conditions',
                'value': instance.get('medical', {}).get('attendees_with_conditions', 0)
            },
            {
                'label': 'Accessibility Needs',
                'value': instance.get('accessibility', {}).get('attendees_with_requirements', 0)
            },
            {
                'label': 'Dietary Requirements',
                'value': instance.get('dietary', {}).get('attendees_with_requirements', 0)
            },
            {
                'label': 'Emergency Contacts',
                'value': instance.get('emergency_contacts', {}).get('attendees_with_contacts', 0)
            }
        ]
        
        return formatters.format_bar_chart(
            data=summary_data,
            title='Personal Information Coverage',
            x_axis_label='Information Type',
            y_axis_label='Number of Attendees'
        )


class AttendeeOverviewStatsSerializer(BaseStatisticsSerializer):
    """Serializer for overview/dashboard statistics."""
    total_attendees = serializers.IntegerField()
    demographics = serializers.DictField()
    personal_info = serializers.DictField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format overview stats with multiple charts.
        Returns a dict with multiple chart configurations.
        """
        demographics = instance.get('demographics', {})
        personal_info = instance.get('personal_info', {})
        
        charts = {}
        
        # Gender pie chart
        gender_data = demographics.get('gender', {}).get('distribution', [])
        if gender_data:
            charts['gender'] = formatters.format_donut_chart(
                data=gender_data,
                title='Gender Distribution',
                center_text=f"{instance.get('total_attendees', 0)}\nTotal"
            )
        
        # Age bar chart
        age_data = demographics.get('age', {}).get('distribution', [])
        if age_data:
            charts['age'] = formatters.format_bar_chart(
                data=age_data,
                title='Age Distribution',
                x_axis_label='Age Range',
                y_axis_label='Count'
            )
        
        # Personal info summary
        personal_summary = [
            {'label': 'Medical Conditions', 'value': personal_info.get('medical_conditions', 0)},
            {'label': 'Accessibility', 'value': personal_info.get('accessibility_requirements', 0)},
            {'label': 'Dietary', 'value': personal_info.get('dietary_requirements', 0)},
            {'label': 'Emergency Contacts', 'value': personal_info.get('emergency_contacts', 0)}
        ]
        
        charts['personal_info'] = formatters.format_bar_chart(
            data=personal_summary,
            title='Personal Information Summary',
            x_axis_label='Category',
            y_axis_label='Attendees with Info'
        )
        
        return charts


class DemographicsSerializer(BaseStatisticsSerializer):
    """Serializer for combined demographics statistics."""
    gender = serializers.DictField()
    age = serializers.DictField()
    relationships = serializers.DictField()
    areas = serializers.DictField()
    
    def format_for_echarts(self, representation: Dict[str, Any], instance: Dict[str, Any]) -> Dict[str, Any]:
        """Format demographics with multiple charts."""
        charts = {}
        
        # Gender chart
        gender_dist = instance.get('gender', {}).get('distribution', [])
        if gender_dist:
            charts['gender'] = formatters.format_pie_chart(
                data=gender_dist,
                title='Gender Distribution'
            )
        
        # Age chart
        age_dist = instance.get('age', {}).get('distribution', [])
        if age_dist:
            charts['age'] = formatters.format_bar_chart(
                data=age_dist,
                title='Age Distribution',
                x_axis_label='Age Range',
                y_axis_label='Count'
            )
        
        # Relationships chart
        rel_dist = instance.get('relationships', {}).get('distribution', [])
        if rel_dist:
            charts['relationships'] = formatters.format_pie_chart(
                data=rel_dist,
                title='Relationships'
            )
        
        # Areas chart (top 10)
        area_dist = instance.get('areas', {}).get('distribution', [])
        if area_dist:
            sorted_areas = sorted(area_dist, key=lambda x: x['value'], reverse=True)[:10]
            charts['areas'] = formatters.format_bar_chart(
                data=sorted_areas,
                title='Top 10 Areas',
                x_axis_label='Area',
                y_axis_label='Count',
                orientation='horizontal'
            )
        
        return charts
