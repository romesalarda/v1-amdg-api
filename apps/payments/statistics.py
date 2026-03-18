"""
Payment Statistics Calculation Module

This module provides calculation functions for payment-related statistics.
Each function returns structured data suitable for both raw JSON and ECharts formatting.

Functions are designed to be:
- Event-scoped or global (via optional event_id parameter)
- Efficient (using Django ORM aggregations)
- Extensible (easy to add new statistics)
- Testable (pure functions with clear inputs/outputs)

NOTE: Payment model does NOT support soft-delete. Only Order model has soft-delete support.
The include_deleted parameter only affects Order-related statistics.
"""
from django.db.models import Count, Q, Avg, Sum, F, Value, CharField, Case, When, DecimalField
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncHour, Coalesce
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import date, timedelta
from typing import Optional, Dict, List, Any
from decimal import Decimal

from apps.payments.models.payments import Payment, PaymentStatusChoices
from apps.payments.models.methods import PaymentMethod
from apps.payments.models.discounts import Discount, DiscountRule
from apps.payments.models.refunds import RefundRequest
from apps.payments.models.donations import Donation
from apps.products.models.orders import Order
from apps.organisations.models import EventSponsorPackage


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_base_queryset(event_id: Optional[str] = None, include_deleted: bool = False):
    """
    Get base payment queryset with common filters applied.
    
    NOTE: Payment model does NOT support soft-delete, so include_deleted has no effect here.
    
    Args:
        event_id: Optional event UUID to filter payments
        include_deleted: IGNORED - Payment model does not support soft-delete
    
    Returns:
        Filtered queryset of payments
    """
    queryset = Payment.objects.all()
    
    if event_id:
        queryset = queryset.filter(event__event_id=event_id)
    
    return queryset


def _get_orders_base_queryset(event_id: Optional[str] = None, include_deleted: bool = False):
    """
    Get base order queryset with common filters applied.
    
    NOTE: Order model DOES support soft-delete via SoftDeleteModel.
    
    Args:
        event_id: Optional event UUID to filter orders
        include_deleted: Whether to include soft-deleted orders
    
    Returns:
        Filtered queryset of orders
    """
    if include_deleted:
        queryset = Order.all_objects.all()
    else:
        queryset = Order.objects.all()
    
    if event_id:
        # Orders link to events through attendee
        queryset = queryset.filter(attendee__event__event_id=event_id)
    
    return queryset


def _format_money_value(money_obj) -> Optional[float]:
    """
    Convert Money object to float for JSON serialization.
    
    Args:
        money_obj: djmoney Money object or None
    
    Returns:
        Float value or None
    """
    if money_obj is None:
        return None
    # Money objects have .amount attribute which is a Decimal
    return float(money_obj.amount) if hasattr(money_obj, 'amount') else float(money_obj)


def _calculate_percentage(part: int, total: int) -> float:
    """Calculate percentage with division by zero protection."""
    return round((part / total * 100), 2) if total > 0 else 0.0


# ============================================================================
# PAYMENT STATISTICS
# ============================================================================

