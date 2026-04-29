"""
Production-grade serializers for the payments app.

Provides comprehensive serializers for payment management with HATEOAS support,
extensive validation, and separation of concerns (list/detail/create/update).

Serializers:
    Payment: PaymentListSerializer, PaymentDetailSerializer, PaymentCreateSerializer, PaymentUpdateSerializer
    PaymentMethod: PaymentMethodSerializer, PaymentMethodDetailSerializer, PaymentMethodCreateUpdateSerializer
    Discount: DiscountListSerializer, DiscountDetailSerializer, DiscountCreateUpdateSerializer
    DiscountRule: DiscountRuleSerializer, DiscountRuleCreateUpdateSerializer
    RefundRequest: RefundRequestListSerializer, RefundRequestDetailSerializer, RefundRequestCreateSerializer
    RefundAssociation: RefundAssociationSerializer, RefundAssociationCreateSerializer
    RefundPolicy: RefundPolicySerializer, RefundPolicyCreateUpdateSerializer
    Donation: DonationListSerializer, DonationDetailSerializer, DonationCreateSerializer
    PaymentHistoryAction: PaymentHistoryActionSerializer

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from djmoney.money import Money
from djmoney.contrib.django_rest_framework import MoneyField
from decimal import Decimal
from typing import Dict, Any, Optional
from uuid import UUID

from apps.payments.models import (
    Payment, PaymentMethod, PaymentStatusChoices, PaymentMethodTypeChoices,
    Discount, DiscountRule, DiscountType, DiscountApplicationChoices, DiscountRuleTypeChoices,
    RefundRequest, RefundAssociation, RefundPolicy, RefundPolicyTypeChoices,
    Donation, PaymentHistoryAction,
    CreditExpense, CreditExpenseTypeChoices, BankTransferEvidence
)
from apps.payments.models.stripe_accounts import StripeConnectedAccount
from apps.common.models import VerificationStatus
from apps.payments.services.attendee_refunds import AttendeeRefundService

User = get_user_model()


# ============================================================================
# PAYMENT METHOD SERIALIZERS
# ============================================================================

class PaymentMethodSerializer(serializers.ModelSerializer):
    """List serializer for PaymentMethod with HATEOAS links."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = PaymentMethod
        fields = (
            'id', 'method_id', 'code', 'title', 'method_type', 'is_active',
            'bank_transfer_required_immediately',
            'event', 'event_name', 'created_by', 'created_by_name',
            'created_at', 'updated_at', 'provided_details', '_links'
        )
        read_only_fields = ('id', 'method_id', 'code', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
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
            'self': request.build_absolute_uri(f"/api/payments/methods/{obj.method_id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/")
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(f"/api/users/{obj.created_by.id}/")
        
        return links


class PaymentMethodDetailSerializer(PaymentMethodSerializer):
    """Detailed serializer for PaymentMethod with full information."""
    
    class Meta(PaymentMethodSerializer.Meta):
        fields = PaymentMethodSerializer.Meta.fields + ('description',)


class PaymentMethodCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for PaymentMethod with validation."""
    
    class Meta:
        model = PaymentMethod
        fields = (
            'title', 'description', 'event', 'method_type',
            'provided_details', 'is_active', 'bank_transfer_required_immediately'
        )
    
    def validate_event(self, value):
        """Ensure event exists and is accessible."""
        if not value:
            raise serializers.ValidationError("Event is required.")
        return value
    
    def validate_provided_details(self, value):
        """Validate provided_details is valid JSON."""
        if value and not isinstance(value, dict):
            raise serializers.ValidationError("Provided details must be a valid JSON object.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation for payment method configuration."""
        method_type = attrs.get('method_type', self.instance.method_type if self.instance else None)
        provided_details = attrs.get('provided_details', {})
        require_immediate = attrs.get(
            'bank_transfer_required_immediately',
            self.instance.bank_transfer_required_immediately if self.instance else False,
        )
        
        # Validate bank transfer details
        if method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
            required_fields = ['account_name', 'sort_code', 'account_number']
            missing = [f for f in required_fields if f not in provided_details]
            if missing:
                raise serializers.ValidationError({
                    'provided_details': f"Bank transfer requires: {', '.join(missing)}"
                })
        
        # Validate Stripe details
        elif method_type == PaymentMethodTypeChoices.STRIPE and attrs.get('provided_details') is not None:
            stripe_acc = provided_details.get('stripe_account_id')
            if not stripe_acc:
                raise serializers.ValidationError({
                    'provided_details': "Stripe method requires 'stripe_account_id'"
                })

            # Normalize and verify the provided Stripe account exists and is usable
            stripe_acc = str(stripe_acc).strip()
            try:
                account_record = StripeConnectedAccount.objects.get(stripe_account_id=stripe_acc)
            except StripeConnectedAccount.DoesNotExist:
                raise serializers.ValidationError({
                    'provided_details': f"Stripe account '{stripe_acc}' not found. Connect the account first via the Stripe Connect flow."
                })

            request = self.context.get('request')
            if request and request.user and account_record.user_id != request.user.id:
                raise serializers.ValidationError({
                    'provided_details': f"Stripe account '{stripe_acc}' does not belong to the authenticated user."
                })

            # Ensure the connected account looks ready for payments
            if not account_record.is_ready_for_payments:
                raise serializers.ValidationError({
                    'provided_details': f"Stripe account '{stripe_acc}' is not ready for payments. Finish onboarding in Stripe."
                })

        if method_type != PaymentMethodTypeChoices.BANK_TRANSFER and require_immediate:
            raise serializers.ValidationError({
                'bank_transfer_required_immediately': 'Immediate evidence is only valid for BANK_TRANSFER methods.'
            })
        
        return attrs


# ============================================================================
# PAYMENT SERIALIZERS
# ============================================================================

class PaymentListSerializer(serializers.ModelSerializer):
    """List serializer for Payment with essential information."""
    
    _links = serializers.SerializerMethodField()
    user_name = serializers.CharField(source='user.username', read_only=True)
    event_name = serializers.CharField(source='event.name', read_only=True)
    method_title = serializers.CharField(source='method.title', read_only=True, allow_null=True)
    method = serializers.SlugRelatedField(slug_field='method_id', read_only=True)

    amount = serializers.SerializerMethodField(help_text="Final modified payment amount")
    amount_value = serializers.FloatField(source='base_amount.amount', read_only=True, help_text="Base amount as float for easier frontend handling")
    amount_currency = serializers.CharField(source='base_amount_currency', read_only=True)

    created_at = serializers.DateTimeField(read_only=True)
    descriptor = serializers.SerializerMethodField(help_text="Type of the payment target (e.g., booking, order, ticket, donation, sponsorship)")

    original_amount = serializers.SerializerMethodField(help_text="Original base amount before modifications")
    final_amount = serializers.SerializerMethodField(help_text="Final amount after percentage modifier")
    
    class Meta:
        model = Payment
        fields = (
            'id', 'payment_id', 'payment_reference', 'user', 'user_name',
            'event', 'event_name', 'method', 'method_title', 'status',
            'amount', 'amount_currency', 'created_at', '_links', 'descriptor', 'base_amount', 'amount_value',
            'bank_transfer_required_immediately', 'outstanding_bank_transfer_evidence', 'total_refunded_amount',
            'original_amount', 'final_amount',
        )
        read_only_fields = ('id', 'payment_id', 'payment_reference', 'created_at')
        extra_kwargs = {
            'created_at': {'default': None},
        }

    @extend_schema_field(OpenApiTypes.STR)
    def get_original_amount(self, obj) -> str:
        """Return the original base amount as string."""
        return str(obj.original_amount)
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_final_amount(self, obj) -> str:
        """Return the final modified amount as string."""
        return str(obj.final_amount)
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_amount(self, obj) -> str:
        """Return the modified amount as string."""
        return str(obj.base_amount)
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_descriptor(self, obj) -> Optional[str]:
        """Return the descriptor as a string if available."""
        if obj.target_type:
            ttype = str(obj.target_type.model)
            if ttype == "eventsponsor":
                return "sponsorship"
            return ttype
        if obj.metadata and 'payment_type' in obj.metadata:
            if obj.metadata['payment_type'] in ['booking_checkout_pending_finalization']:
                return 'pending booking'
        
        return None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'user': {'type': 'string', 'format': 'uri'},
            'event': {'type': 'string', 'format': 'uri'},
            'method': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(f"/api/payments/list/{obj.payment_id}/"),
            'user': request.build_absolute_uri(f"/api/users/{obj.user.id}/"),
            'event': request.build_absolute_uri(f"/api/events/{obj.event.id}/"),
        }
        
        if obj.method:
            links['method'] = request.build_absolute_uri(f"/api/payments/methods/{obj.method.id}/")
        
        return links


