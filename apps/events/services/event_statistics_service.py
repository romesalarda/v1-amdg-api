"""
Event Statistics Calculation Module

This module provides calculation functions for event-related statistics.
Each function returns structured data suitable for both raw JSON and ECharts formatting.

Functions are designed to be:
- Event-scoped or global (via optional filters)
- Efficient (using Django ORM aggregations)
- Extensible (easy to add new statistics)
- Testable (pure functions with clear inputs/outputs)

Priority Focus:
- Basic Information (status, types, overview)
- Financial (revenue, payments, bookings)
- Capacity & Registration
- Reviews & Staff
"""
from django.db.models import (
    Count, Sum, Avg, Q, F, Value, DecimalField, 
    Case, When, IntegerField, FloatField
)
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncHour, Coalesce
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import date, timedelta
from typing import Optional, Dict, List, Any
from decimal import Decimal

from apps.events.models import Event, EventType, EventStaff, EventReview, EventStatusChoices
from apps.bookings.models import Booking, BookingPackage
from apps.attendee.models import Attendee
from apps.products.models import Product
from apps.payments.models import Payment, PaymentStatusChoices
from apps.organisations.models import EventSponsor, EventSponsorPackage
import uuid

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _is_valid_uuid(value):
    """Check if the provided value is a valid UUID."""
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False

def _get_base_queryset(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    status: Optional[str] = None,
    include_deleted: bool = False
):
    """
    Get base event queryset with common filters applied.
    
    Args:
        event_id: Optional event URL-safe title to filter to specific event
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
        status: Optional event status filter
        include_deleted: Whether to include soft-deleted events
    
    Returns:
        Filtered queryset of events
    """
    queryset = Event.objects.all()
    
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    
    if event_id:
        if _is_valid_uuid(event_id):
            queryset = queryset.filter(event_id=event_id)
        else:
            queryset = queryset.filter(url_safe_title=event_id)
    
    if event_type_id:
        queryset = queryset.filter(event_type_id=event_type_id)
    
    if organization_id:
        queryset = queryset.filter(organisation_id=organization_id)
    
    if status:
        queryset = queryset.filter(status=status)
    
    return queryset


# ============================================================================
# BASIC INFORMATION STATISTICS (PRIORITY 1)
# ============================================================================

