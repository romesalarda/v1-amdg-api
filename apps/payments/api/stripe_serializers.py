"""
Serializers for Stripe API views.
"""
from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentMethodTypeChoices,
    StripeConnectedAccount,
    StripeConnectedAccountStatusChoices,
)
from apps.payments.services.stripe.connect import StripeConnectService
from apps.payments.services.stripe.exceptions import StripeServiceError


class StripeConfigResponseSerializer(serializers.Serializer):
    """Response serializer for Stripe configuration."""
    
    publishable_key = serializers.CharField(
        help_text="Stripe publishable key for frontend (test or live mode)"
    )
    test_mode = serializers.BooleanField(
        help_text="Whether Stripe is in test mode"
    )


class StripeConnectAccountSerializer(serializers.Serializer):
    """Response serializer for Stripe Connect account status."""

    connected_account_id = serializers.UUIDField(required=False, allow_null=True)
    stripe_account_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    status = serializers.ChoiceField(choices=StripeConnectedAccountStatusChoices.choices)
    charges_enabled = serializers.BooleanField()
    payouts_enabled = serializers.BooleanField()
    details_submitted = serializers.BooleanField()
    disabled_reason = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    country = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    business_type = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    onboarding_url = serializers.URLField(required=False, allow_null=True, allow_blank=True)
    requires_onboarding = serializers.BooleanField()
    created_at = serializers.DateTimeField(required=False, allow_null=True)
    updated_at = serializers.DateTimeField(required=False, allow_null=True)
    synced_at = serializers.DateTimeField(required=False, allow_null=True)


class StripeConnectedAccountListSerializer(serializers.ModelSerializer):
    """Serializer for listing and retrieving user Stripe connected accounts."""

    status = serializers.CharField(read_only=True)

    class Meta:
        model = StripeConnectedAccount
        fields = (
            'connected_account_id',
            'stripe_account_id',
            'display_name',
            'is_active',
            'is_primary',
            'account_type',
            'country',
            'email',
            'business_type',
            'charges_enabled',
            'payouts_enabled',
            'details_submitted',
            'disabled_reason',
            'status',
            'created_at',
            'updated_at',
            'synced_at',
        )
        read_only_fields = (
            'connected_account_id',
            'stripe_account_id',
            'account_type',
            'country',
            'email',
            'business_type',
            'charges_enabled',
            'payouts_enabled',
            'details_submitted',
            'disabled_reason',
            'status',
            'created_at',
            'updated_at',
            'synced_at',
        )


class StripeConnectedAccountCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a user-owned Stripe connected account record."""

    class Meta:
        model = StripeConnectedAccount
        fields = ('stripe_account_id', 'display_name', 'is_primary')

    def validate_stripe_account_id(self, value):
        normalized = str(value).strip()
        if not normalized:
            raise serializers.ValidationError("stripe_account_id is required.")
        return normalized

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        stripe_account_id = attrs.get('stripe_account_id')

        if not user or not user.is_authenticated:
            raise serializers.ValidationError('Authentication is required.')

        if StripeConnectedAccount.objects.filter(user=user, stripe_account_id=stripe_account_id).exists():
            raise serializers.ValidationError({
                'stripe_account_id': 'This Stripe account is already registered for your user.'
            })

        owner = StripeConnectedAccount.objects.filter(stripe_account_id=stripe_account_id).exclude(user=user).first()
        if owner:
            raise serializers.ValidationError({
                'stripe_account_id': 'This Stripe account is already registered by another user.'
            })

        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user
        stripe_account_id = validated_data['stripe_account_id']

        try:
            stripe_account = StripeConnectService.retrieve_account(stripe_account_id)
        except StripeServiceError as exc:
            raise serializers.ValidationError({'stripe_account_id': exc.user_message}) from exc

        account = StripeConnectedAccount.objects.create(
            user=user,
            stripe_account_id=stripe_account_id,
            display_name=validated_data.get('display_name', ''),
            is_primary=validated_data.get('is_primary', False),
            account_type=getattr(stripe_account, 'type', 'express') or 'express',
            country=getattr(stripe_account, 'country', '') or '',
            email=getattr(stripe_account, 'email', '') or user.email,
            business_type=getattr(stripe_account, 'business_type', '') or 'individual',
            charges_enabled=bool(getattr(stripe_account, 'charges_enabled', False)),
            payouts_enabled=bool(getattr(stripe_account, 'payouts_enabled', False)),
            details_submitted=bool(getattr(stripe_account, 'details_submitted', False)),
            disabled_reason=StripeConnectService.get_disabled_reason(getattr(stripe_account, 'requirements', None)),
            capabilities=getattr(stripe_account, 'capabilities', {}) or {},
            requirements=getattr(stripe_account, 'requirements', {}) or {},
            metadata=getattr(stripe_account, 'metadata', {}) or {},
        )

        return account


class StripeConnectedAccountUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating mutable Stripe connected account fields only."""

    class Meta:
        model = StripeConnectedAccount
        fields = ('display_name', 'is_active', 'is_primary')

    def validate(self, attrs):
        immutable_fields = {
            'stripe_account_id',
            'charges_enabled',
            'payouts_enabled',
            'details_submitted',
            'created_at',
            'updated_at',
            'synced_at',
            'account_type',
            'country',
            'email',
            'business_type',
            'disabled_reason',
            'capabilities',
            'requirements',
            'metadata',
        }
        attempted = immutable_fields.intersection(set(self.initial_data.keys()))
        if attempted:
            field_list = ', '.join(sorted(attempted))
            raise serializers.ValidationError({
                'detail': f'These fields are immutable: {field_list}'
            })

        return attrs


