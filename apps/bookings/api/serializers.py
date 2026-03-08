"""
Production-grade serializers for the bookings app.

Provides comprehensive serializers for booking management with HATEOAS support,
extensive validation, timezone handling, and separation of concerns (list/detail/create/update).

Serializers:
    TicketType: TicketTypeListSerializer, TicketTypeDetailSerializer, TicketTypeCreateUpdateSerializer
    Ticket: TicketListSerializer, TicketDetailSerializer
    BookingPackage: BookingPackageListSerializer, BookingPackageDetailSerializer, BookingPackageCreateUpdateSerializer
    BookingPackageRule: BookingPackageRuleSerializer, BookingPackageRuleCreateUpdateSerializer
    Booking: BookingListSerializer, BookingDetailSerializer, BookingCreateSerializer, BookingUpdateSerializer
    EventAlternativeSigninIdentifier: EventAlternativeSigninListSerializer, EventAlternativeSigninDetailSerializer, EventAlternativeSigninCreateUpdateSerializer
    AttendeeAlternativeSigninIdentifier: AttendeeAlternativeSigninListSerializer, AttendeeAlternativeSigninDetailSerializer, AttendeeAlternativeSigninCreateUpdateSerializer

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from djmoney.money import Money
from djmoney.contrib.django_rest_framework import MoneyField
from decimal import Decimal
from typing import Dict, Any, Optional
import pytz

from apps.bookings.models import (
    Booking, BookingIntent, BookingIntentStatusChoices,
    BookingPackage, BookingPackageRule, PackageRuleTypeChoices,
    TicketType, Ticket, TicketScopeChoices, TicketStatusChoices,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
)
from apps.events.models import Event
from apps.common.models import VerificationStatus
from apps.common.api.serializers import AvailabilityWindowSerializer

User = get_user_model()


# ============================================================================
# UTILITY FUNCTIONS FOR TIMEZONE HANDLING
# ============================================================================

def localize_datetime_to_event_timezone(dt, event):
    """Convert datetime to event's timezone."""
    if not dt:
        return None
    
    if not event or not hasattr(event, 'settings'):
        return dt
    
    # Get event timezone from settings
    event_tz_str = event.settings.default_timezone if hasattr(event, 'settings') else 'UTC'
    event_tz = pytz.timezone(str(event_tz_str))
    
    # If datetime is naive, make it aware in UTC first
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    
    # Convert to event timezone
    return dt.astimezone(event_tz)


class EventTimezoneField(serializers.DateTimeField):
    """Custom datetime field that returns datetimes in event timezone."""
    
    def to_representation(self, value):
        """Convert datetime to event timezone for serialization."""
        if not value:
            return None
        
        # Get event from context
        event = self.context.get('event')
        if event:
            value = localize_datetime_to_event_timezone(value, event)
        
        return super().to_representation(value)


# ============================================================================
# BOOKING INTENT SERIALIZERS
# ============================================================================