class PaymentDetailSerializer(PaymentListSerializer):
    """Detailed serializer for Payment with all information.
    
    Note: target_type and target_id are internal fields used for generic relations.
    They are not exposed via API for security reasons.
    """
    
    refund_requests = serializers.SerializerMethodField(help_text="Associated refund requests")
    donations = serializers.SerializerMethodField(help_text="Associated donations")
    history_actions = serializers.SerializerMethodField(help_text="Recent payment history")
    bank_transfer_evidence = serializers.SerializerMethodField(help_text="Latest bank transfer evidence summary")
    base_amount = serializers.SerializerMethodField()
    modified_amount = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta(PaymentListSerializer.Meta):
        fields = PaymentListSerializer.Meta.fields + (
            'description', 'base_amount', 'base_amount_currency', 'percentage_modifier', 'modified_amount',
            'stripe_payment_intent', 'stripe_charge_id', 'bank_transfer_reference',
            'metadata', 'refund_requests', 'donations', 'history_actions', 'bank_transfer_evidence', 'updated_at', 
        )
    
    def get_base_amount(self, obj) -> str:
        return str(obj.base_amount)
    
    def get_modified_amount(self, obj) -> str:
        return str(obj.modified_amount)
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_refund_requests(self, obj) -> list:
        """Return summary of refund requests."""
        requests = obj.refund_requests.all()[:5]  # Limit to recent 5
        return [{
            'id': str(req.refund_id),
            'amount': str(req.amount),
            'status': req.verification_status,
            'requested_at': req.requested_at.isoformat(),
        } for req in requests]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_donations(self, obj) -> list:
        """Return summary of donations."""
        donations = obj.donations.all()[:5]  # Limit to recent 5
        return [{
            'id': str(don.donation_id),
            'amount': str(don.amount),
            'status': don.verification_status,
            'donated_at': don.donated_at.isoformat(),
        } for don in donations]
    
    @extend_schema_field({'type': 'array', 'items': {'type': 'object'}})
    def get_history_actions(self, obj) -> list:
        """Return recent payment history actions."""
        actions = obj.history_actions.all()[:10]  # Limit to recent 10
        return [{
            'action': act.action,
            'description': act.description,
            'performed_by': act.performed_by.username if act.performed_by else None,
            'timestamp': act.timestamp.isoformat(),
        } for act in actions]

    @extend_schema_field({'type': 'object', 'nullable': True})
    def get_bank_transfer_evidence(self, obj):
        if not obj.method or obj.method.method_type != PaymentMethodTypeChoices.BANK_TRANSFER:
            return None

        evidence = obj.bank_transfer_evidence.order_by('-uploaded_at').first()
        if not evidence:
            return None

        evidence_file_url = None
        if evidence.evidence_file:
            request = self.context.get('request')
            evidence_file_url = evidence.evidence_file.url
            if request:
                evidence_file_url = request.build_absolute_uri(evidence_file_url)

        return {
            'bank_transfer_id': str(evidence.bank_transfer_id),
            'transfer_id': evidence.transfer_id,
            'evidence_file': evidence_file_url,
            'verification_status': evidence.verification_status,
            'uploaded_at': evidence.uploaded_at.isoformat() if evidence.uploaded_at else None,
            'auto_expiry_date': evidence.auto_expiry_date.isoformat() if evidence.auto_expiry_date else None,
        }


class PaymentCreateSerializer(serializers.ModelSerializer):
    """Create serializer for Payment with validation.
    
    Supports frontend-safe target selection fields while preserving temporary
    backward compatibility for legacy target_type + target_id payloads.
    """
    
    TARGET_CHOICES = (
        ('booking', 'Booking'),
        ('order', 'Order'),
        ('ticket', 'Ticket'),
        ('sponsorship', 'Sponsorship'),
        ('none', 'None'),
    )

    TARGET_MODEL_CONFIG = {
        'booking': ('apps.bookings.models', 'Booking', None),
        'order': ('apps.products.models', 'Order', 'order_id'),
        'ticket': ('apps.bookings.models', 'Ticket', 'ticket_id'),
        'sponsorship': ('apps.organisations.models', 'EventSponsor', 'sponsor_id'),
    }

    base_amount = MoneyField(max_digits=10, decimal_places=2)
    base_amount_currency = serializers.CharField(
        required=False,
        allow_blank=False,
        default='GBP',
        help_text="ISO 4217 currency code for base_amount (e.g., GBP, USD, EUR)."
    )
    # Frontend-safe target fields.
    target = serializers.ChoiceField(
        choices=TARGET_CHOICES,
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Payment target type: booking, order, ticket, sponsorship, or none."
    )
    target_id = serializers.CharField(
        write_only=True,
        required=False,
        allow_null=True,
        allow_blank=False,
        help_text="Target identifier (UUID or numeric ID)."
    )
    # Legacy target fields for backward compatibility.
    target_type = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Deprecated: internal ContentType ID. Use 'target' instead."
    )
    
    class Meta:
        model = Payment
        fields = (
            'user', 'event', 'method', 'base_amount', 'base_amount_currency', 'description',
            'target', 'target_id', 'target_type', 'metadata'
        )

    def _get_model_class_for_target(self, target: str):
        """Resolve model class and UUID field name for a target alias."""
        import_string, class_name, uuid_field = self.TARGET_MODEL_CONFIG[target]
        module = __import__(import_string, fromlist=[class_name])
        return getattr(module, class_name), uuid_field

    def _resolve_target_object(self, model_class, target_identifier: str, uuid_field: Optional[str] = None):
        """Resolve target by UUID first (if configured), then numeric PK fallback."""
        identifier = str(target_identifier).strip()
        queryset = model_class.objects.all()

        if uuid_field:
            try:
                UUID(identifier)
                return queryset.get(**{uuid_field: identifier})
            except ValueError:
                pass
            except model_class.DoesNotExist:
                pass

        if identifier.isdigit():
            return queryset.get(pk=int(identifier))

        return queryset.get(pk=identifier)
    
    def validate_base_amount(self, value):
        """Ensure amount is positive."""
        if value.amount <= 0:
            raise serializers.ValidationError("Payment amount must be greater than zero.")
        return value
    
    def validate_method(self, value):
        """Ensure payment method is active."""
        if value and not value.is_active:
            raise serializers.ValidationError("Selected payment method is not active.")
        return value

    def validate_base_amount_currency(self, value):
        """Validate currency code format."""
        if not value:
            return 'GBP'

        currency = str(value).strip().upper()
        if len(currency) != 3:
            raise serializers.ValidationError("Currency must be a 3-letter ISO 4217 code.")
        return currency
    
    def validate(self, attrs):
        """Cross-field validation for payment creation."""
        user = attrs.get('user')
        event = attrs.get('event')
        method = attrs.get('method')
        
        # Ensure method belongs to the same event
        if method and method.event != event:
            raise serializers.ValidationError({
                'method': "Payment method does not belong to the selected event."
            })
        
        # Validate and normalize target payload.
        target = attrs.get('target')
        target_type = attrs.get('target_type')
        target_identifier = attrs.get('target_id')

        if target and target_type:
            raise serializers.ValidationError({
                'target': "Provide either 'target' or legacy 'target_type', not both."
            })

        if target == 'none':
            if target_identifier:
                raise serializers.ValidationError({'target_id': "target_id must be empty when target is 'none'."})
            attrs['target_type'] = None
            attrs['target_id'] = None
            attrs.pop('target', None)
            return attrs

        if target:
            if not target_identifier:
                raise serializers.ValidationError({'target_id': "target_id is required when target is provided."})

            model_class, uuid_field = self._get_model_class_for_target(target)
            try:
                target_obj = self._resolve_target_object(model_class, target_identifier, uuid_field=uuid_field)
            except model_class.DoesNotExist:
                raise serializers.ValidationError({
                    'target_id': f"Target object '{target}' with identifier '{target_identifier}' does not exist."
                })

            attrs['target_type'] = ContentType.objects.get_for_model(model_class)
            attrs['target_id'] = str(target_obj.pk)
            attrs['_target_obj'] = target_obj
            attrs.pop('target', None)
            return attrs

        if target_identifier and not target_type:
            raise serializers.ValidationError(
                "Both legacy target_type and target_id must be provided together."
            )

        if target_type and not target_identifier:
            raise serializers.ValidationError(
                "Both legacy target_type and target_id must be provided together."
            )

        if target_type and target_identifier:
            model_class = target_type.model_class()
            if model_class is None:
                raise serializers.ValidationError({
                    'target_type': "Unsupported target_type provided."
                })
            try:
                target_obj = self._resolve_target_object(model_class, target_identifier)
                attrs['_target_obj'] = target_obj
                attrs['target_id'] = str(target_obj.pk)
            except ObjectDoesNotExist:
                raise serializers.ValidationError({
                    'target_id': f"Target object with identifier {target_identifier} does not exist."
                })

        attrs.pop('target', None)
        
        return attrs
    
    def create(self, validated_data):
        """Create payment with initial DRAFTING status."""
        validated_data.pop('_target_obj', None)  # Remove temp field
        
        # Create payment in DRAFTING status
        payment = Payment.objects.create(
            status=PaymentStatusChoices.DRAFTING,
            **validated_data
        )
        
        # Create history action
        PaymentHistoryAction.objects.create(
            payment=payment,
            action='PAYMENT_CREATED',
            description=f"Payment created for {validated_data['event'].title}",
            performed_by=self.context.get('request').user if self.context.get('request') else None
        )
        
        return payment


class PaymentUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for Payment with status transition validation."""
    
    class Meta:
        model = Payment
        fields = ('status', 'method', 'description', 'metadata', 'stripe_payment_intent', 'stripe_charge_id')
    
    def validate_status(self, value):
        """Validate status transition is allowed."""
        if self.instance:
            from apps.payments.models.payments import ALLOWED_STATUS_TRANSITIONS
            
            current_status = self.instance.status
            if current_status != value:
                allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, [])
                if value not in allowed:
                    raise serializers.ValidationError(
                        f"Cannot transition from {current_status} to {value}. "
                        f"Allowed transitions: {', '.join(allowed)}"
                    )

            if (
                value == PaymentStatusChoices.COMPLETED
                and self.instance.method
                and self.instance.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER
                and not self.instance.bank_transfer_evidence.filter(verification_status=VerificationStatus.VERIFIED).exists()
            ):
                raise serializers.ValidationError(
                    'Cannot complete bank transfer payment without verified bank transfer evidence.'
                )
        return value
    
    def update(self, instance, validated_data):
        """Update payment and log status changes."""
        old_status = instance.status
        new_status = validated_data.get('status', old_status)
        
        # Update the payment
        payment = super().update(instance, validated_data)
        
        # Log status change
        if old_status != new_status:
            PaymentHistoryAction.objects.create(
                payment=payment,
                action='STATUS_CHANGED',
                description=f"Status changed from {old_status} to {new_status}",
                performed_by=self.context.get('request').user if self.context.get('request') else None,
                metadata={'old_status': old_status, 'new_status': new_status}
            )
        
        return payment


# ============================================================================
# DISCOUNT SERIALIZERS
# ============================================================================

class DiscountRuleSerializer(serializers.ModelSerializer):
    """Serializer for DiscountRule."""
    
    added_by_name = serializers.CharField(source='added_by.username', read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = DiscountRule
        fields = (
            'rule_id', 'rule_type', 'name', 'description', 'value',
            'active', 'added_by', 'added_by_name', 'created_at', 'updated_at'
        )
        read_only_fields = ('rule_id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }


class DiscountRuleCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for DiscountRule with validation."""
    
    class Meta:
        model = DiscountRule
        fields = ('rule_type', 'name', 'description', 'value', 'active', 'discount')
    
    def validate(self, attrs):
        """Validate rule configuration based on type."""
        rule_type = attrs.get('rule_type')
        value = attrs.get('value')
        
        # Rules that require a value
        requires_value = [
            DiscountRuleTypeChoices.IS_AGE_LT,
            DiscountRuleTypeChoices.IS_AGE_GT,
            DiscountRuleTypeChoices.ORGANISATION_MATCHES,
            DiscountRuleTypeChoices.VALUE_MATCHES,
            DiscountRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES,
            DiscountRuleTypeChoices.NAME_MATCHES,
            DiscountRuleTypeChoices.LOCATION_MATCHES,
            DiscountRuleTypeChoices.CODE_MATCHES,
        ]
        
        if rule_type in requires_value and not value:
            raise serializers.ValidationError({
                'value': f"Rule type {rule_type} requires a value."
            })
        
        # Validate age rules have integer values
        if rule_type in [DiscountRuleTypeChoices.IS_AGE_GT, DiscountRuleTypeChoices.IS_AGE_LT]:
            try:
                int(value)
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    'value': "Age rules require an integer value."
                })
        
        return attrs


class DiscountListSerializer(serializers.ModelSerializer):
    """List serializer for Discount."""
    
    _links = serializers.SerializerMethodField()
    discount_value = serializers.SerializerMethodField(help_text="Human-readable discount value")
    target_package = serializers.SerializerMethodField(help_text="Target booking package if applicable")
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    rules = DiscountRuleSerializer(many=True, read_only=True)
    
    class Meta:
        model = Discount
        fields = (
            'id', 'discount_id', 'name', 'discount_type', 'discount_value',
            'description', 'percentage', 'amount', 'target_package',
            'active', 'created_by', 'created_by_name', 'created_at', 'rules', '_links'
        )
        read_only_fields = ('id', 'discount_id', 'created_at')
        extra_kwargs = {
            'created_at': {'default': None},
        }
    
    def get_discount_value(self, obj) -> str:
        """Return human-readable discount value."""
        return obj.display_value
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'id': {'type': 'integer'},
            'name': {'type': 'string'},
        },
        'nullable': True
    })
    def get_target_package(self, obj) -> Optional[Dict[str, Any]]:
        """Return target booking package info if discount is linked to a package."""
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage
        
        if obj.target and obj.target_type:
            package_ct = ContentType.objects.get_for_model(BookingPackage)
            if obj.target_type == package_ct and isinstance(obj.target, BookingPackage):
                return {
                    'id': obj.target.id,
                    'name': obj.target.name,
                }
        return None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'target': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/payments/discounts/{obj.discount_id}/"),
        }


