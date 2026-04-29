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