class CreatePaymentIntentSerializer(serializers.Serializer):
    """
    Serializer for creating a Stripe PaymentIntent.
    
    Validates target entity and payment method selection.
    """
    
    target_type = serializers.ChoiceField(
        choices=['order', 'booking'],
        help_text="Type of entity being paid for"
    )
    target_id = serializers.IntegerField(
        min_value=1,
        help_text="ID of the entity being paid for"
    )
    payment_method_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional: Specific PaymentMethod to use (must be Stripe type)"
    )
    
    def validate_target_type(self, value):
        """Validate target type exists in system."""
        valid_types = ['order', 'booking']
        if value.lower() not in valid_types:
            raise serializers.ValidationError(
                f"Invalid target_type. Must be one of: {', '.join(valid_types)}"
            )
        return value.lower()
    
    def validate_payment_method_id(self, value):
        """Validate PaymentMethod exists and is Stripe type."""
        if value is None:
            return None
        
        try:
            payment_method = PaymentMethod.objects.get(pk=value)
            if payment_method.method_type != PaymentMethodTypeChoices.STRIPE:
                raise serializers.ValidationError(
                    "Selected payment method is not a Stripe payment method"
                )
            if not payment_method.is_active:
                raise serializers.ValidationError(
                    "Selected payment method is not active"
                )
            return payment_method
        except PaymentMethod.DoesNotExist:
            raise serializers.ValidationError(
                f"PaymentMethod with id {value} does not exist"
            )
    
    def validate(self, attrs):
        """Cross-field validation."""
        target_type = attrs['target_type']
        target_id = attrs['target_id']
        
        # Validate target exists
        try:
            content_type = ContentType.objects.get(model=target_type)
            target_model = content_type.model_class()
            target = target_model.objects.get(pk=target_id)
            attrs['target_object'] = target
        except Exception as e:
            raise serializers.ValidationError({
                'target_id': f"Invalid {target_type} with id {target_id}: {str(e)}"
            })
        
        # Validate user has access to target
        request = self.context.get('request')
        if request and request.user:
            # Check ownership based on target type
            if hasattr(target, 'customer') and target.customer != request.user:
                raise serializers.ValidationError(
                    "You don't have permission to pay for this entity"
                )
            if hasattr(target, 'made_by') and target.made_by != request.user:
                raise serializers.ValidationError(
                    "You don't have permission to pay for this entity"
                )
        
        return attrs


class PaymentIntentResponseSerializer(serializers.Serializer):
    """Response serializer for PaymentIntent creation."""
    
    client_secret = serializers.CharField(
        help_text="PaymentIntent client secret for Stripe.js"
    )
    payment_intent_id = serializers.CharField(
        help_text="Stripe PaymentIntent ID"
    )
    publishable_key = serializers.CharField(
        help_text="Stripe publishable key"
    )
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Payment amount"
    )
    currency = serializers.CharField(
        help_text="Payment currency code (lowercase)"
    )
    payment_reference = serializers.CharField(
        help_text="Internal payment reference"
    )
    test_mode = serializers.BooleanField(
        help_text="Whether this is a test mode payment"
    )


class ConfirmPaymentIntentSerializer(serializers.Serializer):
    """Request serializer for manual payment confirmation."""
    
    payment_intent_id = serializers.CharField(
        required=True,
        help_text="Stripe PaymentIntent ID to confirm"
    )
    payment_method = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Optional Stripe PaymentMethod ID if not already attached"
    )


class ConfirmPaymentIntentResponseSerializer(serializers.Serializer):
    """Response serializer for manual payment confirmation."""
    
    status = serializers.CharField(help_text="Operation status")
    payment_intent = serializers.DictField(
        help_text="PaymentIntent details",
        child=serializers.CharField()
    )


class ErrorResponseSerializer(serializers.Serializer):
    """Standard error response serializer."""
    
    error = serializers.CharField(help_text="User-friendly error message")
    details = serializers.DictField(
        required=False,
        help_text="Additional error details for debugging"
    )


class WebhookResponseSerializer(serializers.Serializer):
    """Response serializer for webhook processing."""
    
    status = serializers.CharField(
        help_text="Processing status (success, ignored, error)"
    )
    event_id = serializers.CharField(
        required=False,
        help_text="Stripe event ID"
    )
    result = serializers.DictField(
        required=False,
        help_text="Processing result details"
    )
