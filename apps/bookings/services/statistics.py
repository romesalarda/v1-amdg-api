"""
Booking Statistics Calculation Module

This module provides calculation functions for booking-related statistics.
Each function returns structured data suitable for both raw JSON and ECharts formatting.

Functions are designed to be:
- Event-scoped or global (via optional event_id parameter)
- Organization-scoped (via optional organization_id parameter)
- Efficient (using Django ORM aggregations)
- Extensible (easy to add new statistics)
- Testable (pure functions with clear inputs/outputs)
"""
from django.db.models import Count, Q, Avg, F, Sum, Max, Min, Case, When, IntegerField, FloatField, Value
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, Coalesce
from django.utils import timezone
from datetime import date, datetime, time, timedelta
from typing import Optional, Dict, List, Any
from decimal import Decimal

from apps.bookings.models import (
    Booking, Ticket, BookingPackage, BookingPackageRule, 
    TicketType, BookingIntent, PackageProduct
)
from apps.attendee.models import Attendee
from apps.payments.models import Payment, PaymentStatusChoices
from django.contrib.contenttypes.models import ContentType


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_base_booking_queryset(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None
):
    """
    Get base booking queryset with common filters applied.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        include_deleted: Whether to include soft-deleted bookings (via attendees)
        status: Optional payment status to filter by
        date_from: Optional start date for filtering
        date_to: Optional end date for filtering
    
    Returns:
        Filtered queryset of bookings
    """
    queryset = Booking.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    if not include_deleted:
        # Bookings with at least one non-deleted attendee
        queryset = queryset.filter(attendees__deleted_at__isnull=True).distinct()
    
    if status:
        # Filter by payment status
        queryset = queryset.filter(
            payments__status=status
        ).distinct()
    
    if date_from:
        # Convert date to timezone-aware datetime at start of day
        if isinstance(date_from, date) and not isinstance(date_from, datetime):
            date_from = timezone.make_aware(datetime.combine(date_from, time.min))
        queryset = queryset.filter(booked_at__gte=date_from)
    
    if date_to:
        # Include the entire end date - convert to timezone-aware datetime at end of day
        if isinstance(date_to, date) and not isinstance(date_to, datetime):
            date_to = timezone.make_aware(datetime.combine(date_to, time.max))
        queryset = queryset.filter(booked_at__lte=date_to)
    
    return queryset


def _get_base_ticket_queryset(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False,
    status: Optional[str] = None
):
    """Get base ticket queryset with common filters applied."""
    queryset = Ticket.objects.all()
    
    if event_id:
        queryset = queryset.filter(attendee__event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(attendee__event__organisation_id=organization_id)
    
    if not include_deleted:
        queryset = queryset.filter(attendee__deleted_at__isnull=True)
    
    if status:
        queryset = queryset.filter(status=status)
    
    return queryset


def _get_base_intent_queryset(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
):
    """Get base booking intent queryset with common filters applied."""
    queryset = BookingIntent.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    
    return queryset


def _money_to_float(money_value) -> float:
    """Convert Money object to float for JSON serialization."""
    if money_value is None:
        return 0.0
    if isinstance(money_value, Decimal):
        return float(money_value)
    return float(money_value.amount)


# ============================================================================
# BOOKING STATISTICS
# ============================================================================

def calculate_booking_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate overview statistics for bookings.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        include_deleted: Whether to include soft-deleted bookings
    
    Returns:
        Dictionary with booking overview data
    """
    queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted)
    
    total_bookings = queryset.count()
    
    # Attendee statistics
    attendee_filter = Q(attendees__deleted_at__isnull=True) if not include_deleted else Q()
    total_attendees = queryset.aggregate(
        total=Count('attendees', filter=attendee_filter, distinct=True)
    )['total'] or 0
    
    # Calculate average by annotating each booking first
    avg_attendees = total_attendees / total_bookings if total_bookings > 0 else 0
    
    # Ticket statistics
    ticket_qs = Ticket.objects.filter(attendee__booking__in=queryset)
    if not include_deleted:
        ticket_qs = ticket_qs.filter(attendee__deleted_at__isnull=True)
    ticket_count = ticket_qs.count()
    
    # Payment status breakdown using GenericForeignKey
    booking_ct = ContentType.objects.get_for_model(Booking)
    booking_ids = list(queryset.values_list('id', flat=True))
    payment_status_counts = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids
    ).values('status').annotate(
        count=Count('payment_id')
    ).order_by('-count')
    
    status_breakdown = [
        {
            'status': item['status'],
            'count': item['count'],
            'percentage': round((item['count'] / total_bookings * 100), 2) if total_bookings > 0 else 0
        }
        for item in payment_status_counts
    ]
    
    return {
        'total_bookings': total_bookings,
        'total_attendees': total_attendees,
        'total_tickets': ticket_count,
        'average_attendees_per_booking': round(avg_attendees, 2),
        'status_breakdown': status_breakdown
    }


def calculate_booking_status_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate booking status distribution based on payment status.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        include_deleted: Whether to include soft-deleted bookings
    
    Returns:
        Dictionary with status distribution data
    """
    queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted)
    total_bookings = queryset.count()
    
    # Get payment status counts using GenericForeignKey
    booking_ct = ContentType.objects.get_for_model(Booking)
    booking_ids = list(queryset.values_list('id', flat=True))
    status_counts = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids
    ).values('status').annotate(
        count=Count('payment_id')
    ).order_by('-count')
    
    distribution = []
    for item in status_counts:
        distribution.append({
            'label': item['status'],
            'value': item['count'],
            'percentage': round((item['count'] / total_bookings * 100), 2) if total_bookings > 0 else 0
        })
    
    # Add bookings without payments
    bookings_with_payment_ids = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids
    ).values_list('target_id', flat=True)
    bookings_without_payment = queryset.exclude(
        id__in=bookings_with_payment_ids
    ).count()
    
    if bookings_without_payment > 0:
        distribution.append({
            'label': 'NO_PAYMENT',
            'value': bookings_without_payment,
            'percentage': round((bookings_without_payment / total_bookings * 100), 2) if total_bookings > 0 else 0
        })
    
    return {
        'total': total_bookings,
        'distribution': distribution
    }