def calculate_status_distribution(
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of events by status.
    
    Args:
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
        include_deleted: Whether to include soft-deleted events
    
    Returns:
        Dictionary with status distribution data
    """
    queryset = _get_base_queryset(
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=include_deleted
    )
    
    total_count = queryset.count()
    
    # Get status counts
    status_counts = queryset.values('status').annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in status_counts:
        status = item['status']
        count = item['count']
        # Get display name from choices
        label = dict(EventStatusChoices.choices).get(status, status)
        
        distribution.append({
            'label': label,
            'value': count,
            'code': status,
            'percentage': round((count / total_count * 100), 2) if total_count > 0 else 0
        })
    
    # Calculate active events (open + in_progress)
    active_count = queryset.filter(
        status__in=[EventStatusChoices.OPEN, EventStatusChoices.IN_PROGRESS]
    ).count()
    
    return {
        'total_events': total_count,
        'active_count': active_count,
        'distribution': distribution
    }


def calculate_type_distribution(
    organization_id: Optional[int] = None,
    status: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of events by type.
    
    Args:
        organization_id: Optional organization ID
        status: Optional event status filter
        include_deleted: Whether to include soft-deleted events
    
    Returns:
        Dictionary with type distribution data
    """
    queryset = _get_base_queryset(
        organization_id=organization_id,
        status=status,
        include_deleted=include_deleted
    )
    
    total_count = queryset.count()
    
    # Get type counts
    type_counts = queryset.filter(
        event_type__isnull=False
    ).values(
        'event_type__title',
        'event_type__code',
        'event_type_id'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in type_counts:
        count = item['count']
        distribution.append({
            'label': item['event_type__title'],
            'code': item['event_type__code'],
            'type_id': item['event_type_id'],
            'value': count,
            'percentage': round((count / total_count * 100), 2) if total_count > 0 else 0
        })
    
    # Count events without type
    without_type = queryset.filter(event_type__isnull=True).count()
    
    return {
        'total_events': total_count,
        'total_with_type': total_count - without_type,
        'total_without_type': without_type,
        'distribution': distribution
    }


def calculate_organization_distribution(
    event_type_id: Optional[int] = None,
    status: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate distribution of events by organization.
    
    Args:
        event_type_id: Optional event type ID
        status: Optional event status filter
        include_deleted: Whether to include soft-deleted events
        limit: Maximum number of organizations to return
    
    Returns:
        Dictionary with organization distribution data
    """
    queryset = _get_base_queryset(
        event_type_id=event_type_id,
        status=status,
        include_deleted=include_deleted
    )
    
    total_count = queryset.count()
    
    # Get organization counts
    org_counts = queryset.filter(
        organisation__isnull=False
    ).values(
        'organisation__title',
        'organisation_id'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in org_counts:
        count = item['count']
        distribution.append({
            'label': item['organisation__title'],
            'organization_id': item['organisation_id'],
            'value': count,
            'percentage': round((count / total_count * 100), 2) if total_count > 0 else 0
        })
    
    without_org = queryset.filter(organisation__isnull=True).count()
    
    return {
        'total_events': total_count,
        'total_with_organization': total_count - without_org,
        'total_without_organization': without_org,
        'distribution': distribution[:limit]
    }


def calculate_upcoming_events(
    days_ahead: int = 30,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calculate upcoming events within specified days.
    
    Args:
        days_ahead: Number of days to look ahead
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
    
    Returns:
        Dictionary with upcoming events data
    """
    queryset = _get_base_queryset(
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    # Filter to upcoming events
    now = timezone.now()
    future_date = now + timedelta(days=days_ahead)
    
    upcoming = queryset.filter(
        start_datetime__gte=now,
        start_datetime__lte=future_date
    ).order_by('start_datetime')
    
    events_list = []
    for event in upcoming[:20]:  # Limit to 20 for performance
        events_list.append({
            'event_id': str(event.event_id),
            'title': event.title,
            'start_datetime': event.start_datetime.isoformat(),
            'status': event.status,
            'event_type': event.event_type.title if event.event_type else None,
            'expected_attendance': event.expected_attendance,
        })
    
    return {
        'days_ahead': days_ahead,
        'total_upcoming': upcoming.count(),
        'date_range': {
            'start': now.date().isoformat(),
            'end': future_date.date().isoformat()
        },
        'events': events_list
    }


# ============================================================================
# FINANCIAL STATISTICS (PRIORITY 1)
# ============================================================================

def calculate_revenue_overview(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None
) -> Dict[str, Any]:
    """
    Calculate comprehensive revenue overview.
    
    Args:
        event_id: Optional event UUID
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
    
    Returns:
        Dictionary with revenue data from all sources
    """
    event_queryset = _get_base_queryset(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    # Apply date filtering
    if date_from:
        event_queryset = event_queryset.filter(start_datetime__date__gte=date_from)
    if date_to:
        event_queryset = event_queryset.filter(start_datetime__date__lte=date_to)
    
    event_ids = list(event_queryset.values_list('id', flat=True))

    sponsor_stats = calculate_sponsorship_package_performance(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        limit=100,
    )
    
    # All revenue from completed payments (covers bookings, products, etc.)
    total_payment_revenue = Payment.objects.filter(
        event_id__in=event_ids,
        status=PaymentStatusChoices.COMPLETED
    ).aggregate(
        total=Coalesce(Sum('base_amount'), Decimal('0.00'))
    )['total']
    
    # For now, we'll treat all payment revenue as booking revenue
    # since Payment doesn't distinguish between booking/product payments explicitly
    booking_revenue = total_payment_revenue
    product_revenue = Decimal('0.00')
    
    # Donations revenue (linked through payment FK)
    from apps.payments.models import Donation
    donation_revenue = Donation.objects.filter(
        payment__event_id__in=event_ids,
        verification_status='verified'
    ).aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']
    
    sponsor_revenue = Decimal(str(sponsor_stats.get('total_completed_revenue', 0.0)))
    total_revenue = booking_revenue + product_revenue + donation_revenue + sponsor_revenue
    
    breakdown_list = [
        {'source': 'Bookings', 'value': float(booking_revenue)},
        {'source': 'Products', 'value': float(product_revenue)},
        {'source': 'Donations', 'value': float(donation_revenue)},
        {'source': 'Sponsorships', 'value': float(sponsor_revenue)},
    ]
    
    return {
        'total_revenue': float(total_revenue),
        'booking_revenue': float(booking_revenue),
        'product_revenue': float(product_revenue),
        'donation_revenue': float(donation_revenue),
        'sponsor_revenue': float(sponsor_revenue),
        'breakdown': breakdown_list,
        'revenue_breakdown': breakdown_list,  # Alias for backwards compatibility
        'event_count': len(event_ids)
    }


def calculate_sponsorship_package_performance(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Calculate sponsorship package utilization, status and revenue metrics."""
    event_queryset = _get_base_queryset(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False,
    )
    event_ids = list(event_queryset.values_list('id', flat=True))

    package_qs = EventSponsorPackage.objects.filter(event_id__in=event_ids).select_related('event')
    payment_ct = ContentType.objects.get_for_model(EventSponsorPackage)

    packages = []
    total_completed_revenue = Decimal('0.00')
    total_refunded = Decimal('0.00')

    for pkg in package_qs.order_by('tier', 'package_name')[:limit]:
        status_counts = pkg.sponsors.values('verification_status').annotate(count=Count('id'))
        counts = {item['verification_status']: item['count'] for item in status_counts}

        payment_qs = Payment.objects.filter(target_type=payment_ct, target_id=pkg.id)
        completed_amount = payment_qs.filter(status=PaymentStatusChoices.COMPLETED).aggregate(
            total=Coalesce(Sum('base_amount'), Decimal('0.00'))
        )['total']
        refunded_amount = payment_qs.filter(status=PaymentStatusChoices.REFUNDED).aggregate(
            total=Coalesce(Sum('base_amount'), Decimal('0.00'))
        )['total']

        total_completed_revenue += completed_amount
        total_refunded += refunded_amount

        packages.append({
            'package_id': str(pkg.package_id),
            'package_name': pkg.package_name,
            'event_id': str(pkg.event.event_id),
            'event_title': pkg.event.title,
            'tier': pkg.tier,
            'active': pkg.active,
            'sponsors_count': pkg.sponsors.count(),
            'status_counts': {
                'pending': counts.get('pending', 0),
                'verified': counts.get('verified', 0),
                'rejected': counts.get('rejected', 0),
                'processed': counts.get('processed', 0),
            },
            'completed_revenue': float(completed_amount),
            'refunded_revenue': float(refunded_amount),
            'net_revenue': float(completed_amount - refunded_amount),
        })

    total_sponsors = EventSponsor.objects.filter(event_id__in=event_ids).count()
    status_totals = EventSponsor.objects.filter(event_id__in=event_ids).values('verification_status').annotate(count=Count('id'))
    status_summary = {item['verification_status']: item['count'] for item in status_totals}

    return {
        'packages': packages,
        'total_packages': package_qs.count(),
        'total_sponsors': total_sponsors,
        'status_summary': {
            'pending': status_summary.get('pending', 0),
            'verified': status_summary.get('verified', 0),
            'rejected': status_summary.get('rejected', 0),
            'processed': status_summary.get('processed', 0),
        },
        'total_completed_revenue': float(total_completed_revenue),
        'total_refunded_revenue': float(total_refunded),
        'total_net_revenue': float(total_completed_revenue - total_refunded),
    }


def calculate_revenue_by_event(
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 20,
    sort_by: str = 'revenue'
) -> Dict[str, Any]:
    """
    Calculate revenue breakdown by individual events.
    
    Args:
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
        date_from: Start date for filtering
        date_to: End date for filtering
        limit: Maximum number of events to return
    
    Returns:
        Dictionary with per-event revenue data
    """
    event_queryset = _get_base_queryset(
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    if date_from:
        event_queryset = event_queryset.filter(start_datetime__date__gte=date_from)
    if date_to:
        event_queryset = event_queryset.filter(start_datetime__date__lte=date_to)
    
    events_data = []
    
    for event in event_queryset[:limit]:
        # All revenue from completed payments
        payment_rev = Payment.objects.filter(
            event=event,
            status=PaymentStatusChoices.COMPLETED
        ).aggregate(
            total=Coalesce(Sum('base_amount'), Decimal('0.00'))
        )['total']
        
        # For now, treat all payment revenue as booking revenue
        booking_rev = payment_rev
        product_rev = Decimal('0.00')
        
        # Donations
        from apps.payments.models import Donation
        donation_rev = Donation.objects.filter(
            payment__event=event,
            verification_status='verified'
        ).aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00'))
        )['total']
        
        total = booking_rev + product_rev + donation_rev
        
        events_data.append({
            'event_id': str(event.event_id),
            'title': event.title,
            'total_revenue': float(total),
            'booking_revenue': float(booking_rev),
            'product_revenue': float(product_rev),
            'donation_revenue': float(donation_rev),
            'status': event.status,
            'start_date': event.start_datetime.date().isoformat()
        })
    
    # Sort by total revenue descending
    events_data.sort(key=lambda x: x['total_revenue'], reverse=True)
    
    return {
        'events': events_data,
        'total_events': event_queryset.count()
    }


def calculate_payment_status_distribution(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calculate distribution of payment statuses for event bookings.
    
    Args:
        event_id: Optional event UUID
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
    
    Returns:
        Dictionary with payment status distribution
    """
    event_queryset = _get_base_queryset(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    event_ids = list(event_queryset.values_list('id', flat=True))
    
    # Get payment status from Payment model (linked to events)
    payment_stats = Payment.objects.filter(
        event_id__in=event_ids,
        target_id__isnull=False
    ).values('status').annotate(
        count=Count('id'),
        amount=Coalesce(Sum('base_amount'), Decimal('0.00'))
    )
    
    distribution = []
    total_amount = Decimal('0.00')
    total_count = 0
    
    for item in payment_stats:
        amount = item['amount']
        count = item['count']
        total_amount += amount
        total_count += count
        
        # Get human-readable label
        status_label = dict(PaymentStatusChoices.choices).get(item['status'], item['status'])
        
        distribution.append({
            'label': status_label,
            'count': count,
            'amount': float(amount)
        })
    
    # Count total bookings (not just those with payments)
    total_bookings = Booking.objects.filter(event_id__in=event_ids).count()
    
    return {
        'total_bookings': total_bookings,
        'total_payments': total_count,
        'total_amount': float(total_amount),
        'distribution': distribution
    }


# ============================================================================
# CAPACITY & REGISTRATION STATISTICS
# ============================================================================

def calculate_capacity_utilization(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate capacity utilization across events.
    
    Args:
        event_id: Optional event UUID
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
        status: Optional event status filter
    
    Returns:
        Dictionary with capacity utilization data
    """
    queryset = _get_base_queryset(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        status=status,
        include_deleted=False
    )
    
    # Filter events with capacity limits
    events_with_capacity = queryset.filter(
        maximum_attendance__isnull=False,
        maximum_attendance__gt=0
    )
    
    utilization_data = []
    total_capacity = 0
    total_registered = 0
    
    for event in events_with_capacity:
        # Count attendees
        from apps.attendee.models import Attendee
        registered = Attendee.objects.filter(
            event=event,
            deleted_at__isnull=True
        ).count()
        
        capacity = event.maximum_attendance or 0
        utilization = (registered / capacity * 100) if capacity > 0 else 0
        
        total_capacity += capacity
        total_registered += registered
        
        utilization_data.append({
            'event_id': str(event.event_id),
            'title': event.title,
            'maximum_attendance': capacity,
            'registered_count': registered,
            'available': capacity - registered,
            'utilization_percentage': round(utilization, 2)
        })
    
    # Sort by utilization descending
    utilization_data.sort(key=lambda x: x['utilization_percentage'], reverse=True)
    
    overall_utilization = (total_registered / total_capacity * 100) if total_capacity > 0 else 0
    
    return {
        'overall_utilization': round(overall_utilization, 2),
        'average_utilization': round(overall_utilization, 2),  # Same as overall for now
        'total_capacity': total_capacity,
        'total_registered': total_registered,
        'total_available': total_capacity - total_registered,
        'events': utilization_data[:20]  # Top 20 events
    }


def calculate_registration_trends(
    event_id: str,
    period: str = 'day',
    cumulative: bool = False
) -> Dict[str, Any]:
    """
    Calculate registration trends for a specific event over time.
    
    Args:
        event_id: Event UUID (required)
        period: 'hour', 'day', 'week', or 'month'
        cumulative: Whether to include cumulative counts
    
    Returns:
        Dictionary with registration trend data
    """
    if not event_id:
        return {
            'event_id': None,
            'event_title': None,
            'total_registrations': 0,
            'period': period,
            'trends': [],
            'error': 'Event ID is required'
        }
    
    try:
        event = Event.objects.get(event_id=event_id, deleted_at__isnull=True)
    except Event.DoesNotExist:
        return {
            'event_id': event_id,
            'event_title': None,
            'total_registrations': 0,
            'period': period,
            'trends': [],
            'error': 'Event not found'
        }
    
    from apps.attendee.models import Attendee
    
    attendees = Attendee.objects.filter(
        event=event,
        deleted_at__isnull=True
    )
    
    # Group by time period
    if period == 'hour':
        trunc_func = TruncHour
    elif period == 'week':
        trunc_func = TruncWeek
    elif period == 'month':
        trunc_func = TruncMonth
    else:  # day
        trunc_func = TruncDate
    
    trends = attendees.annotate(
        period_date=trunc_func('created_at')
    ).values('period_date').annotate(
        count=Count('id')
    ).order_by('period_date')
    
    # Calculate cumulative
    cumulative = 0
    trend_data = []
    for item in trends:
        cumulative += item['count']
        trend_data.append({
            'date': item['period_date'].isoformat(),
            'count': item['count'],
            'cumulative': cumulative
        })
    
    return {
        'event_id': event_id,
        'event_title': event.title,
        'total_registrations': attendees.count(),
        'period': period,
        'trends': trend_data
    }


# ============================================================================
# REVIEW & RATING STATISTICS
# ============================================================================

def calculate_review_statistics(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate review and rating statistics.
    
    Args:
        event_id: Optional event UUID
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
    
    Returns:
        Dictionary with review statistics
    """
    event_queryset = _get_base_queryset(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    event_ids = list(event_queryset.values_list('id', flat=True))
    
    reviews = EventReview.objects.filter(event_id__in=event_ids)
    
    total_reviews = reviews.count()
    approved_reviews = reviews.filter(approved=True).count()
    
    # Rating distribution
    rating_dist = reviews.values('rating').annotate(
        count=Count('id')
    ).order_by('rating')
    
    distribution = []
    for item in rating_dist:
        distribution.append({
            'rating': item['rating'],
            'count': item['count'],
            'percentage': round((item['count'] / total_reviews * 100), 2) if total_reviews > 0 else 0
        })
    
    # Average rating
    avg_rating = reviews.aggregate(
        avg=Avg('rating')
    )['avg']
    
    # Top rated events
    top_events = Event.objects.filter(
        id__in=event_ids
    ).annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews')
    ).filter(
        review_count__gt=0
    ).order_by('-avg_rating')[:10]
    
    top_rated = []
    for event in top_events:
        top_rated.append({
            'event_id': str(event.event_id),
            'title': event.title,
            'average_rating': round(event.avg_rating, 2) if event.avg_rating else 0,
            'review_count': event.review_count
        })
    
    return {
        'total_reviews': total_reviews,
        'approved_reviews': approved_reviews,
        'pending_reviews': total_reviews - approved_reviews,
        'approval_status': {
            'approved': approved_reviews,
            'pending': total_reviews - approved_reviews
        },
        'average_rating': round(avg_rating, 2) if avg_rating else None,
        'rating_distribution': distribution,
        'top_rated_events': top_rated
    }


# ============================================================================
# STAFF STATISTICS
# ============================================================================

def calculate_staff_allocation(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate staff allocation statistics.
    
    Args:
        event_id: Optional event UUID
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
    
    Returns:
        Dictionary with staff allocation data
    """
    event_queryset = _get_base_queryset(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    event_ids = list(event_queryset.values_list('id', flat=True))
    
    # Staff per event
    staff_per_event = EventStaff.objects.filter(
        event_id__in=event_ids
    ).values('event__title', 'event__event_id').annotate(
        count=Count('staff_id')
    ).order_by('-count')
    
    events_data = []
    for item in staff_per_event:
        events_data.append({
            'event_id': str(item['event__event_id']),
            'event_title': item['event__title'],
            'staff_count': item['count']
        })
    
    # Most active staff members
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    active_staff = EventStaff.objects.filter(
        event_id__in=event_ids,
        user__isnull=False
    ).values(
        'user__first_name',
        'user__last_name',
        'user_id'
    ).annotate(
        event_count=Count('event', distinct=True)
    ).order_by('-event_count')[:10]
    
    staff_list = []
    for item in active_staff:
        staff_list.append({
            'name': f"{item['user__first_name']} {item['user__last_name']}",
            'event_count': item['event_count']
        })
    
    total_staff = EventStaff.objects.filter(
        event_id__in=event_ids
    ).values('user_id').distinct().count()
    
    total_assignments = EventStaff.objects.filter(event_id__in=event_ids).count()
    event_count = len(event_ids)
    average_per_event = total_assignments / event_count if event_count > 0 else 0.0
    
    return {
        'events': events_data[:limit],
        'total_staff_assignments': total_assignments,
        'average_staff_per_event': round(average_per_event, 2),
        'most_active_staff': staff_list,
        'total_unique_staff': total_staff
    }


# ============================================================================
# BOOKING PACKAGE STATISTICS
# ============================================================================

def calculate_booking_package_performance(
    event_id: Optional[str] = None,
    event_type_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Calculate booking package performance statistics.
    
    Args:
        event_id: Optional event UUID
        event_type_id: Optional event type ID
        organization_id: Optional organization ID
    
    Returns:
        Dictionary with booking package data
    """
    event_queryset = _get_base_queryset(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    event_ids = list(event_queryset.values_list('id', flat=True))
    
    # Package usage - count unique bookings that have tickets with each package
    package_stats = BookingPackage.objects.filter(
        event_id__in=event_ids
    ).annotate(
        booking_count=Count('tickets__attendee__booking', distinct=True)
    ).values(
        'id',
        'name',
        'event__title',
        'base_amount',
        'booking_count'
    ).order_by('-booking_count')
    
    packages_data = []
    
    for item in package_stats:
        # Calculate revenue from payments linked to tickets that use this package
        revenue = Payment.objects.filter(
            tickets__package_id=item['id'],
            status=PaymentStatusChoices.COMPLETED
        ).aggregate(
            total=Coalesce(Sum('base_amount'), Decimal('0.00'))
        )['total']
        
        packages_data.append({
            'package_id': item['id'],
            'package_name': item['name'],
            'event_title': item['event__title'],
            'bookings': item['booking_count'],
            'revenue': float(revenue)
        })
    
    # Calculate totals across all packages
    total_bookings = sum(p['bookings'] for p in packages_data)
    total_revenue = sum(p['revenue'] for p in packages_data)
    
    return {
        'total_packages': BookingPackage.objects.filter(event_id__in=event_ids).count(),
        'total_bookings': total_bookings,
        'total_revenue': float(total_revenue),
        'packages': packages_data[:limit]
    }


# ============================================================================
# COMBINED OVERVIEW
# ============================================================================

def calculate_overview_statistics(
    event_type_id: Optional[int] = None,
    event_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None
) -> Dict[str, Any]:
    """
    Calculate combined overview statistics for dashboard.
    
    Args:
        event_type_id: Optional event type ID
        event_id: Optional event ID
        organization_id: Optional organization ID
    
    Returns:
        Dictionary with overview statistics
    """
    queryset = _get_base_queryset(
        event_type_id=event_type_id,
        event_id=event_id,
        organization_id=organization_id,
        include_deleted=False
    )
    
    # Apply additional filters
    if status:
        queryset = queryset.filter(status=status)
    if date_from:
        queryset = queryset.filter(start_datetime__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(start_datetime__date__lte=date_to)
    
    total_events = queryset.count()
    
    # Status summary
    status_summary = {
        'drafting': queryset.filter(status=EventStatusChoices.DRAFTING).count(),
        'published': queryset.filter(status=EventStatusChoices.PUBLISHED).count(),
        'open': queryset.filter(status=EventStatusChoices.OPEN).count(),
        'in_progress': queryset.filter(status=EventStatusChoices.IN_PROGRESS).count(),
        'completed': queryset.filter(status=EventStatusChoices.COMPLETED).count(),
    }
    
    # Quick revenue from completed payments
    event_ids = list(queryset.values_list('id', flat=True))
    total_revenue = Payment.objects.filter(
        event_id__in=event_ids,
        status=PaymentStatusChoices.COMPLETED
    ).aggregate(
        total=Coalesce(Sum('base_amount'), Decimal('0.00'))
    )['total']
    
    # Upcoming events
    now = timezone.now()
    upcoming_30_days = queryset.filter(
        start_datetime__gte=now,
        start_datetime__lte=now + timedelta(days=30)
    ).count()
    
    # Count bookings and attendees
    total_bookings = Booking.objects.filter(event_id__in=event_ids).count()
    total_attendees = Attendee.objects.filter(event_id__in=event_ids).count()
    
    # Calculate average capacity utilization
    events_with_capacity = queryset.exclude(maximum_attendance__isnull=True)
    if events_with_capacity.exists():
        utilizations = []
        for event in events_with_capacity:
            if event.maximum_attendance and event.maximum_attendance > 0:
                attendees_count = event.attendees.count()
                utilization = (attendees_count / event.maximum_attendance) * 100
                utilizations.append(utilization)
        average_capacity_utilization = sum(utilizations) / len(utilizations) if utilizations else 0.0
    else:
        average_capacity_utilization = 0.0
    
    # Get review statistics
    from apps.events.models import EventReview
    reviews = EventReview.objects.filter(event_id__in=event_ids, approved=True)
    total_reviews = reviews.count()
    if total_reviews > 0:
        from django.db.models import Avg
        average_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0.0
    else:
        average_rating = 0.0

    sponsor_stats = calculate_sponsorship_package_performance(
        event_id=event_id,
        event_type_id=event_type_id,
        organization_id=organization_id,
        limit=10,
    )
    
    return {
        'total_events': total_events,
        'active_events': status_summary['open'] + status_summary['in_progress'],
        'upcoming_events': upcoming_30_days,
        'completed_events': status_summary['completed'],
        'total_revenue': float(total_revenue),
        'total_bookings': total_bookings,
        'total_attendees': total_attendees,
        'average_capacity_utilization': float(average_capacity_utilization),
        'average_rating': float(average_rating),
        'total_reviews': total_reviews,
        'sponsorship': {
            'total_packages': sponsor_stats.get('total_packages', 0),
            'total_sponsors': sponsor_stats.get('total_sponsors', 0),
            'status_summary': sponsor_stats.get('status_summary', {}),
            'total_completed_revenue': sponsor_stats.get('total_completed_revenue', 0.0),
            'total_refunded_revenue': sponsor_stats.get('total_refunded_revenue', 0.0),
            'total_net_revenue': sponsor_stats.get('total_net_revenue', 0.0),
            'packages': sponsor_stats.get('packages', []),
        },
        'status_summary': status_summary,
        'upcoming_30_days': upcoming_30_days,
        'generated_at': timezone.now().isoformat()
    }
