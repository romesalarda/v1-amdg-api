"""
Stripe-specific API views.

Provides endpoints for:
- Creating PaymentIntents (lazy creation on checkout)
- Manual payment confirmation
- Stripe configuration for frontend
- Webhook event processing
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
import logging

from apps.payments.models import Payment, PaymentStatusChoices
from apps.payments.api.stripe_serializers import (
    CreatePaymentIntentSerializer,
    PaymentIntentResponseSerializer,
    ConfirmPaymentIntentSerializer,
    ConfirmPaymentIntentResponseSerializer,
    StripeConfigResponseSerializer,
    ErrorResponseSerializer,
    WebhookResponseSerializer,
)
from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.payment_intents import PaymentIntentService
from apps.payments.services.stripe.webhooks import verify_webhook_signature, process_webhook_event
from apps.payments.services.stripe.exceptions import StripeServiceError, StripeWebhookError

logger = logging.getLogger(__name__)


class StripeConfigView(APIView):
    """
    Get Stripe configuration for frontend.
    
    Returns publishable key and test mode status.
    No authentication required - publishable key is safe to expose.
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        operation_id='get_stripe_config',
        summary='Get Stripe configuration',
        description='Returns Stripe publishable key and test mode status for frontend initialization',
        tags=['Stripe'],
        responses={
            200: StripeConfigResponseSerializer,
        }
    )
    def get(self, request):
        """Return Stripe configuration for frontend."""
        data = {
            'publishable_key': StripeClient.get_publishable_key(),
            'test_mode': StripeClient.is_test_mode(),
        }
        serializer = StripeConfigResponseSerializer(data)
        return Response(serializer.data)