class DiscountDetailSerializer(DiscountListSerializer):
    """Detailed serializer for Discount with rules.
    
    Note: target_type and target_id are internal fields and not exposed via API.
    """
    
    rules = DiscountRuleSerializer(many=True, read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta(DiscountListSerializer.Meta):
        fields = DiscountListSerializer.Meta.fields + (
            'description', 'percentage', 'amount', 'rules', 'updated_at'
        )


class DiscountCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for Discount with validation and nested rules.
    
    Note: target_type and target_id should only be set internally by the system.
    Supports nested rule creation/update with a maximum of 2 rules per discount.
    """
    
    amount = MoneyField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    rules = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        max_length=2,
        write_only=True,
        help_text="List of discount rules (maximum 2)"
    )
    # Target fields for internal use only
    target_type = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )
    target_id = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = Discount
        fields = (
            'name', 'description', 'discount_type', 'percentage', 'amount',
            'target_type', 'target_id', 'active', 'rules'
        )
    
    def validate_rules(self, value):
        """Validate rules array."""
        if len(value) > 2:
            raise serializers.ValidationError("Maximum 2 rules allowed per discount.")
        
        # Validate each rule
        for idx, rule_data in enumerate(value):
            # Check required fields
            if 'rule_type' not in rule_data:
                raise serializers.ValidationError({
                    f'rule_{idx}': "rule_type is required for each rule."
                })
            if 'name' not in rule_data:
                raise serializers.ValidationError({
                    f'rule_{idx}': "name is required for each rule."
                })
            
            rule_type = rule_data.get('rule_type')
            rule_value = rule_data.get('value')
            
            # Rules that require a value
            requires_value = [
                'IS_AGE_LT', 'IS_AGE_GT', 'ORGANISATION_MATCHES',
                'VALUE_MATCHES', 'EVENT_STAFF_ROLE_MATCHES', 'NAME_MATCHES',
                'LOCATION_MATCHES', 'CODE_MATCHES'
            ]
            
            if rule_type in requires_value and not rule_value:
                raise serializers.ValidationError({
                    f'rule_{idx}': f"Rule type {rule_type} requires a value."
                })
            
            # Validate age rules have integer values
            if rule_type in ['IS_AGE_GT', 'IS_AGE_LT']:
                try:
                    int(rule_value)
                except (TypeError, ValueError):
                    raise serializers.ValidationError({
                        f'rule_{idx}': "Age rules require an integer value."
                    })
        
        return value
    
    def validate(self, attrs):
        """Cross-field validation for discount configuration."""
        discount_type = attrs.get('discount_type')
        percentage = attrs.get('percentage')
        amount = attrs.get('amount')
        
        if discount_type == DiscountType.PERCENTAGE:
            if percentage is None:
                raise serializers.ValidationError({
                    'percentage': "Percentage discount requires a percentage value."
                })
            if amount is not None:
                raise serializers.ValidationError({
                    'amount': "Percentage discount should not have an amount value."
                })
            if not (0 <= percentage <= 100):
                raise serializers.ValidationError({
                    'percentage': "Percentage must be between 0 and 100."
                })
        
        elif discount_type == DiscountType.FIXED:
            if amount is None:
                raise serializers.ValidationError({
                    'amount': "Fixed discount requires an amount value."
                })
            if percentage is not None:
                raise serializers.ValidationError({
                    'percentage': "Fixed discount should not have a percentage value."
                })
            if amount.amount <= 0:
                raise serializers.ValidationError({
                    'amount': "Discount amount must be greater than zero."
                })
        
        # Validate target exists and user has access
        target_type = attrs.get('target_type')
        target_id = attrs.get('target_id')
        
        if target_type and target_id:
            try:
                model_class = target_type.model_class()
                target_obj = model_class.objects.get(pk=target_id)
                
                # Validate user has access to the target object
                self._validate_target_access(target_obj)
                
            except model_class.DoesNotExist:
                raise serializers.ValidationError({
                    'target_id': f"Target object does not exist."
                })
        
        return attrs
    
    def _validate_target_access(self, target_obj):
        """
        Validate that the user has access to manage discounts for the target object.
        
        For BookingPackage: User must have ADMINISTRATIVE role for the package's event.
        Superusers and staff always have access.
        
        Args:
            target_obj: The target object (e.g., BookingPackage)
        
        Raises:
            ValidationError: If user doesn't have access to the target
        """
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError({
                'target_id': "Unable to verify user access to target object."
            })
        
        user = request.user
        
        # Superusers and staff have access to everything
        if user.is_superuser or user.is_staff:
            return
        
        # Check access based on target type
        from apps.bookings.models import BookingPackage
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        
        if hasattr(target_obj, 'event'):
            # User must have ADMINISTRATIVE role for this event
            has_access = EventRoleAssignment.objects.filter(
                user=user,
                event=target_obj.event,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE
            ).exists()
            
            if not has_access:
                raise serializers.ValidationError({
                    'target_id': (
                        f"Permission denied: You don't have the required administrative role for event '{target_obj.event.title}'. "
                        f"To manage discounts for this booking package, you need an ADMINISTRATIVE role assignment "
                        f"(such as Event Manager, Financial Manager, or Administrator) for this event. "
                        f"Please contact your event organizer or system administrator."
                    )
                })
        else:
            # For other target types, we might need to add validation later
            # For now, require superuser/staff for unknown target types
            raise serializers.ValidationError({
                'target_id': (
                    f"Permission denied: Only system administrators can create discounts for this target type. "
                    f"If you need to create discounts for {type(target_obj).__name__} objects, "
                    f"please contact your system administrator to request elevated permissions."
                )
            })
    
    def create(self, validated_data):
        """Create discount with nested rules."""
        rules_data = validated_data.pop('rules', [])
        discount = super().create(validated_data)
        
        # Create rules
        request = self.context.get('request')
        user = request.user if request else None
        
        for rule_data in rules_data:
            DiscountRule.objects.create(
                discount=discount,
                added_by=user,
                rule_type=rule_data.get('rule_type'),
                name=rule_data.get('name'),
                description=rule_data.get('description', ''),
                value=rule_data.get('value', ''),
                active=rule_data.get('active', True)
            )
        
        return discount
    
    def update(self, instance, validated_data):
        """Update discount and sync rules."""
        rules_data = validated_data.pop('rules', None)
        discount = super().update(instance, validated_data)
        
        # If rules are provided, delete existing and create new ones
        if rules_data is not None:
            # Delete existing rules
            instance.rules.all().delete()
            
            # Create new rules
            request = self.context.get('request')
            user = request.user if request else None
            
            for rule_data in rules_data:
                DiscountRule.objects.create(
                    discount=discount,
                    added_by=user,
                    rule_type=rule_data.get('rule_type'),
                    name=rule_data.get('name'),
                    description=rule_data.get('description', ''),
                    value=rule_data.get('value', ''),
                    active=rule_data.get('active', True)
                )
        
        return discount


# ============================================================================
# REFUND SERIALIZERS
# ============================================================================

class RefundAssociationSerializer(serializers.ModelSerializer):
    """Serializer for RefundAssociation.
    
    Note: target_type and target_id are internal fields and not exposed via API.
    """
    
    amount = MoneyField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = RefundAssociation
        fields = (
            'id', 'refund_request', 'amount', 'description', 'metadata'
        )
        read_only_fields = ('id',)


class RefundAssociationCreateSerializer(serializers.ModelSerializer):
    """Create serializer for RefundAssociation with validation.
    
    Note: target_type and target_id should only be set internally by the system.
    """
    
    amount = MoneyField(max_digits=10, decimal_places=2)
    # Target fields for internal use only
    target_type = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )
    target_id = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = RefundAssociation
        fields = ('refund_request', 'target_type', 'target_id', 'amount', 'description', 'metadata')
    
    def validate_amount(self, value):
        """Ensure amount is positive."""
        if value.amount <= 0:
            raise serializers.ValidationError("Refund amount must be greater than zero.")
        return value
    
    def validate(self, attrs):
        """Validate refund association doesn't exceed payment amount."""
        refund_request = attrs.get('refund_request')
        amount = attrs.get('amount')
        
        # Check total doesn't exceed payment
        current_refunded = refund_request.get_refund_amount()
        if amount > (refund_request.payment.base_amount - current_refunded):
            raise serializers.ValidationError({
                'amount': f"Total refunds would exceed payment amount. "
                         f"Available: {refund_request.payment.base_amount - current_refunded}"
            })
        
        # Validate target exists
        target_type = attrs.get('target_type')
        target_id = attrs.get('target_id')
        
        if target_type and target_id:
            try:
                model_class = target_type.model_class()
                model_class.objects.get(pk=target_id)
            except model_class.DoesNotExist:
                raise serializers.ValidationError({
                    'target_id': "Target object does not exist."
                })
        
        return attrs


class RefundRequestListSerializer(serializers.ModelSerializer):
    """List serializer for RefundRequest."""
    
    _links = serializers.SerializerMethodField()
    payment_reference = serializers.CharField(source='payment.payment_reference', read_only=True)
    requested_by_name = serializers.CharField(source='requested_by.username', read_only=True, allow_null=True)
    amount = MoneyField(max_digits=10, decimal_places=2, read_only=True)
    requested_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = RefundRequest
        fields = (
            'id', 'refund_id', 'tracking_reference', 'payment', 'payment_reference',
            'amount', 'verification_status', 'requested_by', 'requested_by_name',
            'requested_at', 'is_active', '_links'
        )
        read_only_fields = ('id', 'refund_id', 'tracking_reference', 'requested_at')
        extra_kwargs = {
            'requested_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'payment': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/payments/refunds/{obj.refund_id}/"),
            'payment': request.build_absolute_uri(f"/api/payments/list/{obj.payment.payment_id}/"),
        }


class RefundRequestDetailSerializer(RefundRequestListSerializer):
    """Detailed serializer for RefundRequest with associations."""
    
    associations = RefundAssociationSerializer(many=True, read_only=True)
    processed_by_name = serializers.CharField(source='processed_by.username', read_only=True, allow_null=True)
    verified_by_name = serializers.CharField(source='verified_by.username', read_only=True, allow_null=True)
    is_partial = serializers.BooleanField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)
    processed_at = serializers.DateTimeField(read_only=True)
    verified_updated_at = serializers.DateTimeField(read_only=True)
    
    class Meta(RefundRequestListSerializer.Meta):
        fields = RefundRequestListSerializer.Meta.fields + (
            'reason', 'metadata', 'processed_at', 'processed_by', 'processed_by_name',
            'verified_updated_at', 'verified_by', 'verified_by_name',
            'is_partial', 'is_full', 'associations', 'reason'
        )