def calculate_payment_status_distribution(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of payment statuses.
    
    Args:
        event_id: Optional event UUID to filter payments
        include_deleted: IGNORED - Payment model does not support soft-delete
    
    Returns:
        Dictionary with status distribution data:
        {
            'total': int,
            'distribution': [{'label': str, 'value': int, 'percentage': float}, ...],
        }
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    total_count = queryset.count()
    
    # Get status counts
    status_counts = queryset.values('status').annotate(
        count=Count('id')
    ).order_by('-count')
    
    distribution = []
    for item in status_counts:
        status = item['status']
        count = item['count']
        # Get human-readable label from choices
        label = dict(PaymentStatusChoices.choices).get(status, status)
        distribution.append({
            'label': label,
            'value': count,
            'percentage': _calculate_percentage(count, total_count),
            'status_code': status
        })
    
    return {
        'total': total_count,
        'distribution': distribution
    }


def calculate_payment_method_distribution(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate distribution of payment methods.
    
    Args:
        event_id: Optional event UUID to filter payments
        include_deleted: IGNORED - Payment model does not support soft-delete
    
    Returns:
        Dictionary with method distribution data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    total_count = queryset.count()
    
    # Get method counts
    method_counts = queryset.filter(
        method__isnull=False
    ).values(
        'method__title',
        'method__method_type'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    without_method = queryset.filter(method__isnull=True).count()
    
    distribution = []
    for item in method_counts:
        count = item['count']
        distribution.append({
            'label': item['method__title'],
            'value': count,
            'percentage': _calculate_percentage(count, total_count),
            'method_type': item['method__method_type']
        })
    
    return {
        'total': total_count,
        'total_with_method': total_count - without_method,
        'total_without_method': without_method,
        'distribution': distribution
    }


def calculate_payment_trends(
    event_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate payment creation trends over time.
    
    Args:
        event_id: Optional event UUID to filter payments
        group_by: Time grouping ('hour', 'day', 'week', 'month')
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: IGNORED - Payment model does not support soft-delete
    
    Returns:
        Dictionary with trend data:
        {
            'trends': [{'date': str, 'count': int}, ...],
            'total': int
        }
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    # Apply date filtering
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    
    # Group by time period
    if group_by == 'hour':
        queryset = queryset.annotate(period=TruncHour('created_at'))
    elif group_by == 'week':
        queryset = queryset.annotate(period=TruncWeek('created_at'))
    elif group_by == 'month':
        queryset = queryset.annotate(period=TruncMonth('created_at'))
    else:  # day
        queryset = queryset.annotate(period=TruncDate('created_at'))
    
    trends = queryset.values('period').annotate(
        count=Count('id')
    ).order_by('period')
    
    trends_data = [
        {
            'date': item['period'].isoformat() if item['period'] else None,
            'count': item['count']
        }
        for item in trends
    ]
    
    return {
        'trends': trends_data,
        'total': sum(item['count'] for item in trends_data)
    }


def calculate_payment_overview(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate payment overview statistics.
    
    Args:
        event_id: Optional event UUID to filter payments
        include_deleted: IGNORED - Payment model does not support soft-delete
    
    Returns:
        Dictionary with overview data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    total_payments = queryset.count()
    
    # Status breakdown
    status_breakdown = {}
    for status_choice in PaymentStatusChoices:
        count = queryset.filter(status=status_choice.value).count()
        status_breakdown[status_choice.value] = {
            'count': count,
            'label': status_choice.label,
            'percentage': _calculate_percentage(count, total_payments)
        }
    
    # Calculate average payment amount
    avg_amount = queryset.aggregate(avg=Avg('base_amount'))['avg']
    
    # Total amount (all payments)
    total_amount = queryset.aggregate(total=Sum('base_amount'))['total']
    
    return {
        'total_payments': total_payments,
        'total_amount': _format_money_value(total_amount),
        'average_amount': _format_money_value(avg_amount),
        'status_breakdown': status_breakdown
    }


# ============================================================================
# DISCOUNT STATISTICS
# ============================================================================

def calculate_discount_usage(
    event_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate discount usage statistics.
    
    Args:
        event_id: Optional event UUID to filter by event target
    
    Returns:
        Dictionary with discount usage data
    """
    from apps.events.models import Event
    # Get discounts targeting the specific event or all if no event specified
    queryset = Discount.objects.filter(active=True)
    
    if event_id:
        event = Event.objects.filter(event_id=event_id).first()
        if not event:
            # Event not found, return empty queryset
            return {
                'total_discounts': 0,
                'type_distribution': []
            }
        event_ct = ContentType.objects.get(app_label='events', model='event')
        queryset = queryset.filter(target_type=event_ct, target_id=event.id)
    
    total_discounts = queryset.count()
    
    # Count discounts by type
    type_breakdown = queryset.values('discount_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    type_distribution = []
    for item in type_breakdown:
        count = item['count']
        type_distribution.append({
            'label': dict(Discount._meta.get_field('discount_type').choices).get(item['discount_type'], item['discount_type']),
            'value': count,
            'percentage': _calculate_percentage(count, total_discounts),
            'type_code': item['discount_type']
        })
    
    return {
        'total_discounts': total_discounts,
        'type_distribution': type_distribution
    }


def calculate_discount_rule_effectiveness(
    event_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate discount rule effectiveness (which rule types are most common).
    
    Args:
        event_id: Optional event UUID to filter discounts
    
    Returns:
        Dictionary with rule effectiveness data
    """
    # Get rules for active discounts
    from apps.events.models import Event
    queryset = DiscountRule.objects.filter(discount__active=True, active=True)
    
    if event_id:
        event = Event.objects.filter(event_id=event_id).first()
        if not event:
            # Event not found, return empty results
            return {
                'total_rules': 0,
                'rules': []
            }
        event_ct = ContentType.objects.get(app_label='events', model='event')
        queryset = queryset.filter(
            discount__target_type=event_ct,
            discount__target_id=event.id
        )
    
    total_rules = queryset.count()
    
    # Count by rule type
    rule_counts = queryset.values('rule_type').annotate(
        count=Count('discount_id')
    ).order_by('-count')
    
    rules_data = []
    for item in rule_counts:
        count = item['count']
        rules_data.append({
            'rule_type': item['rule_type'],
            'label': item['rule_type'].replace('_', ' ').title(),
            'count': count,
            'percentage': _calculate_percentage(count, total_rules)
        })
    
    return {
        'total_rules': total_rules,
        'rules': rules_data
    }


def calculate_top_discounts(
    event_id: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate top discounts by usage (most referenced).
    
    Note: This returns configured discounts. Actual usage tracking would require
    application data which isn't stored directly on Discount model.
    
    Args:
        event_id: Optional event UUID to filter discounts
        limit: Maximum number of results to return
    
    Returns:
        Dictionary with top discounts data
    """
    from apps.events.models import Event
    queryset = Discount.objects.filter(active=True)
    
    if event_id:
        event = Event.objects.filter(event_id=event_id).first()
        if not event:
            # Event not found, return empty results
            return {
                'total_returned': 0,
                'limit': limit,
                'discounts': []
            }
        event_ct = ContentType.objects.get(app_label='events', model='event')
        queryset = queryset.filter(target_type=event_ct, target_id=event.id)
    
    # Get top discounts ordered by creation date (most recently created)
    top_discounts = queryset.order_by('-created_at')[:limit]
    
    discounts_data = []
    for discount in top_discounts:
        discount_info = {
            'id': str(discount.discount_id),
            'name': discount.name,
            'discount_type': discount.discount_type,
            'rule_count': discount.rules.filter(active=True).count()
        }
        
        if discount.discount_type == 'PERCENTAGE':
            discount_info['value'] = float(discount.percentage) if discount.percentage else 0
            discount_info['display_value'] = f"{discount.percentage}%"
        else:
            discount_info['value'] = _format_money_value(discount.amount)
            discount_info['display_value'] = f"£{_format_money_value(discount.amount)}"
        
        discounts_data.append(discount_info)
    
    return {
        'total_returned': len(discounts_data),
        'limit': limit,
        'discounts': discounts_data
    }


# ============================================================================
# REFUND STATISTICS
# ============================================================================

def calculate_refund_request_stats(
    event_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate refund request statistics.
    
    Args:
        event_id: Optional event UUID to filter by payment event
    
    Returns:
        Dictionary with refund request statistics
    """
    queryset = RefundRequest.objects.all()
    
    if event_id:
        queryset = queryset.filter(payment__event__event_id=event_id)
    
    total_requests = queryset.count()
    
    # Calculate total amount requested
    total_amount = queryset.aggregate(total=Sum('amount'))['total']
    
    # Status breakdown (using RequiresVerificationModel verification_status field)
    status_counts = queryset.values('verification_status').annotate(
        count=Count('id'),
        total_amount=Sum('amount')
    ).order_by('-count')
    
    status_distribution = []
    for item in status_counts:
        count = item['count']
        status_distribution.append({
            'label': item['verification_status'].replace('_', ' ').title() if item['verification_status'] else 'Unknown',
            'value': count,
            'percentage': _calculate_percentage(count, total_requests),
            'total_amount': _format_money_value(item['total_amount']),
            'status_code': item['verification_status']
        })
    
    return {
        'total_requests': total_requests,
        'total_amount': _format_money_value(total_amount),
        'status_distribution': status_distribution
    }


def calculate_refund_trends(
    event_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None
) -> Dict[str, Any]:
    """
    Calculate refund request trends over time.
    
    Args:
        event_id: Optional event UUID to filter refunds
        group_by: Time grouping ('hour', 'day', 'week', 'month')
        date_from: Start date for filtering
        date_to: End date for filtering
    
    Returns:
        Dictionary with refund trend data
    """
    queryset = RefundRequest.objects.all()
    
    if event_id:
        queryset = queryset.filter(payment__event__event_id=event_id)
    
    # Apply date filtering
    if date_from:
        queryset = queryset.filter(requested_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(requested_at__date__lte=date_to)
    
    # Group by time period
    if group_by == 'hour':
        queryset = queryset.annotate(period=TruncHour('requested_at'))
    elif group_by == 'week':
        queryset = queryset.annotate(period=TruncWeek('requested_at'))
    elif group_by == 'month':
        queryset = queryset.annotate(period=TruncMonth('requested_at'))
    else:  # day
        queryset = queryset.annotate(period=TruncDate('requested_at'))
    
    trends = queryset.values('period').annotate(
        count=Count('id'),
        total_amount=Sum('amount')
    ).order_by('period')
    
    trends_data = [
        {
            'date': item['period'].isoformat() if item['period'] else None,
            'count': item['count'],
            'amount': _format_money_value(item['total_amount'])
        }
        for item in trends
    ]
    
    return {
        'trends': trends_data,
        'total_count': sum(item['count'] for item in trends_data),
        'total_amount': sum(item['amount'] or 0 for item in trends_data)
    }


def calculate_refund_processing_times(
    event_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate refund processing time statistics.
    
    Args:
        event_id: Optional event UUID to filter refunds
    
    Returns:
        Dictionary with processing time statistics
    """
    queryset = RefundRequest.objects.filter(
        processed_at__isnull=False,
        requested_at__isnull=False
    )
    
    if event_id:
        queryset = queryset.filter(payment__event__event_id=event_id)
    
    total_processed = queryset.count()
    
    if total_processed == 0:
        return {
            'total_processed': 0,
            'average_days': None,
            'median_days': None,
            'min_days': None,
            'max_days': None
        }
    
    # Calculate processing times in days
    processing_times = []
    for refund in queryset:
        days = (refund.processed_at - refund.requested_at).days
        processing_times.append(days)
    
    processing_times.sort()
    
    # Calculate statistics
    average_days = sum(processing_times) / len(processing_times)
    median_days = processing_times[len(processing_times) // 2]
    min_days = min(processing_times)
    max_days = max(processing_times)
    
    return {
        'total_processed': total_processed,
        'average_days': round(average_days, 2),
        'median_days': median_days,
        'min_days': min_days,
        'max_days': max_days
    }


# ============================================================================
# DONATION STATISTICS
# ============================================================================

def calculate_donation_stats(
    event_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate donation statistics.
    
    NOTE: Donations are linked to payments, which have direct event FK.
    
    Args:
        event_id: Optional event UUID to filter donations via payment
    
    Returns:
        Dictionary with donation statistics
    """
    queryset = Donation.objects.all()
    
    if event_id:
        queryset = queryset.filter(payment__event__event_id=event_id)
    
    total_donations = queryset.count()
    
    # Calculate totals
    total_amount = queryset.aggregate(total=Sum('amount'))['total']
    average_amount = queryset.aggregate(avg=Avg('amount'))['avg']
    
    # Status breakdown (using RequiresVerificationModel verification_status)
    status_counts = queryset.values('verification_status').annotate(
        count=Count('id'),
        total_amount=Sum('amount')
    ).order_by('-count')
    
    status_distribution = []
    for item in status_counts:
        count = item['count']
        status_distribution.append({
            'label': item['verification_status'].replace('_', ' ').title() if item['verification_status'] else 'Unknown',
            'value': count,
            'percentage': _calculate_percentage(count, total_donations),
            'total_amount': _format_money_value(item['total_amount']),
            'status_code': item['verification_status']
        })
    
    return {
        'total_donations': total_donations,
        'total_amount': _format_money_value(total_amount),
        'average_amount': _format_money_value(average_amount),
        'status_distribution': status_distribution
    }


def calculate_donation_trends(
    event_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None
) -> Dict[str, Any]:
    """
    Calculate donation trends over time.
    
    Args:
        event_id: Optional event UUID to filter donations
        group_by: Time grouping ('hour', 'day', 'week', 'month')
        date_from: Start date for filtering
        date_to: End date for filtering
    
    Returns:
        Dictionary with donation trend data
    """
    queryset = Donation.objects.all()
    
    if event_id:
        queryset = queryset.filter(payment__event__event_id=event_id)
    
    # Apply date filtering
    if date_from:
        queryset = queryset.filter(donated_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(donated_at__date__lte=date_to)
    
    # Group by time period
    if group_by == 'hour':
        queryset = queryset.annotate(period=TruncHour('donated_at'))
    elif group_by == 'week':
        queryset = queryset.annotate(period=TruncWeek('donated_at'))
    elif group_by == 'month':
        queryset = queryset.annotate(period=TruncMonth('donated_at'))
    else:  # day
        queryset = queryset.annotate(period=TruncDate('donated_at'))
    
    trends = queryset.values('period').annotate(
        count=Count('id'),
        total_amount=Sum('amount')
    ).order_by('period')
    
    trends_data = [
        {
            'date': item['period'].isoformat() if item['period'] else None,
            'count': item['count'],
            'amount': _format_money_value(item['total_amount'])
        }
        for item in trends
    ]
    
    return {
        'trends': trends_data,
        'total_count': sum(item['count'] for item in trends_data),
        'total_amount': sum(item['amount'] or 0 for item in trends_data)
    }


def calculate_top_donors(
    event_id: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Calculate top donors by total donation amount.
    
    Args:
        event_id: Optional event UUID to filter donations
        limit: Maximum number of results to return
    
    Returns:
        Dictionary with top donors data
    """
    queryset = Donation.objects.filter(donated_by__isnull=False)
    
    if event_id:
        queryset = queryset.filter(payment__event__event_id=event_id)
    
    # Group by donor and sum amounts
    top_donors = queryset.values(
        'donated_by__id',
        'donated_by__email',
        'donated_by__first_name',
        'donated_by__last_name'
    ).annotate(
        total_donated=Sum('amount'),
        donation_count=Count('id')
    ).order_by('-total_donated')[:limit]
    
    donors_data = []
    for donor in top_donors:
        full_name = f"{donor['donated_by__first_name']} {donor['donated_by__last_name']}".strip()
        donors_data.append({
            'user_id': donor['donated_by__id'],
            'email': donor['donated_by__email'],
            'name': full_name if full_name else donor['donated_by__email'],
            'total_donated': _format_money_value(donor['total_donated']),
            'donation_count': donor['donation_count']
        })
    
    return {
        'total_returned': len(donors_data),
        'limit': limit,
        'donors': donors_data
    }


# ============================================================================
# REVENUE STATISTICS (CRITICAL - Only COMPLETED payments count)
# ============================================================================

def calculate_revenue_overview(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue overview statistics.
    
    CRITICAL: Only COMPLETED payments count toward revenue.
    
    Args:
        event_id: Optional event UUID to filter payments
        include_deleted: IGNORED for payments (no soft-delete support)
    
    Returns:
        Dictionary with revenue overview data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    # Only count COMPLETED payments for revenue
    completed_payments = queryset.filter(status=PaymentStatusChoices.COMPLETED)
    
    total_completed = completed_payments.count()
    total_revenue = completed_payments.aggregate(total=Sum('base_amount'))['total']
    average_payment = completed_payments.aggregate(avg=Avg('base_amount'))['avg']
    
    # Calculate refunded amount (from REFUNDED status payments)
    refunded_payments = queryset.filter(status=PaymentStatusChoices.REFUNDED)
    total_refunded = refunded_payments.aggregate(total=Sum('base_amount'))['total']
    
    # Net revenue = completed - refunded
    net_revenue = (
        _format_money_value(total_revenue) or 0
    ) - (
        _format_money_value(total_refunded) or 0
    )
    
    return {
        'total_revenue': _format_money_value(total_revenue),
        'total_completed_payments': total_completed,
        'average_payment': _format_money_value(average_payment),
        'total_refunded': _format_money_value(total_refunded),
        'refunded_payment_count': refunded_payments.count(),
        'net_revenue': net_revenue
    }


def calculate_revenue_trends(
    event_id: Optional[str] = None,
    group_by: str = 'day',
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue trends over time.
    
    CRITICAL: Only COMPLETED payments count toward revenue.
    
    Args:
        event_id: Optional event UUID to filter payments
        group_by: Time grouping ('hour', 'day', 'week', 'month')
        date_from: Start date for filtering
        date_to: End date for filtering
        include_deleted: IGNORED for payments (no soft-delete support)
    
    Returns:
        Dictionary with revenue trend data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    # Only count COMPLETED payments
    queryset = queryset.filter(status=PaymentStatusChoices.COMPLETED)
    
    # Apply date filtering
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    
    # Group by time period
    if group_by == 'hour':
        queryset = queryset.annotate(period=TruncHour('created_at'))
    elif group_by == 'week':
        queryset = queryset.annotate(period=TruncWeek('created_at'))
    elif group_by == 'month':
        queryset = queryset.annotate(period=TruncMonth('created_at'))
    else:  # day
        queryset = queryset.annotate(period=TruncDate('created_at'))
    
    trends = queryset.values('period').annotate(
        revenue=Sum('base_amount'),
        count=Count('id')
    ).order_by('period')
    
    trends_data = [
        {
            'date': item['period'].isoformat() if item['period'] else None,
            'revenue': _format_money_value(item['revenue']),
            'count': item['count']
        }
        for item in trends
    ]
    
    return {
        'trends': trends_data,
        'total_revenue': sum(item['revenue'] or 0 for item in trends_data),
        'total_payments': sum(item['count'] for item in trends_data)
    }


def calculate_revenue_by_method(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate revenue breakdown by payment method.
    
    CRITICAL: Only COMPLETED payments count toward revenue.
    
    Args:
        event_id: Optional event UUID to filter payments
        include_deleted: IGNORED for payments (no soft-delete support)
    
    Returns:
        Dictionary with revenue by method data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    # Only count COMPLETED payments
    queryset = queryset.filter(status=PaymentStatusChoices.COMPLETED)
    
    total_revenue = queryset.aggregate(total=Sum('base_amount'))['total']
    total_revenue_float = _format_money_value(total_revenue) or 0
    
    # Group by payment method
    method_revenue = queryset.filter(
        method__isnull=False
    ).values(
        'method__title',
        'method__method_type'
    ).annotate(
        revenue=Sum('base_amount'),
        count=Count('id')
    ).order_by('-revenue')
    
    methods_data = []
    for item in method_revenue:
        revenue = _format_money_value(item['revenue']) or 0
        methods_data.append({
            'method': item['method__title'],
            'method_type': item['method__method_type'],
            'revenue': revenue,
            'payment_count': item['count'],
            'percentage': _calculate_percentage(int(revenue), int(total_revenue_float)) if total_revenue_float > 0 else 0
        })
    
    # Count payments without method
    without_method_revenue = queryset.filter(
        method__isnull=True
    ).aggregate(
        revenue=Sum('base_amount'),
        count=Count('id')
    )
    
    return {
        'total_revenue': total_revenue_float,
        'methods': methods_data,
        'without_method_revenue': _format_money_value(without_method_revenue['revenue']),
        'without_method_count': without_method_revenue['count']
    }


def calculate_revenue_breakdown(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate comprehensive revenue breakdown.
    
    CRITICAL: Only COMPLETED payments count toward revenue.
    
    Args:
        event_id: Optional event UUID to filter payments
        include_deleted: IGNORED for payments (no soft-delete support)
    
    Returns:
        Dictionary with revenue breakdown data
    """
    queryset = _get_base_queryset(event_id, include_deleted)
    
    # Gross revenue (completed payments)
    completed_payments = queryset.filter(status=PaymentStatusChoices.COMPLETED)
    gross_revenue = completed_payments.aggregate(total=Sum('base_amount'))['total']
    gross_revenue_float = _format_money_value(gross_revenue) or 0
    
    # Refunded amount
    refunded_payments = queryset.filter(status=PaymentStatusChoices.REFUNDED)
    refunded_amount = refunded_payments.aggregate(total=Sum('base_amount'))['total']
    refunded_amount_float = _format_money_value(refunded_amount) or 0
    
    # Pending refund amount
    pending_refund_payments = queryset.filter(status=PaymentStatusChoices.PENDING_REFUND)
    pending_refund_amount = pending_refund_payments.aggregate(total=Sum('base_amount'))['total']
    pending_refund_amount_float = _format_money_value(pending_refund_amount) or 0
    
    # Net revenue
    net_revenue = gross_revenue_float - refunded_amount_float
    
    return {
        'gross_revenue': gross_revenue_float,
        'completed_payment_count': completed_payments.count(),
        'refunded_amount': refunded_amount_float,
        'refunded_payment_count': refunded_payments.count(),
        'pending_refund_amount': pending_refund_amount_float,
        'pending_refund_count': pending_refund_payments.count(),
        'net_revenue': net_revenue
    }


def calculate_sponsor_package_payment_status(
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate sponsor package payment status and revenue metrics."""
    package_qs = EventSponsorPackage.objects.all().select_related('event')
    if event_id:
        package_qs = package_qs.filter(event__event_id=event_id)

    # Payment.target_id is a CharField (GenericForeignKey), so package IDs
    # must be compared as strings to avoid DB type mismatch errors.
    package_ids = list(package_qs.values_list('id', flat=True))
    package_id_strings = [str(package_id) for package_id in package_ids]

    payment_ct = ContentType.objects.get_for_model(EventSponsorPackage)
    payment_qs = Payment.objects.filter(
        target_type=payment_ct,
        target_id__in=package_id_strings,
    )

    distribution = []
    total_amount = Decimal('0.00')
    total_count = 0

    status_counts = payment_qs.values('status').annotate(
        count=Count('id'),
        amount=Coalesce(Sum('base_amount'), Decimal('0.00')),
    )
    for item in status_counts:
        amount = item['amount']
        total_amount += amount
        total_count += item['count']
        distribution.append({
            'status': item['status'],
            'count': item['count'],
            'amount': float(amount),
        })

    package_rows = []
    for pkg in package_qs.order_by('tier', 'package_name'):
        pkg_payments = payment_qs.filter(target_id=str(pkg.id))
        completed_amount = pkg_payments.filter(status=PaymentStatusChoices.COMPLETED).aggregate(
            total=Coalesce(Sum('base_amount'), Decimal('0.00'))
        )['total']
        refunded_amount = pkg_payments.filter(status=PaymentStatusChoices.REFUNDED).aggregate(
            total=Coalesce(Sum('base_amount'), Decimal('0.00'))
        )['total']

        package_rows.append({
            'package_id': str(pkg.package_id),
            'package_name': pkg.package_name,
            'event_id': str(pkg.event.event_id),
            'event_title': pkg.event.title,
            'tier': pkg.tier,
            'active': pkg.active,
            'payment_count': pkg_payments.count(),
            'completed_revenue': float(completed_amount),
            'refunded_revenue': float(refunded_amount),
            'net_revenue': float(completed_amount - refunded_amount),
        })

    return {
        'total_packages': package_qs.count(),
        'total_payments': total_count,
        'total_amount': float(total_amount),
        'distribution': distribution,
        'packages': package_rows,
    }


# ============================================================================
# COMBINED OVERVIEW
# ============================================================================

def calculate_overview_stats(
    event_id: Optional[str] = None,
    include_deleted: bool = False
) -> Dict[str, Any]:
    """
    Calculate combined overview statistics for dashboard display.
    
    Args:
        event_id: Optional event UUID to filter statistics
        include_deleted: Whether to include soft-deleted orders (only affects order stats)
    
    Returns:
        Dictionary with combined overview data
    """
    # Payment overview
    payment_overview = calculate_payment_overview(event_id, include_deleted)
    
    # Revenue overview (only completed payments)
    revenue_overview = calculate_revenue_overview(event_id, include_deleted)
    
    # Discount summary
    discount_usage = calculate_discount_usage(event_id)
    
    # Refund summary
    refund_stats = calculate_refund_request_stats(event_id)
    
    # Donation summary
    donation_stats = calculate_donation_stats(event_id)

    sponsor_package_stats = calculate_sponsor_package_payment_status(event_id)
    
    return {
        'payments': {
            'total': payment_overview['total_payments'],
            'total_amount': payment_overview['total_amount'],
            'average_amount': payment_overview['average_amount'],
            'by_status': payment_overview['status_breakdown']
        },
        'revenue': {
            'gross': revenue_overview['total_revenue'],
            'net': revenue_overview['net_revenue'],
            'refunded': revenue_overview['total_refunded'],
            'completed_count': revenue_overview['total_completed_payments']
        },
        'discounts': {
            'total_active': discount_usage['total_discounts'],
            'by_type': discount_usage['type_distribution']
        },
        'refunds': {
            'total_requests': refund_stats['total_requests'],
            'total_amount': refund_stats['total_amount'],
            'by_status': refund_stats['status_distribution']
        },
        'donations': {
            'total': donation_stats['total_donations'],
            'total_amount': donation_stats['total_amount'],
            'average_amount': donation_stats['average_amount']
        },
        'sponsors': {
            'total_packages': sponsor_package_stats['total_packages'],
            'total_payments': sponsor_package_stats['total_payments'],
            'total_amount': sponsor_package_stats['total_amount'],
            'distribution': sponsor_package_stats['distribution'],
            'packages': sponsor_package_stats['packages'],
        }
    }
