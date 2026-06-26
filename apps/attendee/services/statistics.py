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
import uuid

from django.db.models import Count
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
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
        # support UUIDs or url_safe_titles

        try:
            uuid_obj = uuid.UUID(event_id, version=4)
            queryset = queryset.filter(event__event_id=event_id)

        except ValueError:
            queryset = queryset.filter(event__url_safe_title=event_id)


    
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


def _calculate_location_distribution(
    queryset,
    total_count: int,
    name: str,
    label_field: str,
    code_field: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a location distribution block for a specific hierarchy level."""
    values = [label_field]
    if code_field:
        values.append(code_field)

    counts = queryset.filter(
        **{f'{label_field}__isnull': False}
    ).values(
        *values
    ).annotate(
        count=Count('id')
    ).order_by('-count')

    without_value = queryset.filter(
        **{f'{label_field}__isnull': True}
    ).count()

    distribution = []
    for item in counts:
        label = item.get(label_field)
        if label is None:
            continue

        row = {
            'label': label,
            'value': item['count'],
            'percentage': round((item['count'] / total_count * 100), 2) if total_count > 0 else 0,
        }
        if code_field:
            row['code'] = item.get(code_field)
        distribution.append(row)

    return {
        f'total_with_{name}': total_count - without_value,
        f'total_without_{name}': without_value,
        'distribution': distribution,
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

    area_data = _calculate_location_distribution(
        queryset=queryset,
        total_count=total_count,
        name='area',
        label_field='area_from__area_name',
        code_field='area_from__area_code',
    )

    return {
        'total': total_count,
        'total_with_area': area_data['total_with_area'],
        'total_without_area': area_data['total_without_area'],
        'distribution': area_data['distribution']
    }


def calculate_location_breakdown(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate attendee breakdown across all available location hierarchy levels.

    Args:
        event_id: Optional event UUID to filter attendees
        include_deleted: Whether to include soft-deleted attendees

    Returns:
        Dictionary with area, chapter, cluster, and country distributions
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    total_count = queryset.count()

    by_area = _calculate_location_distribution(
        queryset=queryset,
        total_count=total_count,
        name='area',
        label_field='area_from__area_name',
        code_field='area_from__area_code',
    )
    by_chapter = _calculate_location_distribution(
        queryset=queryset,
        total_count=total_count,
        name='chapter',
        label_field='area_from__chapter__chapter_name',
    )
    by_cluster = _calculate_location_distribution(
        queryset=queryset,
        total_count=total_count,
        name='cluster',
        label_field='area_from__chapter__cluster__cluster_name',
    )
    by_country = _calculate_location_distribution(
        queryset=queryset,
        total_count=total_count,
        name='country',
        label_field='area_from__chapter__cluster__country__country',
    )

    return {
        'total': total_count,
        'by_area': by_area,
        'by_chapter': by_chapter,
        'by_cluster': by_cluster,
        'by_country': by_country,
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


# ============================================================================
# CHECK-IN DAY STATISTICS
# ============================================================================

def calculate_checkin_stats_by_day(
    event_id: Optional[str] = None,
    event_day: Optional[int] = None,
    include_deleted: bool = False,
) -> Dict[str, Any]:
    """
    Calculate per-event-day check-in statistics.

    Day 1 = event start calendar date (event timezone).
    Negative day values = check-ins before the event.
    Values > event duration = check-ins after the event window.

    Args:
        event_id:        Optional event UUID to scope results.
        event_day:       If provided, return statistics for that specific day only.
        include_deleted: Whether to include soft-deleted attendees.

    Returns:
        Dict with keys: days, total_attendees, event_days_count, event_metadata
    """
    from apps.attendee.models import AttendeeCheckIn, CheckInAction, CheckInScanResult
    from apps.events.models import Event
    from django.db.models import Max
    import pytz

    attendee_qs = _get_base_queryset(event_id, include_deleted)
    total_attendees = attendee_qs.count()

    # Resolve event for day-label computation
    event = None
    event_tz = pytz.UTC
    event_start_date = None
    event_days_count = None

    if event_id:
        try:
            event = Event.objects.filter(event_id=event_id).first()
            if event:
                if hasattr(event, 'timezone') and event.timezone:
                    event_tz = pytz.timezone(str(event.timezone))
                event_start_date = event.start_datetime.astimezone(event_tz).date()
                event_end_date = event.end_datetime.astimezone(event_tz).date()
                event_days_count = (event_end_date - event_start_date).days + 1
        except Exception:
            pass

    # Successful CHECK_IN records scoped to this event
    checkin_qs = AttendeeCheckIn.objects.filter(
        attendee__in=attendee_qs,
        action=CheckInAction.CHECK_IN,
        scan_result=CheckInScanResult.SUCCESS,
    )
    if event_day is not None:
        checkin_qs = checkin_qs.filter(event_day=event_day)

    # Per-day aggregate: count of distinct attendees who checked in
    per_day_rows = (
        checkin_qs
        .values('event_day')
        .annotate(
            checked_in_count=Count('attendee_id', distinct=True),
        )
        .order_by('event_day')
    )

    # Hourly breakdown per day (for trend chart)
    from django.db.models.functions import TruncHour
    hourly_qs = (
        checkin_qs
        .annotate(hour=TruncHour('performed_at'))
        .values('event_day', 'hour')
        .annotate(count=Count('check_in_id'))
        .order_by('event_day', 'hour')
    )

    # Build hourly map: {event_day: [{hour, count}, ...]}
    hourly_map: Dict[int, List[Dict]] = {}
    for row in hourly_qs:
        day_key = row['event_day']
        if day_key is None:
            continue
        if day_key not in hourly_map:
            hourly_map[day_key] = []
        hourly_map[day_key].append({
            'hour': row['hour'].astimezone(event_tz).strftime('%H:%M') if row['hour'] else None,
            'count': row['count'],
        })

    # Build per-day result list
    days_data = []
    for row in per_day_rows:
        day_num = row['event_day']
        checked_in = row['checked_in_count']
        not_checked_in = total_attendees - checked_in

        # Derive calendar date label
        day_date = None
        if event_start_date and day_num is not None:
            try:
                day_date = (event_start_date + timedelta(days=day_num - 1)).isoformat()
            except Exception:
                pass

        days_data.append({
            'event_day': day_num,
            'date': day_date,
            'checked_in': checked_in,
            'not_checked_in': not_checked_in,
            'total_attendees': total_attendees,
            'check_in_rate': round(checked_in / total_attendees * 100, 2) if total_attendees > 0 else 0,
            'hourly_timeline': hourly_map.get(day_num, []),
        })

    # If no checkins yet, return empty list (still useful to know total_attendees)
    return {
        'days': days_data,
        'total_attendees': total_attendees,
        'event_days_count': event_days_count,
        'event_metadata': {
            'event_id': event_id,
            'start_date': event_start_date.isoformat() if event_start_date else None,
            'end_date': (event_start_date + timedelta(days=event_days_count - 1)).isoformat()
                if event_start_date and event_days_count else None,
            'timezone': str(event_tz),
        },
        'generated_at': timezone.now().isoformat(),
    }