class BookingIntentListSerializer(serializers.ModelSerializer):
    """List serializer for BookingIntent with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    made_by_name = serializers.CharField(source='made_by.username', read_only=True, allow_null=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    created_at = EventTimezoneField(read_only=True)
    expires_at = EventTimezoneField(read_only=True)
    
    class Meta:
        model = BookingIntent
        fields = [
            'booking_intent_id', 'event', 'event_name', 'intended_ticket_count',
            'status', 'status_display', 'made_by', 'made_by_name',
            'created_at', 'expires_at', 'is_expired', 'is_active', '_links'
        ]
        read_only_fields = [
            'booking_intent_id', 'status', 'made_by', 'created_at',
            'expires_at', 'is_expired', 'is_active'
        ]
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'made_by': {'type': 'string', 'format': 'uri'},
            'cancel': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj):
        """Generate HATEOAS links for the booking intent."""
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f'/api/bookings/intents/{obj.booking_intent_id}/'
            ),
            'event': request.build_absolute_uri(
                f'/api/events/{obj.event.event_id}/'
            ),
        }
        
        if obj.made_by:
            links['made_by'] = request.build_absolute_uri(
                f'/api/users/{obj.made_by.id}/'
            )
        
        # Add cancel link if intent is still active
        if obj.is_active:
            links['cancel'] = request.build_absolute_uri(
                f'/api/bookings/intents/{obj.booking_intent_id}/cancel/'
            )
        
        return links


class BookingIntentDetailSerializer(BookingIntentListSerializer):
    """Detailed serializer for BookingIntent with full information."""
    
    complete_delete_at = EventTimezoneField(read_only=True)
    can_create_booking = serializers.SerializerMethodField()
    
    class Meta(BookingIntentListSerializer.Meta):
        fields = BookingIntentListSerializer.Meta.fields + ['complete_delete_at', 'can_create_booking']
    
    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_create_booking(self, obj):
        """Check if a booking can be created from this intent."""
        return obj.can_create_booking()


class BookingIntentCreateSerializer(serializers.ModelSerializer):
    """Create serializer for BookingIntent with validation."""
    
    event = serializers.SlugRelatedField(
        slug_field='event_id',
        queryset=Event.objects.all(),
        write_only=True
    )
    is_active = serializers.BooleanField(read_only=True)
    event_id = serializers.CharField(source='event.event_id', read_only=True)
    
    class Meta:
        model = BookingIntent
        fields = ['booking_intent_id', 'event', 'event_id', 'intended_ticket_count', 'status', 'is_active']
    
    def validate_event(self, value):
        """Validate the event exists and is open for registration."""
        if value.max_capacity_reached:
            raise serializers.ValidationError(
                "This event has reached its maximum capacity."
            )
        if not value.can_participants_register:
            raise serializers.ValidationError(
                "This event is not currently open for registration."
            )
        return value
    
    def validate_intended_ticket_count(self, value):
        """Validate ticket count is positive."""
        if value < 1:
            raise serializers.ValidationError(
                "Intended ticket count must be at least 1."
            )
        if value > 20:  # Reasonable max to prevent abuse
            raise serializers.ValidationError(
                "Cannot create intent for more than 20 tickets at once."
            )
        return value
    
    def validate(self, attrs):
        """Validate overall capacity availability."""
        event = attrs.get('event')
        intended_count = attrs.get('intended_ticket_count', 1)
        
        # Check if capacity is available (considering pending intents)
        from django.db.models import Sum
        pending_intents = BookingIntent.objects.filter(
            event=event,
            status=BookingIntentStatusChoices.PENDING,
            expires_at__gt=timezone.now()
        )
        
        reserved_by_intents = pending_intents.aggregate(
            total=Sum('intended_ticket_count')
        )['total'] or 0
        
        if event.maximum_attendance is not None:
            available_capacity = event.maximum_attendance - event.number_of_attendees - reserved_by_intents
        
            if available_capacity < intended_count:
                raise serializers.ValidationError({
                    'intended_ticket_count': f'Insufficient capacity. Only {available_capacity} spots available.'
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create a booking intent with the authenticated user."""
        validated_data['made_by'] = self.context['request'].user
        validated_data['status'] = BookingIntentStatusChoices.PENDING
        return super().create(validated_data)


class BookingIntentUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for BookingIntent (limited fields)."""
    
    class Meta:
        model = BookingIntent
        fields = ['intended_ticket_count']
    
    def validate(self, attrs):
        """Only allow updates to pending intents."""
        if self.instance.status != BookingIntentStatusChoices.PENDING:
            raise serializers.ValidationError(
                "Cannot update a non-pending booking intent."
            )
        
        if self.instance.is_expired:
            raise serializers.ValidationError(
                "Cannot update an expired booking intent."
            )
        
        # If updating ticket count, revalidate capacity
        if 'intended_ticket_count' in attrs:
            new_count = attrs['intended_ticket_count']
            old_count = self.instance.intended_ticket_count
            difference = new_count - old_count
            
            if difference > 0:
                # Need more capacity
                from django.db.models import Sum
                pending_intents = BookingIntent.objects.filter(
                    event=self.instance.event,
                    status=BookingIntentStatusChoices.PENDING,
                    expires_at__gt=timezone.now()
                ).exclude(booking_intent_id=self.instance.booking_intent_id)
                
                reserved_by_intents = pending_intents.aggregate(
                    total=Sum('intended_ticket_count')
                )['total'] or 0
                if self.instance.event.maximum_attendance is not None:
                    available_capacity = (
                        self.instance.event.maximum_attendance - 
                        self.instance.event.number_of_attendees - 
                        reserved_by_intents
                    )
                
                    if available_capacity < new_count:
                        raise serializers.ValidationError({
                            'intended_ticket_count': f'Insufficient capacity. Only {available_capacity} spots available.'
                        })
        
        return attrs


# ============================================================================
# TICKET TYPE SERIALIZERS
# ============================================================================

class TicketTypeListSerializer(serializers.ModelSerializer):
    """List serializer for TicketType with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    scope_display = serializers.CharField(source='get_scope_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    valid_from = EventTimezoneField(read_only=True)
    valid_until = EventTimezoneField(read_only=True)
    
    class Meta:
        model = TicketType
        fields = (
            'id', 'code', 'title', 'event', 'event_name', 'scope', 'scope_display',
            'valid_from', 'valid_until', 'is_active', 'created_by', 'created_by_name',
            'created_at', '_links'
        )
        read_only_fields = ('id', 'code', 'created_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'created_by': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/bookings/ticket-types/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/")
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(f"/api/users/{obj.created_by.id}/")
        
        return links


class TicketTypeDetailSerializer(TicketTypeListSerializer):
    """Detailed serializer for TicketType with full information."""
    
    booking_packages = serializers.SerializerMethodField()
    ticket_count = serializers.SerializerMethodField()
    
    class Meta(TicketTypeListSerializer.Meta):
        fields = TicketTypeListSerializer.Meta.fields + (
            'max_entries', 'updated_at', 'booking_packages', 'ticket_count'
        )
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_ticket_count(self, obj) -> int:
        """Return count of tickets issued for this type."""
        return obj.tickets.count()
    
    @extend_schema_field({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'id': {'type': 'integer'},
                'name': {'type': 'string'},
                'url': {'type': 'string', 'format': 'uri'},
            }
        }
    })
    def get_booking_packages(self, obj) -> list:
        """Return list of booking packages for this ticket type."""
        request = self.context.get('request')
        packages = []
        
        for package in obj.booking_packages.filter(is_active=True):
            pkg_data = {
                'id': package.id,
                'name': package.name,
            }
            if request:
                pkg_data['url'] = request.build_absolute_uri(f"/api/bookings/packages/{package.id}/")
            packages.append(pkg_data)
        
        return packages


class TicketTypeCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for TicketType with validation."""
    
    class Meta:
        model = TicketType
        fields = (
            'title', 'event', 'scope', 'valid_from', 'valid_until',
            'is_active', 'max_entries'
        )
    
    def validate_event(self, value):
        """Ensure event exists and is accessible."""
        if not value:
            raise serializers.ValidationError("Event is required.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        valid_from = attrs.get('valid_from')
        valid_until = attrs.get('valid_until')
        
        if valid_from and valid_until and valid_from >= valid_until:
            raise serializers.ValidationError({
                'valid_until': 'Valid until date must be after valid from date.'
            })
        
        return attrs
    
    def create(self, validated_data):
        """Create ticket type with auto-generated code."""
        # Code is generated automatically in the model's save method
        return super().create(validated_data)


# ============================================================================
# TICKET SERIALIZERS
# ============================================================================

class TicketListSerializer(serializers.ModelSerializer):
    """List serializer for Ticket with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    ticket_type_title = serializers.CharField(source='ticket_type.title', read_only=True)
    package_name = serializers.CharField(source='package.name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    status = serializers.ChoiceField(choices=TicketStatusChoices.choices, read_only=True)
    issued_at = EventTimezoneField(read_only=True)
    
    class Meta:
        model = Ticket
        fields = (
            'ticket_id', 'ticket_code', 'attendee', 'attendee_name',
            'ticket_type', 'ticket_type_title', 'package', 'package_name',
            'status', 'status_display', 'issued_at', 'uses', '_links'
        )
        read_only_fields = ('ticket_id', 'ticket_code', 'issued_at', 'status')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'ticket_type': {'type': 'string', 'format': 'uri'},
            'package': {'type': 'string', 'format': 'uri'},
            'payment': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/bookings/tickets/{obj.ticket_id}/"),
            'attendee': request.build_absolute_uri(f"/api/attendees/{obj.attendee.attendee_id}/"),
            'ticket_type': request.build_absolute_uri(f"/api/bookings/ticket-types/{obj.ticket_type.id}/"),
        }
        
        if obj.package:
            links['package'] = request.build_absolute_uri(f"/api/bookings/packages/{obj.package.id}/")
        
        if obj.payment:
            links['payment'] = request.build_absolute_uri(f"/api/payments/list/{obj.payment.payment_id}/")
        
        return links


class TicketDetailSerializer(TicketListSerializer):
    """Detailed serializer for Ticket with full information."""
    
    booking_reference = serializers.CharField(source='attendee.booking.booking_reference', read_only=True, allow_null=True)
    
    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + ('booking_reference',)


# ============================================================================
# BOOKING PACKAGE RULE SERIALIZERS
# ============================================================================

class BookingPackageRuleSerializer(serializers.ModelSerializer):
    """Serializer for BookingPackageRule (nested in package)."""
    
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = BookingPackageRule
        fields = (
            'rule_id', 'rule_type', 'rule_type_display', 'name', 'description',
            'value', 'active', 'added_by', 'added_by_name', 'created_at', 'updated_at'
        )
        read_only_fields = ('rule_id', 'created_at', 'updated_at')


class BookingPackageRuleCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for BookingPackageRule with validation."""
    
    class Meta:
        model = BookingPackageRule
        fields = ('rule_type', 'name', 'description', 'value', 'active')
    
    def validate(self, attrs):
        """Validate rule configuration."""
        rule_type = attrs.get('rule_type')
        value = attrs.get('value')
        
        # Rules that require a value
        rules_requiring_value = [
            PackageRuleTypeChoices.IS_AGE_LT,
            PackageRuleTypeChoices.IS_AGE_GT,
            PackageRuleTypeChoices.ORGANISATION_MATCHES,
            PackageRuleTypeChoices.VALUE_MATCHES,
            PackageRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES,
            PackageRuleTypeChoices.NAME_MATCHES,
            PackageRuleTypeChoices.LOCATION_MATCHES,
            PackageRuleTypeChoices.CODE_MATCHES,
        ]
        
        if rule_type in rules_requiring_value and not value:
            raise serializers.ValidationError({
                'value': f"Rule type {rule_type} requires a value."
            })
        
        # Age rules must have integer values
        if rule_type in [PackageRuleTypeChoices.IS_AGE_GT, PackageRuleTypeChoices.IS_AGE_LT]:
            try:
                int(value)
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    'value': f"Rule type {rule_type} requires an integer value."
                })
        
        return attrs


# ============================================================================
# BOOKING PACKAGE SERIALIZERS
# ============================================================================

class BookingPackageListSerializer(serializers.ModelSerializer):
    """List serializer for BookingPackage with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    ticket_type_title = serializers.CharField(source='ticket_type.title', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    base_amount = MoneyField(max_digits=10, decimal_places=2, read_only=True)
    modified_amount = MoneyField(max_digits=10, decimal_places=2, read_only=True)
    availability_windows = AvailabilityWindowSerializer(many=True, read_only=True)
    
    class Meta:
        model = BookingPackage
        fields = (
            'id','name', 'event', 'event_name', 'ticket_type', 'ticket_type_title','description',
            'base_amount', 'base_amount_currency', 'percentage_modifier', 'modified_amount', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'availability_windows', '_links'
        )
        read_only_fields = ('id', 'created_at', 'modified_amount')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'ticket_type': {'type': 'string', 'format': 'uri'},
            'created_by': {'type': 'string', 'format': 'uri'},
            'rules': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/bookings/packages/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
            'ticket_type': request.build_absolute_uri(f"/api/bookings/ticket-types/{obj.ticket_type.id}/"),
            'rules': request.build_absolute_uri(f"/api/bookings/packages/{obj.id}/rules/"),
            'availability_windows': request.build_absolute_uri(f"/api/bookings/packages/{obj.id}/availability-windows/"),
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(f"/api/users/{obj.created_by.id}/")
        
        return links


class BookingPackageDetailSerializer(BookingPackageListSerializer):
    """Detailed serializer for BookingPackage with nested rules and availability windows."""
    
    rules = BookingPackageRuleSerializer(many=True, read_only=True)
    ticket_count = serializers.SerializerMethodField()
    
    class Meta(BookingPackageListSerializer.Meta):
        fields = BookingPackageListSerializer.Meta.fields + (
            'description', 'updated_at', 'rules', 'ticket_count'
        )
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_ticket_count(self, obj) -> int:
        """Return count of tickets using this package."""
        return obj.tickets.count()


class BookingPackageCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for BookingPackage with validation."""
    
    rules = BookingPackageRuleCreateUpdateSerializer(many=True, required=False)
    
    class Meta:
        model = BookingPackage
        fields = (
            'name', 'description', 'event', 'ticket_type',
            'base_amount', 'percentage_modifier', 'is_active', 'rules'
        )
    
    def validate_event(self, value):
        """Ensure event exists."""
        if not value:
            raise serializers.ValidationError("Event is required.")
        return value
    
    def validate_ticket_type(self, value):
        """Ensure ticket type exists."""
        if not value:
            raise serializers.ValidationError("Ticket type is required.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        ticket_type = attrs.get('ticket_type') or (self.instance.ticket_type if self.instance else None)
        event = attrs.get('event') or (self.instance.event if self.instance else None)
        
        if ticket_type and event and ticket_type.event_id != event.id:
            raise serializers.ValidationError({
                'ticket_type': 'Ticket type must belong to the same event as the booking package.'
            })
        
        return attrs
    
    def create(self, validated_data):
        """Create booking package with nested rules."""
        rules_data = validated_data.pop('rules', [])
        
        # Set created_by from request user
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        
        package = BookingPackage.objects.create(**validated_data)
        
        # Create rules
        for rule_data in rules_data:
            if request and request.user:
                rule_data['added_by'] = request.user
            BookingPackageRule.objects.create(booking_package=package, **rule_data)
        
        return package
    
    def update(self, instance, validated_data):
        """Update booking package and optionally update rules."""
        rules_data = validated_data.pop('rules', None)
        
        # Update package fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # If rules data provided, replace existing rules
        if rules_data is not None:
            instance.rules.all().delete()
            request = self.context.get('request')
            for rule_data in rules_data:
                if request and request.user:
                    rule_data['added_by'] = request.user
                BookingPackageRule.objects.create(booking_package=instance, **rule_data)
        
        return instance


# ============================================================================
# BOOKING SERIALIZERS
# ============================================================================

class BookingListSerializer(serializers.ModelSerializer):
    """List serializer for Booking with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    made_by_name = serializers.CharField(source='made_by.username', read_only=True, allow_null=True)
    attendee_count = serializers.SerializerMethodField()
    booked_at = EventTimezoneField(read_only=True)
    
    class Meta:
        model = Booking
        fields = (
            'id', 'booking_reference', 'event', 'event_name',
            'made_by', 'made_by_name', 'attendee_count', 'booked_at', '_links'
        )
        read_only_fields = ('id', 'booking_reference', 'booked_at')
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_attendee_count(self, obj) -> int:
        """Return count of attendees in this booking."""
        return obj.attendees.count()
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'made_by': {'type': 'string', 'format': 'uri'},
            'attendees': {'type': 'string', 'format': 'uri'},
            'tickets': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/bookings/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
            'attendees': request.build_absolute_uri(f"/api/bookings/{obj.id}/attendees/"),
            'tickets': request.build_absolute_uri(f"/api/bookings/{obj.id}/tickets/"),
        }
        
        if obj.made_by:
            links['made_by'] = request.build_absolute_uri(f"/api/users/{obj.made_by.id}/")
        
        return links