class CreatePaymentIntentView(APIView):
    """
    Create a Stripe PaymentIntent for an Order or Booking.
    
    Initiates payment flow by creating a Stripe PaymentIntent and returning
    the client secret for frontend payment collection.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        operation_id='create_payment_intent',
        summary='Create Stripe PaymentIntent',
        description=(
            'Creates a Stripe PaymentIntent for an Order or Booking. '
            'Returns client_secret for frontend payment collection with Stripe.js. '
            'Creates or reuses existing Payment record.'
        ),
        tags=['Stripe'],
        request=CreatePaymentIntentSerializer,
        responses={
            201: PaymentIntentResponseSerializer,
            400: OpenApiResponse(
                response=ErrorResponseSerializer,
                description='Validation error or Stripe error'
            ),
            404: OpenApiResponse(
                response=ErrorResponseSerializer,
                description='Order or Booking not found'
            ),
            500: OpenApiResponse(
                response=ErrorResponseSerializer,
                description='Internal server error'
            ),
        },
        examples=[
            OpenApiExample(
                name='Create PaymentIntent for Order',
                value={
                    'target_type': 'order',
                    'target_id': 123,
                    'payment_method_id': 1
                },
                request_only=True,
            ),
            OpenApiExample(
                name='Create PaymentIntent for Booking',
                value={
                    'target_type': 'booking',
                    'target_id': 456
                },
                request_only=True,
            )
        ]
    )
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Create a Stripe PaymentIntent for an Order or Booking."""
        serializer = CreatePaymentIntentSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        target_object = serializer.validated_data['target_object']
        
        # Get or create payment
        payment = target_object.get_payment()
        if not payment:
            payment = self._create_payment_for_target(target_object, request.user)
        
        # Prepare metadata matching Stripe format
        metadata = payment.prepare_stripe_metadata()
        
        # Create PaymentIntent
        try:
            payment_intent = PaymentIntentService.create(
                amount=payment.base_amount,
                currency=payment.base_amount.currency.code,
                payment_reference=payment.payment_reference,
                metadata=metadata,
                customer_email=payment.user.email,
                customer_id=payment.stripe_customer_id,
                description=f"Payment for {payment.event.title}"
            )
            
            # Store PaymentIntent ID
            payment.stripe_payment_intent = payment_intent.id
            payment.transition_to(PaymentStatusChoices.PENDING)
            payment.save()
            
            # Return data for frontend
            return Response({
                'client_secret': payment_intent.client_secret,
                'payment_intent_id': payment_intent.id,
                'publishable_key': StripeClient.get_publishable_key(),
                'amount': str(payment.base_amount.amount),
                'currency': payment.base_amount.currency.code.lower(),
                'payment_reference': payment.payment_reference,
                'test_mode': StripeClient.is_test_mode(),
            }, status=status.HTTP_201_CREATED)
            
        except StripeServiceError as e:
            logger.error(f"Stripe error creating PaymentIntent: {e.message}")
            return Response(
                {'error': e.user_message, 'details': e.to_dict()},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception(f"Unexpected error creating PaymentIntent: {str(e)}")
            return Response(
                {'error': 'Payment processing error. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _create_payment_for_target(self, target, user):
        """Create a Payment object for the target entity."""
        from apps.payments.models import PaymentMethod, PaymentMethodTypeChoices
        
        # Get Stripe payment method for event
        payment_method = PaymentMethod.objects.filter(
            event=target.event,
            method_type=PaymentMethodTypeChoices.STRIPE,
            is_active=True
        ).first()
        
        if not payment_method:
            raise ValidationError("No active Stripe payment method configured for this event")
        
        # Create payment
        payment = Payment.objects.create(
            user=user,
            event=target.event,
            method=payment_method,
            base_amount=target.total_amount,
            status=PaymentStatusChoices.DRAFTING,
            target=target
        )
        
        return payment


class StripeConfirmPaymentView(APIView):
    """
    Manual confirmation endpoint for PaymentIntents.
    
    Typically not needed as frontend auto-confirms, but useful for
    server-side payment flows or debugging.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        operation_id='confirm_payment_intent',
        summary='Manually confirm PaymentIntent',
        description=(
            'Manually confirms a Stripe PaymentIntent. '
            'Usually not needed as Stripe.js auto-confirms payments. '
            'Use for server-side payment flows or debugging.'
        ),
        tags=['Stripe'],
        request=ConfirmPaymentIntentSerializer,
        responses={
            200: ConfirmPaymentIntentResponseSerializer,
            400: OpenApiResponse(
                response=ErrorResponseSerializer,
                description='Invalid request or Stripe error'
            ),
            404: OpenApiResponse(
                response=ErrorResponseSerializer,
                description='Payment not found or not owned by user'
            ),
            500: OpenApiResponse(
                response=ErrorResponseSerializer,
                description='Internal server error'
            ),
        }
    )
    def post(self, request):
        """
        Manually confirm a PaymentIntent.
        """
        serializer = ConfirmPaymentIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        payment_intent_id = serializer.validated_data['payment_intent_id']
        payment_method = serializer.validated_data.get('payment_method')
        
        try:
            # Verify payment belongs to user
            payment = Payment.objects.filter(
                stripe_payment_intent=payment_intent_id,
                user=request.user
            ).first()
            
            if not payment:
                return Response(
                    {'error': 'Payment not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Confirm payment intent
            payment_intent = PaymentIntentService.confirm(
                payment_intent_id=payment_intent_id,
                payment_method=payment_method
            )
            
            return Response({
                'status': 'success',
                'payment_intent': {
                    'id': payment_intent.id,
                    'status': payment_intent.status,
                    'client_secret': payment_intent.client_secret,
                }
            })
            
        except StripeServiceError as e:
            logger.error(f"Stripe error confirming payment: {str(e)}")
            return Response(
                {'error': e.user_message, 'details': e.to_dict()},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception(f"Error confirming payment intent: {str(e)}")
            return Response(
                {'error': 'Payment confirmation failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    operation_id='stripe_webhook',
    summary='Stripe webhook endpoint',
    description=(
        'Handles Stripe webhook events. This endpoint is called by Stripe, not by clients. '
        'Verifies webhook signature and processes events like payment_intent.succeeded, '
        'charge.refunded, etc. Must be publicly accessible (no authentication).'
    ),
    tags=['Stripe'],
    request={
        'application/json': {
            'type': 'object',
            'description': 'Stripe event payload (sent by Stripe)'
        }
    },
    responses={
        200: WebhookResponseSerializer,
        400: OpenApiResponse(
            response=ErrorResponseSerializer,
            description='Invalid signature or processing error'
        ),
        405: OpenApiResponse(
            response=ErrorResponseSerializer,
            description='Method not allowed (only POST accepted)'
        ),
        500: OpenApiResponse(
            response=ErrorResponseSerializer,
            description='Internal server error'
        ),
    },
    exclude=True  # Exclude from public API docs since it's webhook-only
)
@csrf_exempt
def stripe_webhook_view(request):
    """
    Handle Stripe webhook events.
    
    Verifies signature and processes events. Must be exempt from CSRF and
    authentication middleware for Stripe to access it.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    if not sig_header:
        logger.warning("Webhook received without signature header")
        return JsonResponse({'error': 'Missing signature'}, status=400)
    
    try:
        # Verify signature and construct event
        event = verify_webhook_signature(payload, sig_header)
        
        logger.info(f"Received webhook: {event.type} (id: {event.id})")
        
        # Process event
        result = process_webhook_event(event)
        
        return JsonResponse({
            'status': 'success',
            'event_id': event.id,
            'result': result
        })
        
    except StripeWebhookError as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return JsonResponse(
            {'error': str(e.message)},
            status=400
        )
    except Exception as e:
        logger.exception(f"Unexpected webhook error: {str(e)}")
        return JsonResponse(
            {'error': 'Webhook processing failed'},
            status=500
        )