def calculate_booking_trends(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate booking creation trends over time.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        group_by: Grouping method - 'day', 'week', or 'month'
        date_from: Optional start date
        date_to: Optional end date
        include_deleted: Whether to include soft-deleted bookings
    
    Returns:
        Dictionary with trend data
    """
    # Build queryset directly to avoid distinct() interference with grouping
    queryset = Booking.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    if not include_deleted:
        # Only include bookings with at least one non-deleted attendee
        queryset = queryset.filter(attendees__deleted_at__isnull=True).distinct()
    
    if date_from:
        # Convert date to timezone-aware datetime at start of day
        if isinstance(date_from, date) and not isinstance(date_from, datetime):
            date_from = timezone.make_aware(datetime.combine(date_from, time.min))
        queryset = queryset.filter(booked_at__gte=date_from)
    
    if date_to:
        # Include the entire end date - convert to timezone-aware datetime at end of day
        if isinstance(date_to, date) and not isinstance(date_to, datetime):
            date_to = timezone.make_aware(datetime.combine(date_to, time.max))
        queryset = queryset.filter(booked_at__lte=date_to)
    
    # Determine truncation function
    if group_by == 'week':
        trunc_func = TruncWeek('booked_at')
    elif group_by == 'month':
        trunc_func = TruncMonth('booked_at')
    else:
        trunc_func = TruncDate('booked_at')
    
    # Get trends - values() resets the query and groups by period
    trends = queryset.annotate(
        period=trunc_func
    ).values('period').annotate(
        count=Count('id')
    ).order_by('period')
    
    trend_data = [
        {
            'date': item['period'].strftime('%Y-%m-%d'),
            'count': item['count']
        }
        for item in trends
    ]
    
    return {
        'total_bookings': queryset.count(),
        'group_by': group_by,
        'trends': trend_data
    }


def calculate_bookings_by_package(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate booking distribution by booking package.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        include_deleted: Whether to include soft-deleted bookings
        limit: Maximum number of packages to return
    
    Returns:
        Dictionary with package distribution data
    """
    ticket_queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    
    # Count tickets by package
    package_counts = ticket_queryset.filter(
        package__isnull=False
    ).values(
        'package__name',
        'package__id'
    ).annotate(
        count=Count('ticket_id')
    ).order_by('-count')[:limit]
    
    total_tickets_with_package = sum(item['count'] for item in package_counts)
    tickets_without_package = ticket_queryset.filter(package__isnull=True).count()
    
    distribution = []
    for item in package_counts:
        distribution.append({
            'package_name': item['package__name'],
            'package_id': item['package__id'],
            'ticket_count': item['count'],
            'percentage': round((item['count'] / total_tickets_with_package * 100), 2) if total_tickets_with_package > 0 else 0
        })
    
    return {
        'total_tickets_with_package': total_tickets_with_package,
        'total_tickets_without_package': tickets_without_package,
        'distribution': distribution
    }


def calculate_attendees_per_booking(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of attendees per booking.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        include_deleted: Whether to include soft-deleted bookings
    
    Returns:
        Dictionary with attendees per booking distribution
    """
    # Build queryset without the attendee filter that affects distinct()
    queryset = Booking.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    # Annotate with attendee count first
    attendee_filter = Q(attendees__deleted_at__isnull=True) if not include_deleted else Q()
    queryset_with_counts = queryset.annotate(
        attendee_count=Count('attendees', filter=attendee_filter, distinct=True)
    )
    
    # Filter out bookings with 0 attendees (if not including deleted)
    if not include_deleted:
        queryset_with_counts = queryset_with_counts.filter(attendee_count__gt=0)
    
    # Get distribution by counting in Python to avoid queryset complexity
    from collections import Counter
    attendee_counts = [b.attendee_count for b in queryset_with_counts]
    count_distribution = Counter(attendee_counts)
    
    distribution = [
        {
            'attendee_count': count,
            'booking_count': freq
        }
        for count, freq in sorted(count_distribution.items())
    ]
    
    # Calculate statistics
    stats = queryset_with_counts.aggregate(
        avg_attendees=Avg('attendee_count'),
        max_attendees=Max('attendee_count'),
        min_attendees=Min('attendee_count')
    )
    
    return {
        'total_bookings': queryset_with_counts.count(),
        'average_attendees': round(stats['avg_attendees'], 2) if stats['avg_attendees'] else 0,
        'max_attendees': stats['max_attendees'] or 0,
        'min_attendees': stats['min_attendees'] or 0,
        'distribution': distribution
    }


def calculate_booking_completion_rate(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate booking completion rate (intents to completed bookings).
    
    Args:
        event_id: Optional event UUID to filter data
        organization_id: Optional organization ID to filter data
        include_deleted: Whether to include soft-deleted intents
    
    Returns:
        Dictionary with completion rate data
    """
    intent_queryset = _get_base_intent_queryset(event_id, organization_id, include_deleted)
    booking_queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted)
    
    total_intents = intent_queryset.count()
    completed_intents = intent_queryset.filter(status='COMPLETED').count()
    expired_intents = intent_queryset.filter(status='EXPIRED').count()
    cancelled_intents = intent_queryset.filter(status='CANCELLED').count()
    pending_intents = intent_queryset.filter(status='PENDING').count()
    
    total_bookings = booking_queryset.count()
    
    completion_rate = round((completed_intents / total_intents * 100), 2) if total_intents > 0 else 0
    
    return {
        'total_intents': total_intents,
        'completed_intents': completed_intents,
        'expired_intents': expired_intents,
        'cancelled_intents': cancelled_intents,
        'pending_intents': pending_intents,
        'total_bookings': total_bookings,
        'completion_rate': completion_rate
    }


def calculate_booking_reference_types(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of booking reference patterns.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        include_deleted: Whether to include soft-deleted bookings
    
    Returns:
        Dictionary with booking reference distribution
    """
    queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted)
    
    # Extract event codes from booking references (format: BK-{event_code}-{sequence})
    bookings = queryset.values('booking_reference')
    
    reference_patterns = {}
    for booking in bookings:
        ref = booking['booking_reference']
        if ref and ref.startswith('BK-'):
            parts = ref.split('-')
            if len(parts) >= 2:
                event_code = parts[1] if len(parts) > 1 else 'UNKNOWN'
                reference_patterns[event_code] = reference_patterns.get(event_code, 0) + 1
    
    distribution = [
        {
            'event_code': code,
            'count': count
        }
        for code, count in sorted(reference_patterns.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return {
        'total_bookings': queryset.count(),
        'distribution': distribution
    }


def calculate_booking_timeline(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate booking timeline statistics (time from creation to completion).
    
    This is a placeholder for future enhancement as we'd need to track
    when bookings transition between states.
    
    Args:
        event_id: Optional event UUID to filter bookings
        organization_id: Optional organization ID to filter bookings
        include_deleted: Whether to include soft-deleted bookings
    
    Returns:
        Dictionary with timeline data
    """
    queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted)
    
    # For now, just return basic booking date distribution
    bookings_by_date = queryset.annotate(
        booking_date=TruncDate('booked_at')
    ).values('booking_date').annotate(
        count=Count('id')
    ).order_by('booking_date')
    
    timeline = [
        {
            'date': item['booking_date'].strftime('%Y-%m-%d'),
            'count': item['count']
        }
        for item in bookings_by_date
    ]
    
    return {
        'total_bookings': queryset.count(),
        'timeline': timeline
    }


# ============================================================================
# TICKET STATISTICS
# ============================================================================

def calculate_ticket_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate overview statistics for tickets.
    
    Args:
        event_id: Optional event UUID to filter tickets
        organization_id: Optional organization ID to filter tickets
        include_deleted: Whether to include soft-deleted tickets
    
    Returns:
        Dictionary with ticket overview data
    """
    queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    
    total_tickets = queryset.count()
    
    # Status breakdown
    status_counts = queryset.values('status').annotate(
        count=Count('attendee_id')
    ).order_by('-count')
    
    status_breakdown = [
        {
            'status': item['status'],
            'count': item['count'],
            'percentage': round((item['count'] / total_tickets * 100), 2) if total_tickets > 0 else 0
        }
        for item in status_counts
    ]
    
    # Scope breakdown
    scope_counts = queryset.values('ticket_type__scope').annotate(
        count=Count('attendee_id')
    ).order_by('-count')
    
    scope_breakdown = [
        {
            'scope': item['ticket_type__scope'],
            'count': item['count'],
            'percentage': round((item['count'] / total_tickets * 100), 2) if total_tickets > 0 else 0
        }
        for item in scope_counts
    ]
    
    # Usage statistics
    usage_stats = queryset.aggregate(
        avg_uses=Avg('uses'),
        total_uses_remaining=Sum('uses')
    )
    
    return {
        'total_tickets': total_tickets,
        'status_breakdown': status_breakdown,
        'scope_breakdown': scope_breakdown,
        'average_uses_remaining': round(usage_stats['avg_uses'], 2) if usage_stats['avg_uses'] else 0,
        'total_uses_remaining': usage_stats['total_uses_remaining'] or 0
    }


def calculate_ticket_status_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate ticket status distribution.
    
    Args:
        event_id: Optional event UUID to filter tickets
        organization_id: Optional organization ID to filter tickets
        include_deleted: Whether to include soft-deleted tickets
    
    Returns:
        Dictionary with status distribution data
    """
    queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    total_tickets = queryset.count()
    
    status_counts = queryset.values('status').annotate(
        count=Count('attendee_id')
    ).order_by('-count')
    
    distribution = [
        {
            'label': item['status'],
            'value': item['count'],
            'percentage': round((item['count'] / total_tickets * 100), 2) if total_tickets > 0 else 0
        }
        for item in status_counts
    ]
    
    return {
        'total': total_tickets,
        'distribution': distribution
    }


def calculate_ticket_type_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate ticket distribution by ticket type.
    
    Args:
        event_id: Optional event UUID to filter tickets
        organization_id: Optional organization ID to filter tickets
        include_deleted: Whether to include soft-deleted tickets
    
    Returns:
        Dictionary with ticket type distribution
    """
    queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    total_tickets = queryset.count()
    
    type_counts = queryset.values(
        'ticket_type__id',
        'ticket_type__scope'
    ).annotate(
        count=Count('attendee_id')
    ).order_by('-count')
    
    distribution = [
        {
            'ticket_type_id': item['ticket_type__id'],
            'scope': item['ticket_type__scope'],
            'count': item['count'],
            'percentage': round((item['count'] / total_tickets * 100), 2) if total_tickets > 0 else 0
        }
        for item in type_counts
    ]
    
    return {
        'total': total_tickets,
        'distribution': distribution
    }


def calculate_ticket_usage_stats(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate ticket usage statistics.
    
    Args:
        event_id: Optional event UUID to filter tickets
        organization_id: Optional organization ID to filter tickets
        include_deleted: Whether to include soft-deleted tickets
    
    Returns:
        Dictionary with usage statistics
    """
    queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    
    total_tickets = queryset.count()
    
    # Valid tickets (ACTIVE with uses > 0)
    valid_tickets = queryset.filter(status='ACTIVE', uses__gt=0).count()
    
    # Used tickets (status = USED)
    used_tickets = queryset.filter(status='USED').count()
    
    # Cancelled tickets
    cancelled_tickets = queryset.filter(status='CANCELLED').count()
    
    # Usage statistics
    usage_stats = queryset.aggregate(
        avg_uses=Avg('uses'),
        total_uses=Sum('uses'),
        max_uses=Max('uses'),
        min_uses=Min('uses')
    )
    
    return {
        'total_tickets': total_tickets,
        'valid_tickets': valid_tickets,
        'used_tickets': used_tickets,
        'cancelled_tickets': cancelled_tickets,
        'average_uses_remaining': round(usage_stats['avg_uses'], 2) if usage_stats['avg_uses'] else 0,
        'total_uses_remaining': usage_stats['total_uses'] or 0,
        'max_uses': usage_stats['max_uses'] or 0,
        'min_uses': usage_stats['min_uses'] or 0,
        'usage_rate': round((used_tickets / total_tickets * 100), 2) if total_tickets > 0 else 0
    }


def calculate_ticket_scope_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate ticket distribution by scope (FULL_EVENT, SINGLE_DAY, WORKSHOP_ONLY).
    
    Args:
        event_id: Optional event UUID to filter tickets
        organization_id: Optional organization ID to filter tickets
        include_deleted: Whether to include soft-deleted tickets
    
    Returns:
        Dictionary with scope distribution
    """
    queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    total_tickets = queryset.count()
    
    scope_counts = queryset.values('ticket_type__scope').annotate(
        count=Count('attendee_id')
    ).order_by('-count')
    
    distribution = [
        {
            'label': item['ticket_type__scope'],
            'value': item['count'],
            'percentage': round((item['count'] / total_tickets * 100), 2) if total_tickets > 0 else 0
        }
        for item in scope_counts
    ]
    
    return {
        'total': total_tickets,
        'distribution': distribution
    }


# ============================================================================
# PACKAGE STATISTICS
# ============================================================================

def calculate_package_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate overview statistics for booking packages.
    
    Args:
        event_id: Optional event UUID to filter packages
        organization_id: Optional organization ID to filter packages
    
    Returns:
        Dictionary with package overview data
    """
    queryset = BookingPackage.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    total_packages = queryset.count()
    active_packages = queryset.filter(is_active=True).count()
    inactive_packages = total_packages - active_packages
    
    # Usage statistics
    packages_with_tickets = queryset.filter(tickets__isnull=False).distinct().count()
    total_tickets_using_packages = Ticket.objects.filter(
        package__in=queryset
    ).count()
    
    # Rule statistics
    total_rules = BookingPackageRule.objects.filter(
        booking_package__in=queryset
    ).count()
    
    active_rules = BookingPackageRule.objects.filter(
        booking_package__in=queryset,
        active=True
    ).count()
    
    return {
        'total_packages': total_packages,
        'active_packages': active_packages,
        'inactive_packages': inactive_packages,
        'packages_with_tickets': packages_with_tickets,
        'total_tickets_using_packages': total_tickets_using_packages,
        'total_rules': total_rules,
        'active_rules': active_rules
    }


def calculate_package_popularity(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate most popular packages by usage.
    
    Args:
        event_id: Optional event UUID to filter packages
        organization_id: Optional organization ID to filter packages
        include_deleted: Whether to include soft-deleted tickets
        limit: Maximum number of packages to return
    
    Returns:
        Dictionary with package popularity data
    """
    queryset = BookingPackage.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    # Count tickets per package
    packages_annotated = queryset.annotate(
        ticket_count=Count(
            'tickets',
            filter=Q(tickets__attendee__deleted_at__isnull=True) if not include_deleted else Q()
        )
    ).order_by('-ticket_count')
    
    # Filter out packages with no tickets and limit
    package_counts = [p for p in packages_annotated if p.ticket_count > 0][:limit]
    
    popularity = [
        {
            'package_id': package.id,
            'package_name': package.name,
            'ticket_count': package.ticket_count,
            'is_active': package.is_active,
            'base_amount': _money_to_float(package.base_amount)
        }
        for package in package_counts
    ]
    
    return {
        'total_packages': queryset.count(),
        'popularity': popularity
    }


def calculate_package_rule_distribution(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate distribution of package rules by type.
    
    Args:
        event_id: Optional event UUID to filter packages
        organization_id: Optional organization ID to filter packages
    
    Returns:
        Dictionary with rule distribution data
    """
    package_queryset = BookingPackage.objects.all()
    
    if event_id:
        package_queryset = package_queryset.filter(event__event_id=event_id)
    
    if organization_id:
        package_queryset = package_queryset.filter(event__organisation_id=organization_id)
    
    rule_queryset = BookingPackageRule.objects.filter(booking_package__in=package_queryset)
    
    total_rules = rule_queryset.count()
    
    rule_type_counts = rule_queryset.values('rule_type').annotate(
        count=Count('rule_id')
    ).order_by('-count')
    
    distribution = [
        {
            'label': item['rule_type'],
            'value': item['count'],
            'percentage': round((item['count'] / total_rules * 100), 2) if total_rules > 0 else 0
        }
        for item in rule_type_counts
    ]
    
    return {
        'total_rules': total_rules,
        'distribution': distribution
    }


def calculate_package_pricing_analysis(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate pricing analysis for packages.
    
    Args:
        event_id: Optional event UUID to filter packages
        organization_id: Optional organization ID to filter packages
    
    Returns:
        Dictionary with pricing analysis data
    """
    queryset = BookingPackage.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    # Pricing statistics
    pricing_stats = queryset.aggregate(
        avg_base_amount=Avg('base_amount'),
        max_base_amount=Max('base_amount'),
        min_base_amount=Min('base_amount'),
        avg_modifier=Avg('percentage_modifier')
    )
    
    # Get packages with pricing info
    packages_with_pricing = []
    for package in queryset[:20]:  # Limit to 20 for performance
        packages_with_pricing.append({
            'package_id': package.id,
            'package_name': package.name,
            'base_amount': _money_to_float(package.base_amount),
            'percentage_modifier': float(package.percentage_modifier) if package.percentage_modifier else 1.0,
            'is_active': package.is_active
        })
    
    return {
        'total_packages': queryset.count(),
        'average_base_amount': _money_to_float(pricing_stats['avg_base_amount']),
        'max_base_amount': _money_to_float(pricing_stats['max_base_amount']),
        'min_base_amount': _money_to_float(pricing_stats['min_base_amount']),
        'average_modifier': float(pricing_stats['avg_modifier']) if pricing_stats['avg_modifier'] else 1.0,
        'packages': packages_with_pricing
    }


# ============================================================================
# INTENT STATISTICS
# ============================================================================

def calculate_intent_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate overview statistics for booking intents.
    
    Args:
        event_id: Optional event UUID to filter intents
        organization_id: Optional organization ID to filter intents
        include_deleted: Whether to include soft-deleted intents
    
    Returns:
        Dictionary with intent overview data
    """
    queryset = _get_base_intent_queryset(event_id, organization_id, include_deleted)
    
    total_intents = queryset.count()
    
    # Status breakdown
    status_counts = queryset.values('status').annotate(
        count=Count('booking_intent_id')
    ).order_by('-count')
    
    status_breakdown = [
        {
            'status': item['status'],
            'count': item['count'],
            'percentage': round((item['count'] / total_intents * 100), 2) if total_intents > 0 else 0
        }
        for item in status_counts
    ]
    
    # Capacity statistics
    capacity_stats = queryset.aggregate(
        total_reserved=Sum('intended_ticket_count'),
        avg_reserved=Avg('intended_ticket_count')
    )
    
    return {
        'total_intents': total_intents,
        'status_breakdown': status_breakdown,
        'total_capacity_reserved': capacity_stats['total_reserved'] or 0,
        'average_capacity_per_intent': round(capacity_stats['avg_reserved'], 2) if capacity_stats['avg_reserved'] else 0
    }


def calculate_intent_conversion_rate(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate booking intent conversion rates.
    
    Args:
        event_id: Optional event UUID to filter intents
        organization_id: Optional organization ID to filter intents
        include_deleted: Whether to include soft-deleted intents
    
    Returns:
        Dictionary with conversion rate data
    """
    queryset = _get_base_intent_queryset(event_id, organization_id, include_deleted)
    
    total_intents = queryset.count()
    completed = queryset.filter(status='COMPLETED').count()
    expired = queryset.filter(status='EXPIRED').count()
    cancelled = queryset.filter(status='CANCELLED').count()
    pending = queryset.filter(status='PENDING').count()
    
    conversion_rate = round((completed / total_intents * 100), 2) if total_intents > 0 else 0
    expiration_rate = round((expired / total_intents * 100), 2) if total_intents > 0 else 0
    cancellation_rate = round((cancelled / total_intents * 100), 2) if total_intents > 0 else 0
    
    return {
        'total_intents': total_intents,
        'completed': completed,
        'expired': expired,
        'cancelled': cancelled,
        'pending': pending,
        'conversion_rate': conversion_rate,
        'expiration_rate': expiration_rate,
        'cancellation_rate': cancellation_rate
    }


def calculate_intent_trends(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate booking intent creation trends over time.
    
    Args:
        event_id: Optional event UUID to filter intents
        organization_id: Optional organization ID to filter intents
        group_by: Grouping method - 'day', 'week', or 'month'
        date_from: Optional start date
        date_to: Optional end date
        include_deleted: Whether to include soft-deleted intents
    
    Returns:
        Dictionary with trend data
    """
    # Build queryset directly
    queryset = BookingIntent.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    if organization_id:
        queryset = queryset.filter(event__organisation_id=organization_id)
    
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    
    if date_from:
        # Convert date to timezone-aware datetime at start of day
        if isinstance(date_from, date) and not isinstance(date_from, datetime):
            date_from = timezone.make_aware(datetime.combine(date_from, time.min))
        queryset = queryset.filter(created_at__gte=date_from)
    
    if date_to:
        # Include the entire end date - convert to timezone-aware datetime at end of day
        if isinstance(date_to, date) and not isinstance(date_to, datetime):
            date_to = timezone.make_aware(datetime.combine(date_to, time.max))
        queryset = queryset.filter(created_at__lte=date_to)
    
    # Determine truncation function
    if group_by == 'week':
        trunc_func = TruncWeek('created_at')
    elif group_by == 'month':
        trunc_func = TruncMonth('created_at')
    else:
        trunc_func = TruncDate('created_at')
    
    # Get trends
    trends = queryset.annotate(
        period=trunc_func
    ).values('period').annotate(
        count=Count('booking_intent_id')
    ).order_by('period')
    
    trend_data = [
        {
            'date': item['period'].strftime('%Y-%m-%d'),
            'count': item['count']
        }
        for item in trends
    ]
    
    return {
        'total_intents': queryset.count(),
        'group_by': group_by,
        'trends': trend_data
    }


# ============================================================================
# REVENUE STATISTICS
# ============================================================================

def calculate_revenue_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue overview statistics.
    Only COMPLETED payments are counted as confirmed revenue.
    
    Args:
        event_id: Optional event UUID to filter revenue
        organization_id: Optional organization ID to filter revenue
        include_deleted: Whether to include soft-deleted bookings
    
    Returns:
        Dictionary with revenue overview data
    """
    booking_queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted)
    
    # Only count COMPLETED payments using GenericForeignKey
    booking_ct = ContentType.objects.get_for_model(Booking)
    booking_ids = list(booking_queryset.values_list('id', flat=True))
    payment_queryset = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids,
        status=PaymentStatusChoices.COMPLETED
    )
    
    revenue_stats = payment_queryset.aggregate(
        total_revenue=Sum('base_amount'),
        avg_revenue=Avg('base_amount'),
        max_revenue=Max('base_amount'),
        min_revenue=Min('base_amount')
    )
    
    total_bookings = booking_queryset.count()
    total_payments = payment_queryset.count()
    
    return {
        'total_revenue': _money_to_float(revenue_stats['total_revenue']),
        'average_revenue_per_booking': _money_to_float(revenue_stats['avg_revenue']),
        'max_revenue': _money_to_float(revenue_stats['max_revenue']),
        'min_revenue': _money_to_float(revenue_stats['min_revenue']),
        'total_bookings': total_bookings,
        'total_completed_payments': total_payments
    }


def calculate_revenue_by_package(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate revenue breakdown by booking package.
    Only COMPLETED payments are counted.
    
    Args:
        event_id: Optional event UUID to filter revenue
        organization_id: Optional organization ID to filter revenue
        include_deleted: Whether to include soft-deleted data
        limit: Maximum number of packages to return
    
    Returns:
        Dictionary with revenue by package data
    """
    ticket_queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    
    # Get tickets with packages
    tickets_with_packages = ticket_queryset.filter(package__isnull=False)
    
    # Get booking IDs for these tickets
    booking_ids = list(
        tickets_with_packages.values_list('attendee__booking_id', flat=True).distinct()
    )
    
    # Get completed payments for these bookings using GenericForeignKey
    booking_ct = ContentType.objects.get_for_model(Booking)
    completed_payments = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids,
        status=PaymentStatusChoices.COMPLETED
    )
    
    # Calculate revenue by package (approximate distribution)
    package_stats = tickets_with_packages.values(
        'package__id',
        'package__name'
    ).annotate(
        ticket_count=Count('ticket_id')
    ).order_by('-ticket_count')[:limit]
    
    # Map payments to packages proportionally
    total_revenue = sum(_money_to_float(p.base_amount) for p in completed_payments)
    
    distribution = [
        {
            'package_id': item['package__id'],
            'package_name': item['package__name'],
            'ticket_count': item['ticket_count'],
            'revenue': 0  # Approximate - payments are per booking, not per package
        }
        for item in package_stats
    ]
    
    total_revenue = sum(item['revenue'] for item in distribution)
    
    return {
        'total_revenue': total_revenue,
        'distribution': distribution
    }


def calculate_revenue_by_ticket_type(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue breakdown by ticket type.
    Only COMPLETED payments are counted.
    
    Args:
        event_id: Optional event UUID to filter revenue
        organization_id: Optional organization ID to filter revenue
        include_deleted: Whether to include soft-deleted data
    
    Returns:
        Dictionary with revenue by ticket type data
    """
    ticket_queryset = _get_base_ticket_queryset(event_id, organization_id, include_deleted)
    
    # Get booking IDs for these tickets
    booking_ids = list(
        ticket_queryset.values_list('attendee__booking_id', flat=True).distinct()
    )
    
    # Get completed payments for these bookings using GenericForeignKey
    booking_ct = ContentType.objects.get_for_model(Booking)
    completed_payments = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids,
        status=PaymentStatusChoices.COMPLETED
    )
    
    # Get ticket type stats
    type_stats = ticket_queryset.values(
        'ticket_type__id',
        'ticket_type__scope'
    ).annotate(
        ticket_count=Count('payment_id')
    ).order_by('-ticket_count')
    
    # Total revenue for approximate distribution
    total_revenue = sum(_money_to_float(p.base_amount) for p in completed_payments)
    
    distribution = [
        {
            'ticket_type_id': item['ticket_type__id'],
            'scope': item['ticket_type__scope'],
            'ticket_count': item['ticket_count'],
            'revenue': 0  # Approximate - payments are per booking, not per ticket type
        }
        for item in type_stats
    ]
    
    total_revenue = sum(item['revenue'] for item in distribution)
    
    return {
        'total_revenue': total_revenue,
        'distribution': distribution
    }


def calculate_revenue_trends(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue trends over time.
    Only COMPLETED payments are counted.
    
    Args:
        event_id: Optional event UUID to filter revenue
        organization_id: Optional organization ID to filter revenue
        group_by: Grouping method - 'day', 'week', or 'month'
        date_from: Optional start date
        date_to: Optional end date
        include_deleted: Whether to include soft-deleted data
    
    Returns:
        Dictionary with revenue trend data
    """
    booking_queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted, None, date_from, date_to)
    
    # Only COMPLETED payments using GenericForeignKey
    booking_ct = ContentType.objects.get_for_model(Booking)
    booking_ids = list(booking_queryset.values_list('id', flat=True))
    payment_queryset = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids,
        status=PaymentStatusChoices.COMPLETED
    )
    
    if date_from:
        # Convert date to timezone-aware datetime at start of day
        if isinstance(date_from, date) and not isinstance(date_from, datetime):
            date_from = timezone.make_aware(datetime.combine(date_from, time.min))
        payment_queryset = payment_queryset.filter(created_at__gte=date_from)
    
    if date_to:
        # Include the entire end date - convert to timezone-aware datetime at end of day
        if isinstance(date_to, date) and not isinstance(date_to, datetime):
            date_to = timezone.make_aware(datetime.combine(date_to, time.max))
        payment_queryset = payment_queryset.filter(created_at__lte=date_to)
    
    # Determine truncation function
    if group_by == 'week':
        trunc_func = TruncWeek('created_at')
    elif group_by == 'month':
        trunc_func = TruncMonth('created_at')
    else:
        trunc_func = TruncDate('created_at')
    
    # Get trends
    trends = payment_queryset.annotate(
        period=trunc_func
    ).values('period').annotate(
        revenue=Sum('base_amount'),
        payment_count=Count('payment_id')
    ).order_by('period')
    
    trend_data = [
        {
            'date': item['period'].strftime('%Y-%m-%d'),
            'revenue': _money_to_float(item['revenue']),
            'payment_count': item['payment_count']
        }
        for item in trends
    ]
    
    return {
        'total_revenue': sum(item['revenue'] for item in trend_data),
        'group_by': group_by,
        'trends': trend_data
    }


def calculate_revenue_breakdown(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue breakdown by payment status.
    
    Args:
        event_id: Optional event UUID to filter revenue
        organization_id: Optional organization ID to filter revenue
        include_deleted: Whether to include soft-deleted data
    
    Returns:
        Dictionary with revenue breakdown by status
    """
    booking_queryset = _get_base_booking_queryset(event_id, organization_id, include_deleted)
    
    # Get all payments (not just COMPLETED) using GenericForeignKey
    booking_ct = ContentType.objects.get_for_model(Booking)
    booking_ids = list(booking_queryset.values_list('id', flat=True))
    payment_queryset = Payment.objects.filter(
        target_type=booking_ct,
        target_id__in=booking_ids
    )
    
    status_revenue = payment_queryset.values('status').annotate(
        total_revenue=Sum('base_amount'),
        payment_count=Count('payment_id')
    ).order_by('-total_revenue')
    
    distribution = [
        {
            'status': item['status'],
            'revenue': _money_to_float(item['total_revenue']),
            'payment_count': item['payment_count']
        }
        for item in status_revenue
    ]
    
    total_revenue = sum(item['revenue'] for item in distribution)
    completed_revenue = sum(
        item['revenue'] for item in distribution 
        if item['status'] == PaymentStatusChoices.COMPLETED
    )
    
    return {
        'total_revenue_all_statuses': total_revenue,
        'completed_revenue': completed_revenue,
        'distribution': distribution
    }


# ============================================================================
# COMBINED OVERVIEW
# ============================================================================

def calculate_booking_statistics_overview(
    event_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate combined overview statistics for dashboard display.
    
    Args:
        event_id: Optional event UUID to filter data
        organization_id: Optional organization ID to filter data
        include_deleted: Whether to include soft-deleted data
    
    Returns:
        Dictionary with combined overview statistics
    """
    booking_overview = calculate_booking_overview(event_id, organization_id, include_deleted)
    ticket_overview = calculate_ticket_overview(event_id, organization_id, include_deleted)
    package_overview = calculate_package_overview(event_id, organization_id)
    intent_overview = calculate_intent_overview(event_id, organization_id, include_deleted)
    revenue_overview = calculate_revenue_overview(event_id, organization_id, include_deleted)
    
    return {
        'bookings': {
            'total': booking_overview['total_bookings'],
            'total_attendees': booking_overview['total_attendees'],
            'average_attendees_per_booking': booking_overview['average_attendees_per_booking']
        },
        'tickets': {
            'total': ticket_overview['total_tickets'],
            'status_breakdown': ticket_overview['status_breakdown']
        },
        'packages': {
            'total': package_overview['total_packages'],
            'active': package_overview['active_packages'],
            'total_usage': package_overview['total_tickets_using_packages']
        },
        'intents': {
            'total': intent_overview['total_intents'],
            'status_breakdown': intent_overview['status_breakdown']
        },
        'revenue': {
            'total': revenue_overview['total_revenue'],
            'average_per_booking': revenue_overview['average_revenue_per_booking'],
            'total_completed_payments': revenue_overview['total_completed_payments']
        }
    }