class BookingDetailSerializer(BookingListSerializer):
    """Detailed serializer for Booking with metadata."""
    
    attendees = serializers.SerializerMethodField()
    tickets = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    
    class Meta(BookingListSerializer.Meta):
        fields = BookingListSerializer.Meta.fields + ('attendees', 'tickets', 'payments')
    
    @extend_schema_field({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'id': {'type': 'string', 'format': 'uuid'},
                'display_id': {'type': 'string'},
                'name': {'type': 'string'},
                'url': {'type': 'string', 'format': 'uri'},
            }
        }
    })
    def get_attendees(self, obj) -> list:
        """Return list of attendees with links."""
        request = self.context.get('request')
        attendees = []
        
        for attendee in obj.attendees.all():
            attendee_data = {
                'id': str(attendee.attendee_id),
                'display_id': attendee.attendee_display_id,
                'name': attendee.full_name,
            }
            if request:
                attendee_data['url'] = request.build_absolute_uri(f"/api/attendees/{attendee.attendee_id}/")
            attendees.append(attendee_data)
        
        return attendees
    
    @extend_schema_field({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'ticket_id': {'type': 'string', 'format': 'uuid'},
                'ticket_code': {'type': 'string'},
                'attendee_name': {'type': 'string'},
                'status': {'type': 'string'},
                'url': {'type': 'string', 'format': 'uri'},
            }
        }
    })
    def get_tickets(self, obj) -> list:
        """Return list of tickets with links."""
        request = self.context.get('request')
        tickets = []
        
        for attendee in obj.attendees.all():
            for ticket in attendee.tickets.all():
                ticket_data = {
                    'ticket_id': str(ticket.ticket_id),
                    'ticket_code': ticket.ticket_code,
                    'attendee_name': attendee.full_name,
                    'status': ticket.status,
                }
                if request:
                    ticket_data['url'] = request.build_absolute_uri(f"/api/bookings/tickets/{ticket.ticket_id}/")
                tickets.append(ticket_data)
        
        return tickets
    
    @extend_schema_field({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'payment_id': {'type': 'string', 'format': 'uuid'},
                'payment_reference': {'type': 'string'},
                'status': {'type': 'string'},
                'amount': {'type': 'string'},
                'url': {'type': 'string', 'format': 'uri'},
            }
        }
    })
    def get_payments(self, obj) -> list:
        """Return list of associated payments with links."""
        request = self.context.get('request')
        payments = []
        
        # Get payments through the PaymentMixin
        for payment in obj.payments.all():
            payment_data = {
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'status': payment.status,
                'amount': str(payment.modified_amount),
            }
            if request:
                payment_data['url'] = request.build_absolute_uri(f"/api/payments/list/{payment.payment_id}/")
            payments.append(payment_data)
        
        return payments


