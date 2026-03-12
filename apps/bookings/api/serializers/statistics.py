"""
Booking Statistics Serializers

Serializers for booking statistics API responses.
These validate and format the output from the statistics calculation functions.
"""
from rest_framework import serializers
from typing import Dict, List, Any


# ============================================================================
# BASE SERIALIZERS
# ============================================================================

class BaseStatisticsSerializer(serializers.Serializer):
    """Base serializer for statistics responses."""
    generated_at = serializers.DateTimeField(required=False)
    filters_applied = serializers.DictField(required=False)


class DistributionItemSerializer(serializers.Serializer):
    """Serializer for distribution item."""
    label = serializers.CharField()
    value = serializers.IntegerField()
    percentage = serializers.FloatField()


class StatusBreakdownSerializer(serializers.Serializer):
    """Serializer for status breakdown item."""
    status = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class ScopeBreakdownSerializer(serializers.Serializer):
    """Serializer for scope breakdown item."""
    scope = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class TrendItemSerializer(serializers.Serializer):
    """Serializer for trend data point."""
    date = serializers.CharField()
    count = serializers.IntegerField()


class RevenueTrendItemSerializer(serializers.Serializer):
    """Serializer for revenue trend data point."""
    date = serializers.CharField()
    revenue = serializers.FloatField()
    payment_count = serializers.IntegerField()


# ============================================================================
# BOOKING STATISTICS SERIALIZERS
# ============================================================================

class BookingOverviewSerializer(BaseStatisticsSerializer):
    """Serializer for booking overview statistics."""
    total_bookings = serializers.IntegerField()
    total_attendees = serializers.IntegerField()
    total_tickets = serializers.IntegerField()
    average_attendees_per_booking = serializers.FloatField()
    status_breakdown = StatusBreakdownSerializer(many=True)


class BookingStatusDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for booking status distribution."""
    total = serializers.IntegerField()
    distribution = DistributionItemSerializer(many=True)


class BookingTrendsSerializer(BaseStatisticsSerializer):
    """Serializer for booking trends over time."""
    total_bookings = serializers.IntegerField()
    group_by = serializers.CharField()
    trends = TrendItemSerializer(many=True)


class BookingsByPackageItemSerializer(serializers.Serializer):
    """Serializer for bookings by package item."""
    package_name = serializers.CharField()
    package_id = serializers.IntegerField()
    ticket_count = serializers.IntegerField()
    percentage = serializers.FloatField()


class BookingsByPackageSerializer(BaseStatisticsSerializer):
    """Serializer for bookings by package."""
    total_tickets_with_package = serializers.IntegerField()
    total_tickets_without_package = serializers.IntegerField()
    distribution = BookingsByPackageItemSerializer(many=True)


class AttendeesPerBookingItemSerializer(serializers.Serializer):
    """Serializer for attendees per booking distribution item."""
    attendee_count = serializers.IntegerField()
    booking_count = serializers.IntegerField()


class AttendeesPerBookingSerializer(BaseStatisticsSerializer):
    """Serializer for attendees per booking distribution."""
    total_bookings = serializers.IntegerField()
    average_attendees = serializers.FloatField()
    max_attendees = serializers.IntegerField()
    min_attendees = serializers.IntegerField()
    distribution = AttendeesPerBookingItemSerializer(many=True)


class BookingCompletionRateSerializer(BaseStatisticsSerializer):
    """Serializer for booking completion rate."""
    total_intents = serializers.IntegerField()
    completed_intents = serializers.IntegerField()
    expired_intents = serializers.IntegerField()
    cancelled_intents = serializers.IntegerField()
    pending_intents = serializers.IntegerField()
    total_bookings = serializers.IntegerField()
    completion_rate = serializers.FloatField()


class BookingReferenceTypeItemSerializer(serializers.Serializer):
    """Serializer for booking reference type item."""
    event_code = serializers.CharField()
    count = serializers.IntegerField()


class BookingReferenceTypesSerializer(BaseStatisticsSerializer):
    """Serializer for booking reference types distribution."""
    total_bookings = serializers.IntegerField()
    distribution = BookingReferenceTypeItemSerializer(many=True)


class BookingTimelineSerializer(BaseStatisticsSerializer):
    """Serializer for booking timeline."""
    total_bookings = serializers.IntegerField()
    timeline = TrendItemSerializer(many=True)


# ============================================================================
# TICKET STATISTICS SERIALIZERS
# ============================================================================

class TicketOverviewSerializer(BaseStatisticsSerializer):
    """Serializer for ticket overview statistics."""
    total_tickets = serializers.IntegerField()
    status_breakdown = StatusBreakdownSerializer(many=True)
    scope_breakdown = ScopeBreakdownSerializer(many=True)
    average_uses_remaining = serializers.FloatField()
    total_uses_remaining = serializers.IntegerField()


class TicketStatusDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for ticket status distribution."""
    total = serializers.IntegerField()
    distribution = DistributionItemSerializer(many=True)


