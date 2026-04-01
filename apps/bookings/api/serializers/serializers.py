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
    BookingPackage, BookingPackageRule, PackageProduct, PackageRuleTypeChoices,
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

        # expire all existing pending intents for this user and event to prevent duplicates
        BookingIntent.objects.filter(
            event=validated_data['event'],
            made_by=validated_data['made_by'],
            status=BookingIntentStatusChoices.PENDING,
            expires_at__gt=timezone.now()
        ).update(status=BookingIntentStatusChoices.EXPIRED)

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
# BOOKING PACKAGE PRODUCT SERIALIZERS
# ============================================================================

class PackageProductSerializer(serializers.ModelSerializer):
    """Read serializer for products linked to booking packages."""

    product_title = serializers.CharField(source='product.title', read_only=True)
    product_display_code = serializers.CharField(source='product.display_code', read_only=True)
    product_public_id = serializers.UUIDField(source='product.product_id', read_only=True)
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    base_amount = serializers.SerializerMethodField()
    base_amount_currency = serializers.SerializerMethodField()
    modified_amount = serializers.SerializerMethodField()

    class Meta:
        model = PackageProduct
        fields = (
            'id',
            'booking_package',
            'product',
            'product_public_id',
            'product_display_code',
            'product_title',
            'quantity_per_attendee',
            'base_amount',
            'base_amount_currency',
            'percentage_modifier',
            'modified_amount',
            'added_at',
            'added_by',
            'added_by_name',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'booking_package',
            'base_amount',
            'base_amount_currency',
            'modified_amount',
            'added_at',
            'added_by',
            'added_by_name',
            'updated_at',
        )

    def _resolve_base_money(self, obj) -> Optional[Money]:
        """Resolve a safe base Money object for response serialization."""
        if getattr(obj, 'product', None) and getattr(obj.product, 'base_amount', None) is not None:
            return obj.product.base_amount
        return getattr(obj, 'base_amount', None)

    def get_base_amount(self, obj) -> str:
        base_money = self._resolve_base_money(obj)
        if base_money is None:
            return '0.00'
        return str(base_money.amount.quantize(Decimal('0.01')))

    def get_base_amount_currency(self, obj) -> str:
        base_money = self._resolve_base_money(obj)
        if base_money is None:
            return 'GBP'
        return base_money.currency.code

    def get_modified_amount(self, obj) -> str:
        base_money = self._resolve_base_money(obj)
        if base_money is None:
            return '0.00'

        modifier = getattr(obj, 'percentage_modifier', Decimal('0.00')) or Decimal('0.00')
        modified = base_money * (Decimal('1.00') + (modifier / Decimal('100')))
        return str(modified.amount.quantize(Decimal('0.01')))


class PackageProductCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/update serializer for booking package product links."""

    class Meta:
        model = PackageProduct
        fields = (
            'booking_package',
            'product',
            'quantity_per_attendee',
            'percentage_modifier',
        )
        extra_kwargs = {
            'booking_package': {'required': False},
        }

    def validate(self, attrs):
        booking_package = (
            self.context.get('booking_package')
            or attrs.get('booking_package')
            or (self.instance.booking_package if self.instance else None)
        )
        product = attrs.get('product') or (self.instance.product if self.instance else None)

        if booking_package is None:
            raise serializers.ValidationError({'booking_package': 'Booking package is required.'})

        if product and booking_package.event_id != product.event_id:
            raise serializers.ValidationError({
                'product': 'Product must belong to the same event as the booking package.'
            })

        return attrs

    def create(self, validated_data):
        booking_package = self.context.get('booking_package')
        if booking_package is not None:
            validated_data['booking_package'] = booking_package

        request = self.context.get('request')
        if request and request.user:
            validated_data['added_by'] = request.user

        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('booking_package', None)
        return super().update(instance, validated_data)


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
                'method': {'type': 'string'},
                'url': {'type': 'string', 'format': 'uri'},
                'description': {'type': 'string'},
                'method_id': {'type': 'string', 'format': 'uuid'},
                'method_type': {'type': 'string'},
                'method_title': {'type': 'string'},
                'bank_reference': {'type': 'string'},
            }
        }
    })
    def get_payments(self, obj) -> list:
        """Return list of associated payments with links."""
        from apps.payments.api.serializers import PaymentMethodDetailSerializer
        request = self.context.get('request')
        payments = []
        
        # Get payments through the PaymentMixin
        for payment in obj.payments.all():
            payment_data = {
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'status': payment.status,
                'amount': str(payment.modified_amount),
                'provided_details': payment.method.provided_details,
                'method_id': payment.method.method_id,
                'description': payment.description,
                'method_type': payment.method.method_type,
                'method_title': payment.method.title,
                'bank_reference': payment.bank_transfer_reference,
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

        if not variant.is_purchasable:
            raise serializers.ValidationError({
                'variant_id': f'Variant {variant_id} is not currently purchasable.'
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


class EmergencyContactDraftSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    relationship = serializers.ChoiceField(
        choices=[
            'parent', 'sibling', 'child', 'spouse', 'friend', 'other'
        ]
    )
    phone_number = serializers.CharField()
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    primary_contact = serializers.BooleanField(required=False, default=True)


class PersonalInfoItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    details = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class MedicalConditionItemSerializer(PersonalInfoItemSerializer):
    severity = serializers.ChoiceField(
        choices=['mild', 'moderate', 'severe'],
        required=False,
        allow_null=True
    )


class AttendeePersonalInfoDraftSerializer(serializers.Serializer):
    dietary_requirements = PersonalInfoItemSerializer(many=True, required=False)
    medical_conditions = MedicalConditionItemSerializer(many=True, required=False)
    accessibility_requirements = PersonalInfoItemSerializer(many=True, required=False)
    emergency_contact = EmergencyContactDraftSerializer(required=False)


class AttendeeConsentDraftSerializer(serializers.Serializer):
    consent_id = serializers.IntegerField()
    consent_given = serializers.BooleanField(default=False)


class EventQuestionAnswerDraftSerializer(serializers.Serializer):
    question_id = serializers.UUIDField()
    answer_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    selected_option_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False
    )
    upload_resource_id = serializers.IntegerField(required=False)
    upload_url = serializers.URLField(required=False)

    def validate(self, attrs):
        answer_text = attrs.get('answer_text')
        selected_option_ids = attrs.get('selected_option_ids', [])
        upload_resource_id = attrs.get('upload_resource_id')
        upload_url = attrs.get('upload_url')

        if upload_resource_id and upload_url:
            raise serializers.ValidationError(
                'Provide only one of upload_resource_id or upload_url.'
            )

        if not answer_text and not selected_option_ids and not upload_resource_id and not upload_url:
            raise serializers.ValidationError(
                'An answer, selected options, or upload reference is required.'
            )

        return attrs


class AttendeeDraftSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    date_of_birth = serializers.DateField()
    gender = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    relationship_to_user = serializers.ChoiceField(
        choices=['self', 'spouse', 'child', 'friend', 'parent', 'sibling', 'other']
    )
    area_from = serializers.IntegerField(required=True)
    personal_info = AttendeePersonalInfoDraftSerializer(required=False)
    consents = AttendeeConsentDraftSerializer(many=True, required=False)
    question_answers = EventQuestionAnswerDraftSerializer(many=True, required=False)

    def validate_area_from(self, value):
        """Ensure area_from points to an active AreaLocation."""
        from apps.locations.models import AreaLocation

        try:
            area = AreaLocation.objects.get(id=value, active=True)
        except AreaLocation.DoesNotExist:
            raise serializers.ValidationError(
                f'AreaLocation with id {value} does not exist or is not active.'
            )

        return area.id


class AttendeeCheckoutSerializer(serializers.Serializer):
    """Serializer for a single attendee's package and product selections."""

    attendee_id = serializers.UUIDField(
        required=False,
        help_text="UUID of the attendee this selection is for"
    )
    attendee = AttendeeDraftSerializer(
        required=False,
        help_text="Draft attendee data to create during checkout"
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
        attendee_draft = attrs.get('attendee')
        package_id = attrs.get('package_id')
        product_selections = attrs.get('product_selections', [])

        if bool(attendee_id) == bool(attendee_draft):
            raise serializers.ValidationError({
                'attendee_id': 'Provide either attendee_id or attendee, but not both.'
            })

        # Validate BookingPackage exists
        try:
            package = BookingPackage.objects.get(id=package_id)
        except BookingPackage.DoesNotExist:
            raise serializers.ValidationError({
                'package_id': f'BookingPackage with id {package_id} does not exist.'
            })

        if attendee_id:
            try:
                attendee = Attendee.objects.get(attendee_id=attendee_id)
            except Attendee.DoesNotExist:
                raise serializers.ValidationError({
                    'attendee_id': f'Attendee with id {attendee_id} does not exist.'
                })

            if package.event_id != attendee.event_id:
                raise serializers.ValidationError({
                    'package_id': 'Package must belong to the same event as the attendee.'
                })

            attrs['_attendee'] = attendee
        else:
            attrs['_attendee_draft'] = attendee_draft

        # Validate product selections match package products
        if product_selections:
            selected_product_ids = [ps['package_product_id'] for ps in product_selections]
            if len(selected_product_ids) != len(set(selected_product_ids)):
                raise serializers.ValidationError({
                    'product_selections': 'Duplicate package_product_id entries are not allowed.'
                })

            package_product_ids = set(ps['package_product_id'] for ps in product_selections)
            actual_package_products = package.package_products.values_list('id', flat=True)

            invalid_ids = package_product_ids - set(actual_package_products)
            if invalid_ids:
                raise serializers.ValidationError({
                    'product_selections': f'PackageProduct IDs {invalid_ids} do not belong to package {package.name}'
                })

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
    stripe_payment_intent_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Stripe PaymentIntent ID when payment is already confirmed"
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
        stripe_payment_intent_id = attrs.get('stripe_payment_intent_id')
        
        # Get intent and payment method
        intent = BookingIntent.objects.get(booking_intent_id=intent_id)
        from apps.payments.models import PaymentMethod
        payment_method = PaymentMethod.objects.get(id=method_id)
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        # Validate intent ownership for non-admin users
        if user and not user.is_staff and not user.is_superuser:
            if not intent.made_by_id or intent.made_by_id != user.id:
                raise serializers.ValidationError({
                    'booking_intent_id': 'This booking intent does not belong to the authenticated user.'
                })
        
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
        event_ids = set()
        for selection in attendee_selections:
            attendee = selection.get('_attendee')
            if attendee:
                if not attendee.area_from_id:
                    raise serializers.ValidationError({
                        'attendees': f'Attendee {attendee.attendee_id} must have area_from set.'
                    })
                event_ids.add(attendee.event_id)
            else:
                draft = selection.get('_attendee_draft') or {}
                if not draft.get('area_from'):
                    raise serializers.ValidationError({
                        'attendees': 'Each draft attendee must include area_from.'
                    })
                event_ids.add(intent.event_id)

        if len(event_ids) > 1:
            raise serializers.ValidationError({
                'attendees': 'All attendees must belong to the same event.'
            })

        if event_ids and list(event_ids)[0] != intent.event_id:
            raise serializers.ValidationError({
                'attendees': 'Attendees must belong to the same event as the booking intent.'
            })

        # Validate draft attendee details (consents/questions/uploads)
        from apps.attendee.models import Consent
        from apps.attendee.models.personal.dietary import DietaryRequirement
        from apps.attendee.models.personal.medical import MedicalCondition
        from apps.attendee.models.personal.accessibility import AccessibilityRequirement
        from apps.events.models import EventQuestion, EventQuestionTypeChoices
        from apps.common.models import Resource

        required_consent_ids = set(
            Consent.objects.filter(event=intent.event, required=True, active=True)
            .values_list('id', flat=True)
        )
        required_question_ids = set(
            EventQuestion.objects.filter(event=intent.event, required=True, public=True)
            .values_list('id', flat=True)
        )

        for selection in attendee_selections:
            draft = selection.get('_attendee_draft')
            if not draft:
                continue

            consents = draft.get('consents', [])
            consent_ids = [item['consent_id'] for item in consents]
            if len(consent_ids) != len(set(consent_ids)):
                raise serializers.ValidationError({
                    'attendees': 'Duplicate consent entries detected.'
                })

            if consent_ids:
                valid_consents = set(
                    Consent.objects.filter(event=intent.event, id__in=consent_ids)
                    .values_list('id', flat=True)
                )
                invalid_consents = set(consent_ids) - valid_consents
                if invalid_consents:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid consent IDs: {sorted(invalid_consents)}'
                    })
            consent_given_ids = {
                item['consent_id']
                for item in consents
                if item.get('consent_given') is True
            }
            missing_consents = required_consent_ids - consent_given_ids
            if missing_consents:
                raise serializers.ValidationError({
                    'attendees': f'Missing required consents: {sorted(missing_consents)}'
                })

            answers = draft.get('question_answers', [])
            question_ids = [item['question_id'] for item in answers]
            if len(question_ids) != len(set(question_ids)):
                raise serializers.ValidationError({
                    'attendees': 'Duplicate question answers detected.'
                })
            answered_question_ids = set()
            normalized_answers = []

            for answer in answers:
                question_id = answer.get('question_id')
                selected_option_ids = answer.get('selected_option_ids', [])
                upload_resource_id = answer.get('upload_resource_id')
                upload_url = answer.get('upload_url')
                answer_text = answer.get('answer_text')

                try:
                    question = EventQuestion.objects.get(id=question_id)
                except EventQuestion.DoesNotExist:
                    raise serializers.ValidationError({
                        'attendees': f'Question {question_id} does not exist.'
                    })

                if question.event_id != intent.event_id:
                    raise serializers.ValidationError({
                        'attendees': 'Question must belong to the same event as the booking intent.'
                    })

                if upload_resource_id:
                    try:
                        resource = Resource.objects.get(id=upload_resource_id)
                    except Resource.DoesNotExist:
                        raise serializers.ValidationError({
                            'attendees': f'Upload resource {upload_resource_id} does not exist.'
                        })

                    if resource.target_type.model != 'event' or str(resource.target_id) != str(intent.event_id):
                        raise serializers.ValidationError({
                            'attendees': 'Upload resource must belong to the same event.'
                        })

                    answer_text = resource.resource_url
                elif upload_url:
                    answer_text = upload_url

                if question.question_type in [
                    EventQuestionTypeChoices.SINGLE_CHOICE,
                    EventQuestionTypeChoices.MULTIPLE_CHOICE
                ]:
                    if not selected_option_ids:
                        raise serializers.ValidationError({
                            'attendees': f'Question {question_id} requires selected options.'
                        })
                    valid_option_ids = set(question.options.values_list('id', flat=True))
                    invalid_options = set(selected_option_ids) - valid_option_ids
                    if invalid_options:
                        raise serializers.ValidationError({
                            'attendees': f'Invalid option IDs {invalid_options} for question {question_id}.'
                        })
                    if question.question_type == EventQuestionTypeChoices.SINGLE_CHOICE and len(selected_option_ids) > 1:
                        raise serializers.ValidationError({
                            'attendees': f'Question {question_id} allows only one selected option.'
                        })
                else:
                    if not answer_text:
                        raise serializers.ValidationError({
                            'attendees': f'Question {question_id} requires an answer.'
                        })
                    question.validate_answer(answer_text)

                answered_question_ids.add(question_id)
                normalized_answers.append({
                    'question_id': question_id,
                    'answer_text': answer_text,
                    'selected_option_ids': selected_option_ids,
                })

            missing_questions = required_question_ids - answered_question_ids
            if missing_questions:
                raise serializers.ValidationError({
                    'attendees': f'Missing required questions: {sorted(missing_questions)}'
                })

            personal_info = draft.get('personal_info') or {}
            dietary_ids = [item['id'] for item in personal_info.get('dietary_requirements', [])]
            accessibility_ids = [item['id'] for item in personal_info.get('accessibility_requirements', [])]
            medical_ids = [item['id'] for item in personal_info.get('medical_conditions', [])]

            if dietary_ids:
                valid_dietary = set(
                    DietaryRequirement.objects.filter(active=True, id__in=dietary_ids)
                    .values_list('id', flat=True)
                )
                invalid_dietary = set(dietary_ids) - valid_dietary
                if invalid_dietary:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid dietary requirement IDs: {sorted(invalid_dietary)}'
                    })

            if accessibility_ids:
                valid_accessibility = set(
                    AccessibilityRequirement.objects.filter(active=True, id__in=accessibility_ids)
                    .values_list('id', flat=True)
                )
                invalid_accessibility = set(accessibility_ids) - valid_accessibility
                if invalid_accessibility:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid accessibility requirement IDs: {sorted(invalid_accessibility)}'
                    })

            if medical_ids:
                valid_medical = set(
                    MedicalCondition.objects.filter(active=True, id__in=medical_ids)
                    .values_list('id', flat=True)
                )
                invalid_medical = set(medical_ids) - valid_medical
                if invalid_medical:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid medical condition IDs: {sorted(invalid_medical)}'
                    })

            package = selection.get('_package')
            if package and package.event_id != intent.event_id:
                raise serializers.ValidationError({
                    'attendees': 'Package must belong to the same event as the booking intent.'
                })

            draft['question_answers'] = normalized_answers

        if stripe_payment_intent_id:
            attrs['_stripe_payment_intent_id'] = stripe_payment_intent_id
        
        # Store validated objects for processing
        attrs['_intent'] = intent
        attrs['_payment_method'] = payment_method
        
        return attrs


