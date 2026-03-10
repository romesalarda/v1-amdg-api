"""
Attendee Statistics Calculation Module

This module provides calculation functions for attendee-related statistics.
Each function returns structured data suitable for both raw JSON and ECharts formatting.

Functions are designed to be:
- Event-scoped or global (via optional event_id parameter)
- Efficient (using Django ORM aggregations)
- Extensible (easy to add new statistics)
- Testable (pure functions with clear inputs/outputs)
"""
from django.db.models import Count, Q, Avg, F, Value, CharField, Case, When, IntegerField
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, ExtractYear
from django.utils import timezone
from datetime import date, timedelta
from typing import Optional, Dict, List, Any

from apps.attendee.models import (
    Attendee, AttendeeMedicalCondition, AttendeeAccessibilityRequirement,
    AttendeeDietaryRequirement, AttendeeConsent, EmergencyContact, EventAttendance
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_base_queryset(event_id: Optional[str] = None, include_deleted: bool = False):
    """
    Get base attendee queryset with common filters applied.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Filtered queryset of attendees
    """
    queryset = Attendee.all_objects.all()
    
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    return queryset


def _calculate_age(date_of_birth: date) -> int:
    """Calculate age from date of birth."""
    today = date.today()
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )


def _group_age(age: int) -> str:
    """Group age into standard ranges."""
    if age < 13:
        return '0-12'
    elif age < 18:
        return '13-17'
    elif age < 26:
        return '18-25'
    elif age < 36:
        return '26-35'
    elif age < 46:
        return '36-45'
    elif age < 61:
        return '46-60'
    else:
        return '60+'


# ============================================================================
# DEMOGRAPHIC STATISTICS
# ============================================================================