class TicketTypeDistributionItemSerializer(serializers.Serializer):
    """Serializer for ticket type distribution item."""
    ticket_type_id = serializers.IntegerField()
    scope = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class TicketTypeDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for ticket type distribution."""
    total = serializers.IntegerField()
    distribution = TicketTypeDistributionItemSerializer(many=True)


class TicketUsageStatsSerializer(BaseStatisticsSerializer):
    """Serializer for ticket usage statistics."""
    total_tickets = serializers.IntegerField()
    valid_tickets = serializers.IntegerField()
    used_tickets = serializers.IntegerField()
    cancelled_tickets = serializers.IntegerField()
    average_uses_remaining = serializers.FloatField()
    total_uses_remaining = serializers.IntegerField()
    max_uses = serializers.IntegerField()
    min_uses = serializers.IntegerField()
    usage_rate = serializers.FloatField()


class TicketScopeDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for ticket scope distribution."""
    total = serializers.IntegerField()
    distribution = DistributionItemSerializer(many=True)


# ============================================================================
# PACKAGE STATISTICS SERIALIZERS
# ============================================================================

class PackageOverviewSerializer(BaseStatisticsSerializer):
    """Serializer for package overview statistics."""
    total_packages = serializers.IntegerField()
    active_packages = serializers.IntegerField()
    inactive_packages = serializers.IntegerField()
    packages_with_tickets = serializers.IntegerField()
    total_tickets_using_packages = serializers.IntegerField()
    total_rules = serializers.IntegerField()
    active_rules = serializers.IntegerField()


class PackagePopularityItemSerializer(serializers.Serializer):
    """Serializer for package popularity item."""
    package_id = serializers.IntegerField()
    package_name = serializers.CharField()
    ticket_count = serializers.IntegerField()
    is_active = serializers.BooleanField()
    base_amount = serializers.FloatField()


class PackagePopularitySerializer(BaseStatisticsSerializer):
    """Serializer for package popularity."""
    total_packages = serializers.IntegerField()
    popularity = PackagePopularityItemSerializer(many=True)


class PackageRuleDistributionSerializer(BaseStatisticsSerializer):
    """Serializer for package rule distribution."""
    total_rules = serializers.IntegerField()
    distribution = DistributionItemSerializer(many=True)


class PackagePricingItemSerializer(serializers.Serializer):
    """Serializer for package pricing item."""
    package_id = serializers.IntegerField()
    package_name = serializers.CharField()
    base_amount = serializers.FloatField()
    percentage_modifier = serializers.FloatField()
    is_active = serializers.BooleanField()


class PackagePricingAnalysisSerializer(BaseStatisticsSerializer):
    """Serializer for package pricing analysis."""
    total_packages = serializers.IntegerField()
    average_base_amount = serializers.FloatField()
    max_base_amount = serializers.FloatField()
    min_base_amount = serializers.FloatField()
    average_modifier = serializers.FloatField()
    packages = PackagePricingItemSerializer(many=True)


# ============================================================================
# INTENT STATISTICS SERIALIZERS
# ============================================================================

class IntentOverviewSerializer(BaseStatisticsSerializer):
    """Serializer for intent overview statistics."""
    total_intents = serializers.IntegerField()
    status_breakdown = StatusBreakdownSerializer(many=True)
    total_capacity_reserved = serializers.IntegerField()
    average_capacity_per_intent = serializers.FloatField()