class RefundRequestCreateSerializer(serializers.ModelSerializer):
    """Create serializer for RefundRequest with validation."""
    
    amount = MoneyField(max_digits=10, decimal_places=2)
    payment = serializers.SlugRelatedField(slug_field='payment_id', queryset=Payment.objects.all())
    attendee_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        allow_empty=False,
        help_text="Required for PARTIAL booking refunds. List of attendee UUIDs to refund."
    )
    refund_items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        allow_empty=True,
        help_text=(
            "Optional granular refund targets. For booking-linked partial refunds, use items with: "
            "attendee_id (required), quantity (required), and one of order_item_id or unique variant/package selector."
        ),
    )
    reason_code = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=64,
        write_only=True,
        help_text="Short reason code for immutable audit metadata."
    )
    override_used_ticket_block = serializers.BooleanField(required=False, default=False, write_only=True)
    override_reason = serializers.CharField(required=False, allow_blank=False, max_length=500, write_only=True)
    
    class Meta:
        model = RefundRequest
        fields = (
            'payment', 'amount', 'amount_currency', 'reason',
            'attendee_ids', 'refund_items', 'reason_code', 'override_used_ticket_block', 'override_reason'
        )
    
    def validate_payment(self, value):
        """Ensure payment is completed and eligible for refund."""
        if value.status not in [PaymentStatusChoices.COMPLETED, PaymentStatusChoices.PARTIALLY_REFUNDED]:
            raise serializers.ValidationError(
                "Only completed payments can be refunded."
            )
        
        # Check if payment already has an active refund request
        if value.refund_requests.filter(is_active=True).exists():
            raise serializers.ValidationError(
                "This payment already has an active refund request."
            )
        
        return value
    
    def validate_amount(self, value):
        """Ensure amount is positive."""
        if value.amount <= 0:
            raise serializers.ValidationError("Refund amount must be greater than zero.")
        return value
    
    def validate_reason(self, value):
        """Ensure reason meets length requirements."""
        if len(value) < 10:
            raise serializers.ValidationError("Reason must be at least 10 characters.")
        if len(value) > 1000:
            raise serializers.ValidationError("Reason must not exceed 1000 characters.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation for refund request."""
        payment = attrs.get('payment')
        amount = attrs.get('amount')
        request = self.context.get('request')
        actor = request.user if request else None
        attendee_ids_raw = attrs.get('attendee_ids') or []
        attendee_ids = [str(att_id) for att_id in attendee_ids_raw]
        refund_items = attrs.get('refund_items') or []
        override_used_ticket_block = attrs.get('override_used_ticket_block', False)
        override_reason = attrs.get('override_reason')
        reason_code = attrs.get('reason_code', 'unspecified')
        refund_context = {
            'is_booking_payment': AttendeeRefundService.is_booking_payment(payment),
            'selected_attendee_ids': attendee_ids,
            'breakdown': None,
            'refund_scope': 'legacy',
            'selected_refund_items': [],
        }
        
        # Ensure amount doesn't exceed payment
        if amount > payment.base_amount:
            raise serializers.ValidationError({
                'amount': f"Refund amount cannot exceed payment amount ({payment.base_amount})."
            })

        is_targeted_booking_refund = refund_context['is_booking_payment'] and bool(refund_items)
        is_targeted_order_refund = (not refund_context['is_booking_payment']) and bool(refund_items)

        # Partial booking refunds must explicitly select attendees when not using granular targets.
        if refund_context['is_booking_payment'] and amount < payment.base_amount and not attendee_ids and not is_targeted_booking_refund:
            raise serializers.ValidationError({
                'attendee_ids': "attendee_ids is required for partial refunds on booking payments."
            })

        if refund_context['is_booking_payment'] and refund_items and attendee_ids:
            raise serializers.ValidationError({
                'refund_items': "Use either attendee_ids or refund_items for booking refunds, not both."
            })

        if not refund_context['is_booking_payment'] and attendee_ids:
            raise serializers.ValidationError({
                'attendee_ids': "attendee_ids is only valid for booking-linked payments."
            })

        if not refund_context['is_booking_payment'] and amount < payment.base_amount and not is_targeted_order_refund:
            raise serializers.ValidationError({
                'refund_items': "refund_items is required for partial refunds on order-linked payments."
            })

        if override_used_ticket_block and not override_reason:
            raise serializers.ValidationError({
                'override_reason': "override_reason is required when override_used_ticket_block=true."
            })

        if override_used_ticket_block and actor:
            from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices

            is_event_admin = actor.is_superuser or actor.is_staff or EventRoleAssignment.objects.filter(
                user=actor,
                event=payment.event,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
            ).exists()
            if not is_event_admin:
                raise serializers.ValidationError({
                    'override_used_ticket_block': (
                        "Only event administrative users may override the used-ticket refund block."
                    )
                })

        if refund_context['is_booking_payment'] and is_targeted_booking_refund:
            breakdown = AttendeeRefundService.calculate_targeted_booking_product_breakdown(payment, refund_items)
            refund_context['selected_attendee_ids'] = breakdown.get('selected_attendee_ids', [])
            refund_context['selected_refund_items'] = breakdown.get('items', [])
            refund_context['breakdown'] = breakdown
            refund_context['refund_scope'] = 'targeted_booking_products'

            breakdown_total = breakdown['total']
            breakdown_total_amount = Decimal(str(getattr(breakdown_total, 'amount', breakdown_total))).quantize(Decimal('0.01'))
            requested_amount = Decimal(str(amount.amount)).quantize(Decimal('0.01'))

            if requested_amount != breakdown_total_amount:
                raise serializers.ValidationError({
                    'amount': (
                        f"Targeted booking refund amount must match selected item total ({breakdown_total_amount})."
                    )
                })

        elif is_targeted_order_refund:
            breakdown = AttendeeRefundService.calculate_targeted_order_item_breakdown(payment, refund_items)
            refund_context['selected_refund_items'] = breakdown.get('items', [])
            refund_context['breakdown'] = breakdown
            refund_context['refund_scope'] = 'targeted_order_items'

            breakdown_total = breakdown['total']
            breakdown_total_amount = Decimal(str(getattr(breakdown_total, 'amount', breakdown_total))).quantize(Decimal('0.01'))
            requested_amount = Decimal(str(amount.amount)).quantize(Decimal('0.01'))

            if requested_amount != breakdown_total_amount:
                raise serializers.ValidationError({
                    'amount': (
                        f"Targeted order refund amount must match selected item total ({breakdown_total_amount})."
                    )
                })

        elif refund_context['is_booking_payment']:
            if not attendee_ids and amount == payment.base_amount:
                attendee_ids = list(
                    payment.target.attendees.filter(deleted_at__isnull=True).values_list('attendee_id', flat=True)
                )
                attendee_ids = [str(att_id) for att_id in attendee_ids]

            attendees = AttendeeRefundService.resolve_booking_attendees(payment, attendee_ids)

            if AttendeeRefundService.has_used_ticket(payment, attendees) and not override_used_ticket_block:
                raise serializers.ValidationError({
                    'attendee_ids': (
                        "One or more selected attendees already have a used ticket. "
                        "Set override_used_ticket_block=true with override_reason if admin override is intended."
                    )
                })

            breakdown = AttendeeRefundService.calculate_breakdown(payment, attendees)
            refund_context['selected_attendee_ids'] = attendee_ids
            refund_context['breakdown'] = breakdown
            refund_context['refund_scope'] = 'attendee_entities'

            # Explicitly enforce amount integrity for partial booking refunds.
            breakdown_total = breakdown['total']
            breakdown_total_amount = Decimal(str(getattr(breakdown_total, 'amount', breakdown_total))).quantize(Decimal('0.01'))
            requested_amount = Decimal(str(amount.amount)).quantize(Decimal('0.01'))

            if amount < payment.base_amount and requested_amount != breakdown_total_amount:
                raise serializers.ValidationError({
                    'amount': (
                        f"Partial booking refund amount must match selected attendee entity total ({breakdown_total_amount})."
                    )
                })
        
        # Check refund policy if exists
        if hasattr(payment.event, 'refund_policy'):
            policy = payment.event.refund_policy
            if not policy.is_refundable(timezone.now()):
                raise serializers.ValidationError(
                    "This payment is not eligible for refund according to the event's refund policy."
                )

        attrs['_attendee_refund_context'] = {
            **refund_context,
            'reason_code': reason_code,
            'override_used_ticket_block': override_used_ticket_block,
            'override_reason': override_reason,
            'requested_by_id': actor.id if actor else None,
            'requested_by_username': actor.username if actor else None,
        }
        
        return attrs
    
    def create(self, validated_data):
        """Create refund request with requesting user."""
        refund_context = validated_data.pop('_attendee_refund_context', {})
        validated_data.pop('attendee_ids', None)
        validated_data.pop('refund_items', None)
        validated_data.pop('reason_code', None)
        validated_data.pop('override_used_ticket_block', None)
        validated_data.pop('override_reason', None)
        validated_data['requested_by'] = self.context.get('request').user if self.context.get('request') else None
        refund_request = super().create(validated_data)

        metadata = refund_request.metadata or {}
        metadata.update(
            {
                'selected_attendee_ids': refund_context.get('selected_attendee_ids', []),
                'selected_refund_items': refund_context.get('selected_refund_items', []),
                'reason_code': refund_context.get('reason_code', 'unspecified'),
                'requested_by_id': refund_context.get('requested_by_id'),
                'requested_by_username': refund_context.get('requested_by_username'),
                'override_used_ticket_block': refund_context.get('override_used_ticket_block', False),
                'override_reason': refund_context.get('override_reason'),
                'refund_scope': refund_context.get('refund_scope', 'legacy'),
                'frozen_breakdown': refund_context.get('breakdown'),
            }
        )
        refund_request.metadata = metadata
        refund_request.save(update_fields=['metadata'])

        AttendeeRefundService.attach_associations(refund_request)
        return refund_request


class RefundRequestUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for RefundRequest status changes."""
    
    class Meta:
        model = RefundRequest
        fields = ('verification_status', 'metadata')
    
    def validate_verification_status(self, value):
        """Validate status transition."""
        if self.instance:
            current = self.instance.verification_status
            
            # Define allowed transitions
            allowed_transitions = {
                VerificationStatus.PENDING: [VerificationStatus.VERIFIED, VerificationStatus.REJECTED],
                VerificationStatus.VERIFIED: [VerificationStatus.PROCESSED],
            }
            
            if current != value:
                allowed = allowed_transitions.get(current, [])
                if value not in allowed:
                    raise serializers.ValidationError(
                        f"Cannot transition from {current} to {value}."
                    )
        
        return value
    
    def update(self, instance, validated_data):
        """Update refund request and handle status changes."""
        new_status = validated_data.get('verification_status', instance.verification_status)
        user = self.context.get('request').user if self.context.get('request') else None
        
        if new_status == VerificationStatus.VERIFIED and instance.verification_status != new_status:
            instance.mark_verified(user)
        elif new_status == VerificationStatus.PROCESSED and instance.verification_status != new_status:
            instance.mark_processed(user)
        elif new_status == VerificationStatus.REJECTED and instance.verification_status != new_status:
            instance.mark_rejected(user)
        else:
            instance = super().update(instance, validated_data)
        
        return instance


class RefundPolicySerializer(serializers.ModelSerializer):
    """Serializer for RefundPolicy."""
    
    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.name', read_only=True)
    
    class Meta:
        model = RefundPolicy
        fields = (
            'id', 'event', 'event_name', 'policy_type', 'refundable_within_days',
            'percentage_refund', 'notes', '_links'
        )
        read_only_fields = ('id',)
    
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
            'self': request.build_absolute_uri(f"/api/payments/refund-policies/{obj.id}/"),
            'event': request.build_absolute_uri(f"/api/event/list/{obj.event.event_id}/"),
        }


class RefundPolicyCreateUpdateSerializer(serializers.ModelSerializer):
    """Create/Update serializer for RefundPolicy with validation."""
    
    class Meta:
        model = RefundPolicy
        fields = ('event', 'policy_type', 'refundable_within_days', 'percentage_refund', 'notes')
    
    def validate_refundable_within_days(self, value):
        """Ensure days is non-negative."""
        if value < 0:
            raise serializers.ValidationError("Days must be non-negative.")
        return value
    
    def validate_percentage_refund(self, value):
        """Ensure percentage is between 0 and 100."""
        if not (0 <= value <= 100):
            raise serializers.ValidationError("Percentage must be between 0 and 100.")
        return value
    
    def validate(self, attrs):
        """Validate policy configuration."""
        policy_type = attrs.get('policy_type')
        percentage = attrs.get('percentage_refund', 100)
        
        if policy_type == RefundPolicyTypeChoices.PARTIAL_REFUND and percentage == 100:
            raise serializers.ValidationError({
                'percentage_refund': "Partial refund policy should have a percentage less than 100."
            })
        
        return attrs


# ============================================================================
# DONATION SERIALIZERS
# ============================================================================

class DonationListSerializer(serializers.ModelSerializer):
    """List serializer for Donation."""
    
    _links = serializers.SerializerMethodField()
    payment_reference = serializers.CharField(source='payment.payment_reference', read_only=True)
    donated_by_name = serializers.CharField(source='donated_by.username', read_only=True, allow_null=True)
    amount = MoneyField(max_digits=10, decimal_places=2, read_only=True)
    donated_at = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = Donation
        fields = (
            'id', 'donation_id', 'tracking_reference', 'amount',
            'payment', 'payment_reference', 'verification_status',
            'donated_by', 'donated_by_name', 'donated_at', '_links'
        )
        read_only_fields = ('id', 'donation_id', 'tracking_reference', 'donated_at')
        extra_kwargs = {
            'donated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'payment': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(f"/api/payments/donations/{obj.donation_id}/"),
            'payment': request.build_absolute_uri(f"/api/payments/list/{obj.payment.payment_id}/"),
        }


class DonationDetailSerializer(DonationListSerializer):
    """Detailed serializer for Donation."""
    
    verified_by_name = serializers.CharField(source='verified_by.username', read_only=True, allow_null=True)
    processed_by_name = serializers.CharField(source='processed_by.username', read_only=True, allow_null=True)
    verified_updated_at = serializers.DateTimeField(read_only=True)
    processed_at = serializers.DateTimeField(read_only=True)
    
    class Meta(DonationListSerializer.Meta):
        fields = DonationListSerializer.Meta.fields + (
            'verified_updated_at', 'verified_by', 'verified_by_name',
            'processed_at', 'processed_by', 'processed_by_name', 'auto_processed'
        )


class DonationCreateSerializer(serializers.ModelSerializer):
    """Create serializer for Donation with validation."""
    
    amount = MoneyField(max_digits=10, decimal_places=2)
    
    class Meta:
        model = Donation
        fields = ('amount', 'payment')
    
    def validate_amount(self, value):
        """Ensure amount is positive."""
        if value.amount <= 0:
            raise serializers.ValidationError("Donation amount must be greater than zero.")
        return value
    
    def validate_payment(self, value):
        """Ensure payment is completed and belongs to the user."""
        if value.status != PaymentStatusChoices.COMPLETED:
            raise serializers.ValidationError(
                "Donations can only be made on completed payments."
            )
        
        return value
    
    def create(self, validated_data):
        """Create donation with donating user."""
        validated_data['donated_by'] = self.context.get('request').user if self.context.get('request') else None
        return super().create(validated_data)
#
class DonationCheckoutSerializer(serializers.Serializer):
    """
    Checkout serializer for creating donations with payment.
    
    Accepts donation amount, payment method, and optional event/message.
    Backend validates amount and creates both Donation and Payment atomically.
    """
    
    amount = MoneyField(
        max_digits=10,
        decimal_places=2,
        help_text="Donation amount (must be > £0 and < £10,000)"
    )
    payment_method_id = serializers.IntegerField(
        help_text="ID of the PaymentMethod to use"
    )
    user_id = serializers.IntegerField(
        required=False,
        help_text="Optional donor user ID. Requires event administrative permissions when different from authenticated user."
    )
    event_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional event ID for event-specific donations"
    )
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Optional message from donor"
    )
    
    def validate_amount(self, value):
        """Validate donation amount is reasonable."""
        # Handle both Money objects (from internal use) and Decimal (from API input)
        if isinstance(value, Money):
            amount = value.amount
        else:
            # When sent as separate amount/currency fields, value is Decimal
            amount = value
        
        if amount <= 0:
            raise serializers.ValidationError("Donation amount must be greater than £0.")
        
        if amount > 10000:
            raise serializers.ValidationError("Donation amount cannot exceed £10,000. Please contact support for larger donations.")
        
        return value
    
    def validate_payment_method_id(self, value):
        """Validate payment method exists and is active."""
        from apps.payments.models import PaymentMethod
        
        try:
            payment_method = PaymentMethod.objects.get(id=value)
        except PaymentMethod.DoesNotExist:
            raise serializers.ValidationError(
                f'PaymentMethod with id {value} does not exist.'
            )
        
        if not payment_method.is_active:
            raise serializers.ValidationError(
                f'Payment method "{payment_method.title}" is not active.'
            )
        
        return value
    
    def validate_event_id(self, value):
        """Validate event exists if provided."""
        if value:
            from apps.events.models import Event
            try:
                Event.objects.get(event_id=value)
            except Event.DoesNotExist:
                raise serializers.ValidationError(
                    f'Event with id {value} does not exist.'
                )
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        from apps.payments.models import PaymentMethod
        from apps.events.models import Event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        from apps.attendee.models import Attendee
        
        payment_method = PaymentMethod.objects.get(id=attrs['payment_method_id'])
        event_id = attrs.get('event_id')
        request = self.context.get('request')
        request_user = request.user if request else None
        
        # If event is provided, validate payment method belongs to that event
        if event_id:
            event = Event.objects.get(event_id=event_id)
            
            if payment_method.event_id != event.id:
                raise serializers.ValidationError({
                    'payment_method_id': f'Payment method must belong to the selected event ({event.title}).'
                })
            
            attrs['event'] = event
        else:
            # For general donations, payment method should have an event context
            if not payment_method.event:
                raise serializers.ValidationError({
                    'payment_method_id': 'Payment method must have an event context.'
                })
            
            attrs['event'] = payment_method.event

        donor_user = request_user
        requested_user_id = attrs.get('user_id')
        if requested_user_id is not None:
            try:
                donor_user = User.objects.get(id=requested_user_id, is_active=True)
            except User.DoesNotExist:
                raise serializers.ValidationError({'user_id': 'Selected user does not exist or is inactive.'})

            if request_user and donor_user != request_user:
                is_platform_admin = request_user.is_superuser or request_user.is_staff
                is_event_admin = EventRoleAssignment.objects.filter(
                    user=request_user,
                    event=attrs['event'],
                    role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
                ).exists()

                if not (is_platform_admin or is_event_admin):
                    raise serializers.ValidationError({
                        'user_id': 'You do not have permission to create donations for another user.'
                    })

            is_event_attendee = Attendee.objects.filter(
                user=donor_user,
                event=attrs['event'],
                deleted_at__isnull=True,
            ).exists()
            is_event_staff = donor_user.event_staff.filter(event=attrs['event']).exists()
            has_event_role = donor_user.event_roles.filter(event=attrs['event']).exists()

            if not (is_event_attendee or is_event_staff or has_event_role):
                raise serializers.ValidationError({
                    'user_id': 'Selected user is not an attendee or service team member for this event.'
                })
        
        attrs['payment_method'] = payment_method
        attrs['donor_user'] = donor_user
        
        return attrs


# ============================================================================
# CREDIT SERIALIZERS
# ============================================================================

class CreditExpenseListSerializer(serializers.ModelSerializer):
    """List serializer for CreditExpense with read-only generic target details."""

    _links = serializers.SerializerMethodField()
    event_name = serializers.CharField(source='event.name', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    target = serializers.SerializerMethodField()
    target_type = serializers.CharField(source='target_type.model', read_only=True, allow_null=True)
    target_type_name = serializers.CharField(source='target_type.name', read_only=True, allow_null=True)

    class Meta:
        model = CreditExpense
        fields = (
            'credit_id', 'amount', 'amount_currency', 'description', 'expense_type',
            'event', 'event_name', 'created_by', 'created_by_name',
            'paid_date', 'is_settled', 'verification_status',
            'target', 'target_type', 'target_type_name', 'target_id',
            'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('credit_id', 'created_at', 'updated_at', 'target', 'target_type', 'target_type_name', 'target_id')

    @extend_schema_field(OpenApiTypes.STR)
    def get_target(self, obj) -> Optional[str]:
        return str(obj.target) if obj.target else None

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

        links = {
            'self': request.build_absolute_uri(f"/api/payments/credits/{obj.credit_id}/"),
        }
        if obj.event:
            links['event'] = request.build_absolute_uri(f"/api/events/{obj.event.event_id}/")
        return links


class CreditExpenseDetailSerializer(CreditExpenseListSerializer):
    """Detailed serializer for CreditExpense."""

    verified_by_name = serializers.CharField(source='verified_by.username', read_only=True, allow_null=True)
    processed_by_name = serializers.CharField(source='processed_by.username', read_only=True, allow_null=True)

    class Meta(CreditExpenseListSerializer.Meta):
        fields = CreditExpenseListSerializer.Meta.fields + (
            'verified_updated_at', 'verified_by', 'verified_by_name',
            'processed_at', 'processed_by', 'processed_by_name', 'auto_processed'
        )


class CreditExpenseCreateSerializer(serializers.ModelSerializer):
    """Create serializer for CreditExpense."""

    amount = MoneyField(max_digits=14, decimal_places=2)

    class Meta:
        model = CreditExpense
        fields = ('event', 'amount', 'description', 'expense_type', 'paid_date', 'is_settled')

    def validate_amount(self, value):
        if value.amount <= 0:
            raise serializers.ValidationError('Credit amount must be greater than zero.')
        return value

    def validate(self, attrs):
        forbidden_fields = {'target_type', 'target_id'}
        provided_forbidden = forbidden_fields.intersection(getattr(self, 'initial_data', {}).keys())
        if provided_forbidden:
            raise serializers.ValidationError({
                field: 'This field is read-only and controlled by the backend.'
                for field in sorted(provided_forbidden)
            })

        return attrs

    def validate_paid_date(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError('Paid date cannot be in the future.')
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['created_by'] = request.user if request else None
        return super().create(validated_data)


class CreditExpenseUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for CreditExpense."""

    class Meta:
        model = CreditExpense
        fields = ('description', 'paid_date', 'is_settled', 'verification_status')

    def validate_paid_date(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError('Paid date cannot be in the future.')
        return value

    def validate(self, attrs):
        forbidden_fields = {'target_type', 'target_id'}
        provided_forbidden = forbidden_fields.intersection(getattr(self, 'initial_data', {}).keys())
        if provided_forbidden:
            raise serializers.ValidationError({
                field: 'This field is read-only and controlled by the backend.'
                for field in sorted(provided_forbidden)
            })

        return attrs

    def validate_verification_status(self, value):
        if self.instance:
            current = self.instance.verification_status
            allowed_transitions = {
                VerificationStatus.PENDING: [VerificationStatus.VERIFIED, VerificationStatus.REJECTED],
                VerificationStatus.VERIFIED: [VerificationStatus.PROCESSED],
            }

            if current != value and value not in allowed_transitions.get(current, []):
                raise serializers.ValidationError(f'Cannot transition from {current} to {value}.')

        return value

    def update(self, instance, validated_data):
        new_status = validated_data.get('verification_status', instance.verification_status)
        user = self.context.get('request').user if self.context.get('request') else None

        if new_status == VerificationStatus.VERIFIED and instance.verification_status != new_status:
            instance.mark_verified(user)
        elif new_status == VerificationStatus.PROCESSED and instance.verification_status != new_status:
            instance.mark_processed(user)
        elif new_status == VerificationStatus.REJECTED and instance.verification_status != new_status:
            instance.mark_rejected(user)
        else:
            instance = super().update(instance, validated_data)

        return instance


# ============================================================================
# BANK TRANSFER EVIDENCE SERIALIZERS
# ============================================================================

class BankTransferEvidenceListSerializer(serializers.ModelSerializer):
    """List serializer for bank transfer evidence."""

    _links = serializers.SerializerMethodField()
    payment_reference = serializers.CharField(source='payment.payment_reference', read_only=True, allow_null=True)
    payer_name = serializers.CharField(read_only=True, allow_null=True)
    payer_account_last4 = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = BankTransferEvidence
        fields = (
            'bank_transfer_id', 'transfer_id', 'evidence_file',
            'payment', 'payment_reference', 'payer_name', 'payer_account_last4',
            'amount_on_evidence', 'verification_status', 'uploaded_at', 'auto_expiry_date', '_links'
        )
        read_only_fields = ('bank_transfer_id', 'uploaded_at', 'auto_expiry_date')

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'payment': {'type': 'string', 'format': 'uri'},
        }
    })
    def get__links(self, obj) -> Dict[str, str]:
        request = self.context.get('request')
        if not request:
            return {}

        links = {
            'self': request.build_absolute_uri(f"/api/payments/bank-transfer-evidence/{obj.bank_transfer_id}/"),
        }
        if obj.payment:
            links['payment'] = request.build_absolute_uri(f"/api/payments/list/{obj.payment.payment_id}/")
        return links