class BookingCreateSerializer(serializers.ModelSerializer):
    """Create serializer for Booking with validation."""

    booking_reference = serializers.CharField(read_only=True, help_text="Auto-generated booking reference.")
    event = serializers.PrimaryKeyRelatedField(
        queryset=Event.objects.all(),
        required=False,
        allow_null=True,
        help_text="Event for the booking. Not required when using a booking intent (event will be inferred from intent)."
    )
    
    class Meta:
        model = Booking
        fields = ('event', 'booking_reference')
    
    def validate_event(self, value):
        """Ensure event exists and is accessible (if provided)."""
        # Event can be null here - it will be validated and set in the viewset
        return value
    
    def create(self, validated_data):
        """Create booking with auto-generated reference."""
        from core.utils.display import generate_human_readable_id
        
        # Set made_by from request user
        request = self.context.get('request')
        if request and request.user:
            validated_data['made_by'] = request.user
        
        # Generate booking reference
        event = validated_data['event']
        validated_data['booking_reference'] = generate_human_readable_id(
            50, 'BKG', event.display_code[:10]
        )
        
        return Booking.objects.create(**validated_data)


class BookingUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for Booking (limited fields)."""
    
    class Meta:
        model = Booking
        fields = []  # Bookings are mostly immutable after creation
    
    def update(self, instance, validated_data):
        """Minimal update support - bookings are mostly immutable."""
        return instance


# ============================================================================
# ALTERNATIVE SIGNIN IDENTIFIER SERIALIZERS
# ============================================================================

class EventAlternativeSigninListSerializer(serializers.ModelSerializer):
    """List serializer for EventAlternativeSigninIdentifier with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.title', read_only=True)
    verification_status_display = serializers.CharField(source='get_verification_status_display', read_only=True)
    
    class Meta:
        model = EventAlternativeSigninIdentifier
        fields = (
            'id', 'title', 'event', 'event_name', 'is_active',
            'format_match', 'description',
            'verification_status', 'verification_status_display',
            'max_uses_per_signin', 'created_at', '_links'
        )
        read_only_fields = ('id', 'created_at')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/bookings/alternative-signins/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
        }


class EventAlternativeSigninDetailSerializer(EventAlternativeSigninListSerializer):
    """Detailed serializer for EventAlternativeSigninIdentifier."""
    
    verified_by_name = serializers.CharField(source='verified_by.username', read_only=True, allow_null=True)
    processed_by_name = serializers.CharField(source='processed_by.username', read_only=True, allow_null=True)
    
    class Meta(EventAlternativeSigninListSerializer.Meta):
        fields = EventAlternativeSigninListSerializer.Meta.fields + (
            'description', 'format_match', 'verified_by', 'verified_by_name',
            'verified_updated_at', 'processed_by', 'processed_by_name',
            'processed_at', 'auto_processed', 'updated_at'
        )


class EventAlternativeSigninCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for EventAlternativeSigninIdentifier with validation."""
    
    class Meta:
        model = EventAlternativeSigninIdentifier
        fields = (
            'title', 'description', 'event', 'format_match',
            'max_uses_per_signin', 'is_active'
        )
    
    def validate_event(self, value):
        """Ensure event exists."""
        if not value:
            raise serializers.ValidationError("Event is required.")
        return value
    
    def validate_format_match(self, value):
        """Validate regex pattern if provided."""
        if value:
            import re
            try:
                re.compile(value)
            except re.error as e:
                raise serializers.ValidationError(f"Invalid regex pattern: {e}")
        return value


class AttendeeAlternativeSigninListSerializer(serializers.ModelSerializer):
    """List serializer for AttendeeAlternativeSigninIdentifier with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    attendee_name = serializers.CharField(source='attendee.full_name', read_only=True)
    event_alternative_signin_title = serializers.CharField(source='event_alternative_signin.title', read_only=True)
    ticket_code = serializers.CharField(source='ticket.ticket_code', read_only=True, allow_null=True)
    defined_by_name = serializers.CharField(source='defined_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = AttendeeAlternativeSigninIdentifier
        fields = (
            'sign_id', 'attendee', 'attendee_name', 'ticket', 'ticket_code',
            'identifier', 'event_alternative_signin', 'event_alternative_signin_title',
            'uses', 'defined_by', 'defined_by_name', 'defined_at', '_links'
        )
        read_only_fields = ('sign_id', 'defined_at', 'uses')
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'attendee': {'type': 'string', 'format': 'uri'},
            'ticket': {'type': 'string', 'format': 'uri'},
            'event_alternative_signin': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/bookings/attendee-alternative-signins/{obj.sign_id}/"),
            'attendee': request.build_absolute_uri(f"/api/attendees/{obj.attendee.attendee_id}/"),
            'event_alternative_signin': request.build_absolute_uri(f"/api/bookings/alternative-signins/{obj.event_alternative_signin.id}/"),
        }
        
        if obj.ticket:
            links['ticket'] = request.build_absolute_uri(f"/api/bookings/tickets/{obj.ticket.ticket_id}/")
        
        return links


class AttendeeAlternativeSigninDetailSerializer(AttendeeAlternativeSigninListSerializer):
    """Detailed serializer for AttendeeAlternativeSigninIdentifier."""
    
    class Meta(AttendeeAlternativeSigninListSerializer.Meta):
        fields = AttendeeAlternativeSigninListSerializer.Meta.fields + ('updated_at',)


class AttendeeAlternativeSigninCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for AttendeeAlternativeSigninIdentifier with validation."""
    
    class Meta:
        model = AttendeeAlternativeSigninIdentifier
        fields = (
            'attendee', 'ticket', 'identifier', 'event_alternative_signin'
        )
    
    def validate(self, attrs):
        """Cross-field validation."""
        attendee = attrs.get('attendee')
        ticket = attrs.get('ticket')
        event_alternative_signin = attrs.get('event_alternative_signin')
        identifier = attrs.get('identifier', '').strip()
        
        if not identifier:
            raise serializers.ValidationError({
                'identifier': 'Identifier cannot be empty.'
            })
        
        # Validate format match
        if event_alternative_signin and not event_alternative_signin.validate_code_format(identifier):
            raise serializers.ValidationError({
                'identifier': 'Identifier does not match the required format.'
            })
        
        # Validate ticket and event match
        if ticket and event_alternative_signin:
            if event_alternative_signin.event_id != ticket.attendee.event_id:
                raise serializers.ValidationError({
                    'event_alternative_signin': 'The event alternative sign-in identifier must belong to the same event as the ticket.'
                })
            
            if ticket.attendee_id != attendee.pk:
                raise serializers.ValidationError({
                    'ticket': 'The ticket must belong to the same attendee.'
                })
        
        # Check if event alternative signin is active
        if event_alternative_signin and not event_alternative_signin.is_valid:
            raise serializers.ValidationError({
                'event_alternative_signin': 'The event alternative sign-in identifier is not active.'
            })
        
        return attrs
    
    def create(self, validated_data):
        """Create attendee alternative signin with defined_by."""
        request = self.context.get('request')
        if request and request.user:
            validated_data['defined_by'] = request.user
        
        return AttendeeAlternativeSigninIdentifier.objects.create(**validated_data)


# ============================================================================
# CHECKOUT SERIALIZERS
# ============================================================================

class ProductSelectionSerializer(serializers.Serializer):
    """Serializer for product variant selection within a package."""
    
    package_product_id = serializers.IntegerField(
        help_text="ID of the PackageProduct this selection is for"
    )
    variant_id = serializers.UUIDField(
        help_text="UUID of the ProductVariant being selected"
    )
    quantity = serializers.IntegerField(
        min_value=1,
        default=1,
        help_text="Quantity to order (must not exceed package_product.quantity_per_attendee)"
    )
    
    def validate(self, attrs):
        """Validate that quantity doesn't exceed package limits."""
        from apps.bookings.models import PackageProduct
        from apps.products.models import ProductVariant
        
        package_product_id = attrs.get('package_product_id')
        variant_id = attrs.get('variant_id')
        quantity = attrs.get('quantity')
        
        # Validate PackageProduct exists
        try:
            package_product = PackageProduct.objects.get(id=package_product_id)
        except PackageProduct.DoesNotExist:
            raise serializers.ValidationError({
                'package_product_id': f'PackageProduct with id {package_product_id} does not exist.'
            })
        
        # Validate ProductVariant exists and belongs to the product
        try:
            variant = ProductVariant.objects.get(variant_id=variant_id)
        except ProductVariant.DoesNotExist:
            raise serializers.ValidationError({
                'variant_id': f'ProductVariant with id {variant_id} does not exist.'
            })
        
        if variant.product_id != package_product.product_id:
            raise serializers.ValidationError({
                'variant_id': f'Variant does not belong to product {package_product.product.title}'
            })
        
        # Strict enforcement: quantity must not exceed package limit
        if quantity > package_product.quantity_per_attendee:
            raise serializers.ValidationError({
                'quantity': (
                    f'Quantity {quantity} exceeds package limit of '
                    f'{package_product.quantity_per_attendee}. '
                    'To order more, place a separate order after checkout.'
                )
            })
        
        # Store validated objects for later use
        attrs['_package_product'] = package_product
        attrs['_variant'] = variant
        
        return attrs