class IntentConversionRateSerializer(BaseStatisticsSerializer):
    """Serializer for intent conversion rate."""
    total_intents = serializers.IntegerField()
    completed = serializers.IntegerField()
    expired = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    pending = serializers.IntegerField()
    conversion_rate = serializers.FloatField()
    expiration_rate = serializers.FloatField()
    cancellation_rate = serializers.FloatField()


class IntentTrendsSerializer(BaseStatisticsSerializer):
    """Serializer for intent trends over time."""
    total_intents = serializers.IntegerField()
    group_by = serializers.CharField()
    trends = TrendItemSerializer(many=True)


# ============================================================================
# REVENUE STATISTICS SERIALIZERS
# ============================================================================

class BookingRevenueOverviewSerializer(BaseStatisticsSerializer):
    """Serializer for revenue overview statistics."""
    total_revenue = serializers.FloatField()
    average_revenue_per_booking = serializers.FloatField()
    max_revenue = serializers.FloatField()
    min_revenue = serializers.FloatField()
    total_bookings = serializers.IntegerField()
    total_completed_payments = serializers.IntegerField()


class RevenueByPackageItemSerializer(serializers.Serializer):
    """Serializer for revenue by package item."""
    package_id = serializers.IntegerField()
    package_name = serializers.CharField()
    revenue = serializers.FloatField()
    ticket_count = serializers.IntegerField()


class RevenueByPackageSerializer(BaseStatisticsSerializer):
    """Serializer for revenue by package."""
    total_revenue = serializers.FloatField()
    distribution = RevenueByPackageItemSerializer(many=True)


class RevenueByTicketTypeItemSerializer(serializers.Serializer):
    """Serializer for revenue by ticket type item."""
    ticket_type_id = serializers.IntegerField()
    scope = serializers.CharField()
    revenue = serializers.FloatField()
    ticket_count = serializers.IntegerField()


class RevenueByTicketTypeSerializer(BaseStatisticsSerializer):
    """Serializer for revenue by ticket type."""
    total_revenue = serializers.FloatField()
    distribution = RevenueByTicketTypeItemSerializer(many=True)


class BookingRevenueTrendsSerializer(BaseStatisticsSerializer):
    """Serializer for revenue trends."""
    total_revenue = serializers.FloatField()
    group_by = serializers.CharField()
    trends = RevenueTrendItemSerializer(many=True)


class RevenueBreakdownItemSerializer(serializers.Serializer):
    """Serializer for revenue breakdown item."""
    status = serializers.CharField()
    revenue = serializers.FloatField()
    payment_count = serializers.IntegerField()


class BookingRevenueBreakdownSerializer(BaseStatisticsSerializer):
    """Serializer for revenue breakdown by status."""
    total_revenue_all_statuses = serializers.FloatField()
    completed_revenue = serializers.FloatField()
    distribution = RevenueBreakdownItemSerializer(many=True)


# ============================================================================
# COMBINED OVERVIEW SERIALIZERS
# ============================================================================

class BookingsSummarySerializer(serializers.Serializer):
    """Serializer for bookings summary in overview."""
    total = serializers.IntegerField()
    total_attendees = serializers.IntegerField()
    average_attendees_per_booking = serializers.FloatField()


class TicketsSummarySerializer(serializers.Serializer):
    """Serializer for tickets summary in overview."""
    total = serializers.IntegerField()
    status_breakdown = StatusBreakdownSerializer(many=True)


class PackagesSummarySerializer(serializers.Serializer):
    """Serializer for packages summary in overview."""
    total = serializers.IntegerField()
    active = serializers.IntegerField()
    total_usage = serializers.IntegerField()


class IntentsSummarySerializer(serializers.Serializer):
    """Serializer for intents summary in overview."""
    total = serializers.IntegerField()
    status_breakdown = StatusBreakdownSerializer(many=True)


class RevenueSummarySerializer(serializers.Serializer):
    """Serializer for revenue summary in overview."""
    total = serializers.FloatField()
    average_per_booking = serializers.FloatField()
    total_completed_payments = serializers.IntegerField()


class BookingStatisticsOverviewSerializer(BaseStatisticsSerializer):
    """Serializer for combined booking statistics overview."""
    bookings = BookingsSummarySerializer()
    tickets = TicketsSummarySerializer()
    packages = PackagesSummarySerializer()
    intents = IntentsSummarySerializer()
    revenue = RevenueSummarySerializer()