class BankTransferEvidenceDetailSerializer(BankTransferEvidenceListSerializer):
    """Detailed serializer for bank transfer evidence."""

    verified_by_name = serializers.CharField(source='verified_by.username', read_only=True, allow_null=True)
    processed_by_name = serializers.CharField(source='processed_by.username', read_only=True, allow_null=True)

    class Meta(BankTransferEvidenceListSerializer.Meta):
        fields = BankTransferEvidenceListSerializer.Meta.fields + (
            'metadata', 'verified_updated_at', 'verified_by', 'verified_by_name',
            'processed_at', 'processed_by', 'processed_by_name', 'auto_processed'
        )


class BankTransferEvidenceCreateSerializer(serializers.ModelSerializer):
    """Create serializer for bank transfer evidence."""

    amount_on_evidence = MoneyField(max_digits=14, decimal_places=2, required=False, allow_null=True)

    class Meta:
        model = BankTransferEvidence
        fields = (
            'transfer_id', 'evidence_file', 'payer_name', 'payer_account_last4',
            'amount_on_evidence', 'metadata', 'payment'
        )

    def validate_transfer_id(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError('Transfer ID is required.')
        return value.strip()

    def validate(self, attrs):
        payment = attrs.get('payment')
        transfer_id = attrs.get('transfer_id', '')
        metadata = attrs.get('metadata') or {}
        attrs['metadata'] = metadata

        if not payment:
            matched_payment = self._find_matching_payment(transfer_id)
            if matched_payment:
                attrs['payment'] = matched_payment
                attrs['metadata']['auto_matched_payment_id'] = str(matched_payment.payment_id)

        if payment and payment.bank_transfer_reference:
            if transfer_id.lower() not in payment.bank_transfer_reference.lower() and payment.bank_transfer_reference.lower() not in transfer_id.lower():
                attrs['metadata']['match_suggestion'] = payment.bank_transfer_reference

        return attrs

    def _find_matching_payment(self, transfer_id):
        if not transfer_id:
            return None

        payment_qs = Payment.objects.filter(bank_transfer_reference__icontains=transfer_id)
        if payment_qs.count() == 1:
            return payment_qs.first()
        return None

    def create(self, validated_data):
        instance = super().create(validated_data)
        return instance


class BankTransferEvidenceUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for bank transfer evidence."""

    class Meta:
        model = BankTransferEvidence
        fields = ('payer_name', 'payer_account_last4', 'metadata', 'payment', 'verification_status')

    def validate_verification_status(self, value):
        if self.instance:
            current = self.instance.verification_status
            allowed_transitions = {
                VerificationStatus.PENDING: [VerificationStatus.VERIFIED, VerificationStatus.REJECTED],
                VerificationStatus.VERIFIED: [VerificationStatus.PROCESSED],
            }

            if current != value and value not in allowed_transitions.get(current, []):
                raise serializers.ValidationError(f'Cannot transition from {current} to {value}.')

        return value

    def update(self, instance, validated_data):
        new_status = validated_data.get('verification_status', instance.verification_status)
        user = self.context.get('request').user if self.context.get('request') else None

        if new_status == VerificationStatus.VERIFIED and instance.verification_status != new_status:
            instance.mark_verified(user)
        elif new_status == VerificationStatus.PROCESSED and instance.verification_status != new_status:
            instance.mark_processed(user)
        elif new_status == VerificationStatus.REJECTED and instance.verification_status != new_status:
            instance.mark_rejected(user)
        else:
            instance = super().update(instance, validated_data)

        return instance


# ============================================================================
# PAYMENT HISTORY SERIALIZERS
# ============================================================================

class PaymentHistoryActionSerializer(serializers.ModelSerializer):
    """Serializer for PaymentHistoryAction."""
    
    performed_by_name = serializers.CharField(source='performed_by.username', read_only=True, allow_null=True)
    payment_reference = serializers.CharField(source='payment.payment_reference', read_only=True)
    timestamp = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = PaymentHistoryAction
        fields = (
            'id', 'action_id', 'payment', 'payment_reference', 'action',
            'description', 'metadata', 'performed_by', 'performed_by_name',
            'timestamp', 'notes'
        )
        read_only_fields = ('id', 'action_id', 'timestamp')
        extra_kwargs = {
            'timestamp': {'default': None},
        }