class CheckoutPreviewSerializer(serializers.Serializer):
    """
    Read-only checkout preview serializer.

    Mirrors checkout attendee payload but does not require a payment method.
    """

    booking_intent_id = serializers.UUIDField(
        help_text="UUID of the BookingIntent to preview"
    )
    attendees = AttendeeCheckoutSerializer(
        many=True,
        help_text="List of attendee selections with packages and products"
    )

    def validate_booking_intent_id(self, value):
        """Validate booking intent exists and is active."""
        try:
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

    def validate(self, attrs):
        """Cross-field validation."""
        intent_id = attrs.get('booking_intent_id')
        attendee_selections = attrs.get('attendees', [])

        intent = BookingIntent.objects.get(booking_intent_id=intent_id)
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if user and not user.is_staff and not user.is_superuser:
            if not intent.made_by_id or intent.made_by_id != user.id:
                raise serializers.ValidationError({
                    'booking_intent_id': 'This booking intent does not belong to the authenticated user.'
                })

        if len(attendee_selections) != intent.intended_ticket_count:
            raise serializers.ValidationError({
                'attendees': (
                    f'Expected {intent.intended_ticket_count} attendees based on booking intent, '
                    f'but received {len(attendee_selections)} selections.'
                )
            })

        event_ids = set()
        for selection in attendee_selections:
            attendee = selection.get('_attendee')
            if attendee:
                if not attendee.area_from_id:
                    raise serializers.ValidationError({
                        'attendees': f'Attendee {attendee.attendee_id} must have area_from set.'
                    })
                event_ids.add(attendee.event_id)
            else:
                draft = selection.get('_attendee_draft') or {}
                if not draft.get('area_from'):
                    raise serializers.ValidationError({
                        'attendees': 'Each draft attendee must include area_from.'
                    })
                event_ids.add(intent.event_id)

        if len(event_ids) > 1:
            raise serializers.ValidationError({
                'attendees': 'All attendees must belong to the same event.'
            })

        if event_ids and list(event_ids)[0] != intent.event_id:
            raise serializers.ValidationError({
                'attendees': 'Attendees must belong to the same event as the booking intent.'
            })

        from apps.attendee.models import Consent
        from apps.attendee.models.personal.dietary import DietaryRequirement
        from apps.attendee.models.personal.medical import MedicalCondition
        from apps.attendee.models.personal.accessibility import AccessibilityRequirement
        from apps.events.models import EventQuestion, EventQuestionTypeChoices
        from apps.common.models import Resource

        required_consent_ids = set(
            Consent.objects.filter(event=intent.event, required=True, active=True)
            .values_list('id', flat=True)
        )
        required_question_ids = set(
            EventQuestion.objects.filter(event=intent.event, required=True, public=True)
            .values_list('id', flat=True)
        )

        for selection in attendee_selections:
            draft = selection.get('_attendee_draft')
            if not draft:
                continue

            consents = draft.get('consents', [])
            consent_ids = [item['consent_id'] for item in consents]
            if len(consent_ids) != len(set(consent_ids)):
                raise serializers.ValidationError({
                    'attendees': 'Duplicate consent entries detected.'
                })

            if consent_ids:
                valid_consents = set(
                    Consent.objects.filter(event=intent.event, id__in=consent_ids)
                    .values_list('id', flat=True)
                )
                invalid_consents = set(consent_ids) - valid_consents
                if invalid_consents:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid consent IDs: {sorted(invalid_consents)}'
                    })
            consent_given_ids = {
                item['consent_id']
                for item in consents
                if item.get('consent_given') is True
            }
            missing_consents = required_consent_ids - consent_given_ids
            if missing_consents:
                raise serializers.ValidationError({
                    'attendees': f'Missing required consents: {sorted(missing_consents)}'
                })

            answers = draft.get('question_answers', [])
            question_ids = [item['question_id'] for item in answers]
            if len(question_ids) != len(set(question_ids)):
                raise serializers.ValidationError({
                    'attendees': 'Duplicate question answers detected.'
                })
            answered_question_ids = set()
            normalized_answers = []

            for answer in answers:
                question_id = answer.get('question_id')
                selected_option_ids = answer.get('selected_option_ids', [])
                upload_resource_id = answer.get('upload_resource_id')
                upload_url = answer.get('upload_url')
                answer_text = answer.get('answer_text')

                try:
                    question = EventQuestion.objects.get(id=question_id)
                except EventQuestion.DoesNotExist:
                    raise serializers.ValidationError({
                        'attendees': f'Question {question_id} does not exist.'
                    })

                if question.event_id != intent.event_id:
                    raise serializers.ValidationError({
                        'attendees': 'Question must belong to the same event as the booking intent.'
                    })

                if upload_resource_id:
                    try:
                        resource = Resource.objects.get(id=upload_resource_id)
                    except Resource.DoesNotExist:
                        raise serializers.ValidationError({
                            'attendees': f'Upload resource {upload_resource_id} does not exist.'
                        })

                    if resource.target_type.model != 'event' or str(resource.target_id) != str(intent.event_id):
                        raise serializers.ValidationError({
                            'attendees': 'Upload resource must belong to the same event.'
                        })

                    answer_text = resource.resource_url
                elif upload_url:
                    answer_text = upload_url

                if question.question_type in [
                    EventQuestionTypeChoices.SINGLE_CHOICE,
                    EventQuestionTypeChoices.MULTIPLE_CHOICE
                ]:
                    if not selected_option_ids:
                        raise serializers.ValidationError({
                            'attendees': f'Question {question_id} requires selected options.'
                        })
                    valid_option_ids = set(question.options.values_list('id', flat=True))
                    invalid_options = set(selected_option_ids) - valid_option_ids
                    if invalid_options:
                        raise serializers.ValidationError({
                            'attendees': f'Invalid option IDs {invalid_options} for question {question_id}.'
                        })
                    if question.question_type == EventQuestionTypeChoices.SINGLE_CHOICE and len(selected_option_ids) > 1:
                        raise serializers.ValidationError({
                            'attendees': f'Question {question_id} allows only one selected option.'
                        })
                else:
                    if not answer_text:
                        raise serializers.ValidationError({
                            'attendees': f'Question {question_id} requires an answer.'
                        })
                    question.validate_answer(answer_text)

                answered_question_ids.add(question_id)
                normalized_answers.append({
                    'question_id': question_id,
                    'answer_text': answer_text,
                    'selected_option_ids': selected_option_ids,
                })

            missing_questions = required_question_ids - answered_question_ids
            if missing_questions:
                raise serializers.ValidationError({
                    'attendees': f'Missing required questions: {sorted(missing_questions)}'
                })

            personal_info = draft.get('personal_info') or {}
            dietary_ids = [item['id'] for item in personal_info.get('dietary_requirements', [])]
            accessibility_ids = [item['id'] for item in personal_info.get('accessibility_requirements', [])]
            medical_ids = [item['id'] for item in personal_info.get('medical_conditions', [])]

            if dietary_ids:
                valid_dietary = set(
                    DietaryRequirement.objects.filter(active=True, id__in=dietary_ids)
                    .values_list('id', flat=True)
                )
                invalid_dietary = set(dietary_ids) - valid_dietary
                if invalid_dietary:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid dietary requirement IDs: {sorted(invalid_dietary)}'
                    })

            if accessibility_ids:
                valid_accessibility = set(
                    AccessibilityRequirement.objects.filter(active=True, id__in=accessibility_ids)
                    .values_list('id', flat=True)
                )
                invalid_accessibility = set(accessibility_ids) - valid_accessibility
                if invalid_accessibility:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid accessibility requirement IDs: {sorted(invalid_accessibility)}'
                    })

            if medical_ids:
                valid_medical = set(
                    MedicalCondition.objects.filter(active=True, id__in=medical_ids)
                    .values_list('id', flat=True)
                )
                invalid_medical = set(medical_ids) - valid_medical
                if invalid_medical:
                    raise serializers.ValidationError({
                        'attendees': f'Invalid medical condition IDs: {sorted(invalid_medical)}'
                    })

            package = selection.get('_package')
            if package and package.event_id != intent.event_id:
                raise serializers.ValidationError({
                    'attendees': 'Package must belong to the same event as the booking intent.'
                })

            draft['question_answers'] = normalized_answers

        attrs['_intent'] = intent
        return attrs