class AttendeeCheckoutSerializer(serializers.Serializer):
    """Serializer for a single attendee's package and product selections."""
    
    attendee_id = serializers.UUIDField(
        help_text="UUID of the attendee this selection is for"
    )
    package_id = serializers.IntegerField(
        help_text="ID of the BookingPackage selected for this attendee"
    )
    product_selections = ProductSelectionSerializer(
        many=True,
        required=False,
        help_text="Optional product variant selections for package products"
    )
    
    def validate(self, attrs):
        """Validate attendee and package compatibility."""
        from apps.attendee.models import Attendee
        from apps.bookings.models import BookingPackage
        
        attendee_id = attrs.get('attendee_id')
        package_id = attrs.get('package_id')
        product_selections = attrs.get('product_selections', [])
        
        # Validate Attendee exists
        try:
            attendee = Attendee.objects.get(attendee_id=attendee_id)
        except Attendee.DoesNotExist:
            raise serializers.ValidationError({
                'attendee_id': f'Attendee with id {attendee_id} does not exist.'
            })
        
        # Validate BookingPackage exists and belongs to same event
        try:
            package = BookingPackage.objects.get(id=package_id)
        except BookingPackage.DoesNotExist:
            raise serializers.ValidationError({
                'package_id': f'BookingPackage with id {package_id} does not exist.'
            })
        
        if package.event_id != attendee.event_id:
            raise serializers.ValidationError({
                'package_id': 'Package must belong to the same event as the attendee.'
            })
        
        # Validate product selections match package products
        if product_selections:
            package_product_ids = set(ps['package_product_id'] for ps in product_selections)
            actual_package_products = package.package_products.values_list('id', flat=True)
            
            invalid_ids = package_product_ids - set(actual_package_products)
            if invalid_ids:
                raise serializers.ValidationError({
                    'product_selections': f'PackageProduct IDs {invalid_ids} do not belong to package {package.name}'
                })
        
        # Store validated objects
        attrs['_attendee'] = attendee
        attrs['_package'] = package
        
        return attrs


class CheckoutSerializer(serializers.Serializer):
    """
    Checkout serializer for creating bookings with payments.
    
    This serializer:
    1. Accepts booking intent ID, payment method, and attendee selections
    2. Validates all data comprehensively
    3. Does NOT accept prices from frontend (backend calculates all)
    4. Returns booking, payment, orders, and tickets (or client_secret for Stripe)
    """
    
    booking_intent_id = serializers.UUIDField(
        help_text="UUID of the BookingIntent to complete"
    )
    payment_method_id = serializers.IntegerField(
        help_text="ID of the PaymentMethod to use"
    )
    attendees = AttendeeCheckoutSerializer(
        many=True,
        help_text="List of attendee selections with packages and products"
    )
    
    def validate_booking_intent_id(self, value):
        """Validate booking intent exists and is active."""
        try:
            # Don't use select_for_update here - will be locked in viewset
            intent = BookingIntent.objects.get(booking_intent_id=value)
        except BookingIntent.DoesNotExist:
            raise serializers.ValidationError(
                f'BookingIntent with id {value} does not exist.'
            )
        
        if not intent.is_active:
            raise serializers.ValidationError(
                f'BookingIntent {value} is not active. Status: {intent.status}, '
                f'Expired: {intent.is_expired}'
            )
        
        if not intent.can_create_booking():
            raise serializers.ValidationError(
                f'Cannot create booking from intent {value}. Event may be full or closed.'
            )
        
        return value
    
    def validate_payment_method_id(self, value):
        """Validate payment method exists and is active."""
        from apps.payments.models import PaymentMethod
        
        try:
            method = PaymentMethod.objects.get(id=value)
        except PaymentMethod.DoesNotExist:
            raise serializers.ValidationError(
                f'PaymentMethod with id {value} does not exist.'
            )
        
        if not method.is_active:
            raise serializers.ValidationError(
                f'PaymentMethod {method.title} is not currently active.'
            )
        
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        intent_id = attrs.get('booking_intent_id')
        method_id = attrs.get('payment_method_id')
        attendee_selections = attrs.get('attendees', [])
        
        # Get intent and payment method
        intent = BookingIntent.objects.get(booking_intent_id=intent_id)
        from apps.payments.models import PaymentMethod
        payment_method = PaymentMethod.objects.get(id=method_id)
        
        # Validate payment method belongs to same event
        if payment_method.event_id != intent.event_id:
            raise serializers.ValidationError({
                'payment_method_id': 'Payment method must belong to the same event as the booking intent.'
            })
        
        # Validate attendee count matches intent
        if len(attendee_selections) != intent.intended_ticket_count:
            raise serializers.ValidationError({
                'attendees': (
                    f'Expected {intent.intended_ticket_count} attendees based on booking intent, '
                    f'but received {len(attendee_selections)} selections.'
                )
            })
        
        # Validate all attendees belong to the same event
        event_ids = set(selection['_attendee'].event_id for selection in attendee_selections)
        if len(event_ids) > 1:
            raise serializers.ValidationError({
                'attendees': 'All attendees must belong to the same event.'
            })
        
        if event_ids and list(event_ids)[0] != intent.event_id:
            raise serializers.ValidationError({
                'attendees': 'Attendees must belong to the same event as the booking intent.'
            })
        
        # Store validated objects for processing
        attrs['_intent'] = intent
        attrs['_payment_method'] = payment_method
        
        return attrs