def calculate_age_distribution(
    event_id: Optional[str] = None,
    grouping: str = 'ranges',
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate age distribution of attendees.
    
    Args:
        event_id: Optional event UUID to filter attendees
        grouping: 'ranges' for age ranges or 'individual' for each age
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with age distribution data:
        {
            'total_with_age': int,
            'total_without_age': int,
            'distribution': [{'label': str, 'value': int, 'percentage': float}, ...],
            'average_age': float or None
        }
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    total_count = queryset.count()
    with_age = queryset.filter(date_of_birth__isnull=False)
    total_with_age = with_age.count()
    total_without_age = total_count - total_with_age
    
    # Calculate ages
    age_data = []
    for attendee in with_age.only('date_of_birth'):
        age = _calculate_age(attendee.date_of_birth)
        age_data.append(age)
    
    # Calculate average
    average_age = sum(age_data) / len(age_data) if age_data else None
    
    # Group ages
    if grouping == 'ranges':
        age_groups = {}
        for age in age_data:
            group = _group_age(age)
            age_groups[group] = age_groups.get(group, 0) + 1
        
        # Ensure all ranges are present
        all_ranges = ['0-12', '13-17', '18-25', '26-35', '36-45', '46-60', '60+']
        distribution = [
            {
                'label': range_label,
                'value': age_groups.get(range_label, 0),
                'percentage': round((age_groups.get(range_label, 0) / total_with_age * 100), 2) if total_with_age > 0 else 0
            }
            for range_label in all_ranges
        ]
    else:  # individual
        from collections import Counter
        age_counts = Counter(age_data)
        distribution = [
            {
                'label': str(age),
                'value': count,
                'percentage': round((count / total_with_age * 100), 2) if total_with_age > 0 else 0
            }
            for age, count in sorted(age_counts.items())
        ]
    
    return {
        'total_with_age': total_with_age,
        'total_without_age': total_without_age,
        'distribution': distribution,
        'average_age': round(average_age, 1) if average_age else None
    }


def calculate_gender_distribution(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate gender distribution of attendees.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with gender distribution data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    total_count = queryset.count()
    
    # Get gender counts
    gender_counts = queryset.values('gender').annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in gender_counts:
        gender = item['gender'] or 'Not Specified'
        count = item['count']
        distribution.append({
            'label': gender,
            'value': count,
            'percentage': round((count / total_count * 100), 2) if total_count > 0 else 0
        })
    
    return {
        'total': total_count,
        'distribution': distribution
    }


def calculate_relationship_distribution(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of attendee relationships to users.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with relationship distribution data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    total_count = queryset.count()
    
    # Get relationship counts
    relationship_counts = queryset.values(
        'relationship_to_user'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in relationship_counts:
        relationship = item['relationship_to_user']
        count = item['count']
        # Get display name from choices
        from apps.attendee.models.attendee import AttendeeRelationship
        label = dict(AttendeeRelationship.choices).get(relationship, relationship)
        
        distribution.append({
            'label': label,
            'value': count,
            'code': relationship,
            'percentage': round((count / total_count * 100), 2) if total_count > 0 else 0
        })
    
    return {
        'total': total_count,
        'distribution': distribution
    }


def calculate_area_distribution(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of attendees by area location.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with area distribution data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    total_count = queryset.count()
    
    # Get area counts
    area_counts = queryset.filter(
        area_from__isnull=False
    ).values(
        'area_from__area_name'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    without_area = queryset.filter(area_from__isnull=True).count()
    
    distribution = []
    for item in area_counts:
        area = item['area_from__area_name']
        count = item['count']
        distribution.append({
            'label': area,
            'value': count,
            'percentage': round((count / total_count * 100), 2) if total_count > 0 else 0
        })
    
    return {
        'total': total_count,
        'total_with_area': total_count - without_area,
        'total_without_area': without_area,
        'distribution': distribution
    }


# ============================================================================
# PERSONAL INFORMATION STATISTICS
# ============================================================================

def calculate_medical_conditions_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate statistics about medical conditions.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with medical conditions statistics
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    total_attendees = queryset.count()
    
    # Get attendees with medical conditions
    attendees_with_conditions = queryset.filter(
        attendeemedicalcondition__isnull=False
    ).distinct().count()
    
    # Get condition breakdown
    condition_counts = AttendeeMedicalCondition.objects.filter(
        attendee__in=queryset
    ).values(
        'medical_condition__label',
        'medical_condition__code'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    conditions = [
        {
            'label': item['medical_condition__label'],
            'code': item['medical_condition__code'],
            'value': item['count'],
            'percentage': round((item['count'] / total_attendees * 100), 2) if total_attendees > 0 else 0
        }
        for item in condition_counts
    ]
    
    # Get severity breakdown
    severity_counts = AttendeeMedicalCondition.objects.filter(
        attendee__in=queryset,
        severity__isnull=False
    ).values('severity').annotate(
        count=Count('id')
    ).order_by('-count')
    
    severity_distribution = [
        {
            'label': item['severity'].title() if item['severity'] else 'Not Specified',
            'value': item['count'],
            'percentage': round((item['count'] / attendees_with_conditions * 100), 2) if attendees_with_conditions > 0 else 0
        }
        for item in severity_counts
    ]
    
    return {
        'total_attendees': total_attendees,
        'attendees_with_conditions': attendees_with_conditions,
        'attendees_without_conditions': total_attendees - attendees_with_conditions,
        'conditions': conditions,
        'severity_distribution': severity_distribution
    }


def calculate_accessibility_requirements_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate statistics about accessibility requirements.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with accessibility requirements statistics
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    total_attendees = queryset.count()
    
    # Get attendees with accessibility requirements
    attendees_with_requirements = queryset.filter(
        attendeeaccessibilityrequirement__isnull=False
    ).distinct().count()
    
    # Get requirement breakdown
    requirement_counts = AttendeeAccessibilityRequirement.objects.filter(
        attendee__in=queryset
    ).values(
        'accessibility_requirement__label',
        'accessibility_requirement__code'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    requirements = [
        {
            'label': item['accessibility_requirement__label'],
            'code': item['accessibility_requirement__code'],
            'value': item['count'],
            'percentage': round((item['count'] / total_attendees * 100), 2) if total_attendees > 0 else 0
        }
        for item in requirement_counts
    ]
    
    return {
        'total_attendees': total_attendees,
        'attendees_with_requirements': attendees_with_requirements,
        'attendees_without_requirements': total_attendees - attendees_with_requirements,
        'requirements': requirements
    }


def calculate_dietary_requirements_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate statistics about dietary requirements.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with dietary requirements statistics
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    total_attendees = queryset.count()
    
    # Get attendees with dietary requirements
    attendees_with_requirements = queryset.filter(
        attendeedietaryrequirement__isnull=False
    ).distinct().count()
    
    # Get requirement breakdown
    requirement_counts = AttendeeDietaryRequirement.objects.filter(
        attendee__in=queryset
    ).values(
        'dietary_requirement__label',
        'dietary_requirement__code'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    requirements = [
        {
            'label': item['dietary_requirement__label'],
            'code': item['dietary_requirement__code'],
            'value': item['count'],
            'percentage': round((item['count'] / total_attendees * 100), 2) if total_attendees > 0 else 0
        }
        for item in requirement_counts
    ]
    
    return {
        'total_attendees': total_attendees,
        'attendees_with_requirements': attendees_with_requirements,
        'attendees_without_requirements': total_attendees - attendees_with_requirements,
        'requirements': requirements
    }


def calculate_emergency_contact_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate statistics about emergency contacts.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with emergency contact statistics
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    total_attendees = queryset.count()
    
    # Get attendees with emergency contacts
    attendees_with_contacts = queryset.filter(
        emergency_contacts__isnull=False
    ).distinct().count()
    
    # Get relationship breakdown
    relationship_counts = EmergencyContact.objects.filter(
        attendee__in=queryset
    ).values('relationship').annotate(
        count=Count('id')
    ).order_by('-count')
    
    relationships = [
        {
            'label': item['relationship'].title(),
            'value': item['count'],
            'percentage': round((item['count'] / attendees_with_contacts * 100), 2) if attendees_with_contacts > 0 else 0
        }
        for item in relationship_counts
    ]
    
    return {
        'total_attendees': total_attendees,
        'attendees_with_contacts': attendees_with_contacts,
        'attendees_without_contacts': total_attendees - attendees_with_contacts,
        'relationships': relationships
    }


# ============================================================================
# CONSENT STATISTICS
# ============================================================================

def calculate_consent_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate statistics about consent completion.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with consent statistics
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    total_attendees = queryset.count()
    
    if not event_id:
        # Global consent stats don't make sense without event context
        return {
            'total_attendees': total_attendees,
            'message': 'Consent statistics require event_id parameter'
        }
    
    # Get all consents for the event
    from apps.attendee.models.personal.consent import Consent
    event_consents = Consent.objects.filter(
        event__event_id=event_id,
        active=True
    )
    
    consent_breakdown = []
    for consent in event_consents:
        total_responses = AttendeeConsent.objects.filter(
            attendee__in=queryset,
            consent=consent
        ).count()
        
        given_count = AttendeeConsent.objects.filter(
            attendee__in=queryset,
            consent=consent,
            consent_given=True
        ).count()
        
        consent_breakdown.append({
            'consent_code': consent.code,
            'consent_title': consent.title,
            'required': consent.required,
            'total_responses': total_responses,
            'consents_given': given_count,
            'consents_declined': total_responses - given_count,
            'completion_rate': round((total_responses / total_attendees * 100), 2) if total_attendees > 0 else 0,
            'approval_rate': round((given_count / total_responses * 100), 2) if total_responses > 0 else 0
        })
    
    return {
        'total_attendees': total_attendees,
        'total_consents': event_consents.count(),
        'consent_breakdown': consent_breakdown
    }


# ============================================================================
# TIME-BASED STATISTICS
# ============================================================================

def calculate_registration_trends(
    event_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate registration trends over time.
    
    Args:
        event_id: Optional event UUID to filter attendees
        group_by: 'day', 'week', or 'month'
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with registration trend data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    # Apply date filtering
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    
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
    
    trend_data = [
        {
            'date': item['period'].isoformat(),
            'count': item['count']
        }
        for item in trends
    ]
    
    return {
        'total_attendees': queryset.count(),
        'group_by': group_by,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'trends': trend_data
    }


def calculate_attendance_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate attendance check-in statistics.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with attendance statistics
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    total_attendees = queryset.count()
    
    # Get attendance records
    attendance_queryset = EventAttendance.objects.filter(
        attendee__in=queryset
    )
    
    if event_id:
        attendance_queryset = attendance_queryset.filter(
            event__event_id=event_id
        )
    
    checked_in = attendance_queryset.filter(check_in_time__isnull=False).count()
    not_checked_in = total_attendees - checked_in
    
    # Get check-in trend (by date)
    checkin_trends = attendance_queryset.filter(
        check_in_time__isnull=False
    ).annotate(
        date=TruncDate('check_in_time')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')
    
    trend_data = [
        {
            'date': item['date'].isoformat(),
            'count': item['count']
        }
        for item in checkin_trends
    ]
    
    return {
        'total_attendees': total_attendees,
        'checked_in': checked_in,
        'not_checked_in': not_checked_in,
        'check_in_rate': round((checked_in / total_attendees * 100), 2) if total_attendees > 0 else 0,
        'check_in_trends': trend_data
    }


# ============================================================================
# COMBINED OVERVIEW
# ============================================================================

def calculate_overview_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate combined overview statistics for dashboard.
    
    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees
    
    Returns:
        Dictionary with overview statistics
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    return {
        'total_attendees': queryset.count(),
        'demographics': {
            'gender': calculate_gender_distribution(event_id, include_deleted),
            'age': calculate_age_distribution(event_id, 'ranges', include_deleted),
            'relationships': calculate_relationship_distribution(event_id, include_deleted),
        },
        'personal_info': {
            'medical_conditions': queryset.filter(
                attendeemedicalcondition__isnull=False
            ).distinct().count(),
            'accessibility_requirements': queryset.filter(
                attendeeaccessibilityrequirement__isnull=False
            ).distinct().count(),
            'dietary_requirements': queryset.filter(
                attendeedietaryrequirement__isnull=False
            ).distinct().count(),
            'emergency_contacts': queryset.filter(
                emergency_contacts__isnull=False
            ).distinct().count(),
        },
        'generated_at': timezone.now().isoformat()
    }
