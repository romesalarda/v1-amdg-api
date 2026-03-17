"""
Stripe webhook event handlers.

Processes Stripe webhook events to update Payment and RefundRequest statuses.
Implements event handlers for payment intents, charges, and disputes.
"""
import stripe
from typing import Dict, Callable, Optional
import logging
from django.db import transaction

from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.exceptions import StripeWebhookError

logger = logging.getLogger(__name__)


class WebhookEventHandler:
    """
    Base class for webhook event handlers.
    
    Event handlers should inherit from this and implement the handle() method.
    """
    
    def __init__(self, event: stripe.Event):
        self.event = event
        self.event_type = event.type
        self.event_id = event.id
        self.data = event.data.object
    
    def handle(self) -> Dict:
        """
        Process the webhook event.
        
        Returns:
            Dict: Result of processing with 'status' and optional 'message'
        """
        raise NotImplementedError("Subclasses must implement handle()")
    
    def log_event(self, message: str, level: str = 'info'):
        """Log event processing with context."""
        log_func = getattr(logger, level)
        log_func(f"[{self.event_type}:{self.event_id}] {message}")


class PaymentIntentSucceededHandler(WebhookEventHandler):
    """Handle payment_intent.succeeded events."""
    
    def handle(self) -> Dict:
        """
        Mark Payment as COMPLETED when PaymentIntent succeeds.
        
        Updates:
        - Payment.status -> COMPLETED
        - Payment.stripe_charge_id (from latest charge)
        - PaymentHistoryAction (status change log)
        - Related Order/Booking status
        """
        from apps.payments.models import Payment, PaymentStatusChoices, PaymentHistoryAction
        
        payment_intent_id = self.data.id
        charge_id = None
        
        # Extract charge ID from latest charge
        if hasattr(self.data, 'latest_charge') and self.data.latest_charge:
            charge_id = self.data.latest_charge if isinstance(self.data.latest_charge, str) else self.data.latest_charge.id
        
        try:
            with transaction.atomic():
                # Find payment by PaymentIntent ID
                payment = Payment.objects.select_for_update().filter(
                    stripe_payment_intent=payment_intent_id
                ).first()
                
                if not payment:
                    self.log_event(
                        f"Payment not found for PaymentIntent {payment_intent_id}",
                        level='warning'
                    )
                    return {'status': 'ignored', 'message': 'Payment not found'}
                
                # Check if already processed (idempotency)
                if payment.status == PaymentStatusChoices.COMPLETED:
                    self.log_event(f"Payment {payment.payment_reference} already completed", level='info')
                    return {'status': 'already_processed', 'payment_id': str(payment.payment_id)}
                
                # Store processed event IDs to prevent duplicate processing
                if not payment.metadata:
                    payment.metadata = {}
                
                event_ids = payment.metadata.get('stripe_event_ids', [])
                if self.event_id in event_ids:
                    self.log_event(f"Event {self.event_id} already processed", level='info')
                    return {'status': 'already_processed', 'payment_id': str(payment.payment_id)}
                
                event_ids.append(self.event_id)
                payment.metadata['stripe_event_ids'] = event_ids
                
                # Update charge ID if available
                if charge_id:
                    payment.stripe_charge_id = charge_id
                
                # Transition to COMPLETED
                payment.transition_to(PaymentStatusChoices.COMPLETED)
                payment.save()
                
                # Log history
                PaymentHistoryAction.objects.create(
                    payment=payment,
                    action='webhook_payment_succeeded',
                    performed_by=None,  # System action
                    metadata={
                        'event_id': self.event_id,
                        'payment_intent_id': payment_intent_id,
                        'charge_id': charge_id,
                        'amount': str(self.data.amount_received),
                        'currency': self.data.currency,
                    }
                )
                
                self.log_event(
                    f"Payment {payment.payment_reference} marked as COMPLETED "
                    f"(charge: {charge_id})",
                    level='info'
                )
                
                # Update related entity (Order/Booking) status if needed
                if payment.target:
                    self._update_target_status(payment)
                
                return {
                    'status': 'success',
                    'payment_id': str(payment.payment_id),
                    'payment_reference': payment.payment_reference
                }
                
        except Exception as e:
            self.log_event(f"Error processing event: {str(e)}", level='error')
            logger.exception(f"Failed to process payment_intent.succeeded: {str(e)}")
            raise StripeWebhookError(
                message=f"Failed to process webhook: {str(e)}",
                user_message="Payment processing error"
            )
    
    def _update_target_status(self, payment):
        """Update related Order or Booking status after successful payment."""
        try:
            target = payment.target

            from apps.organisations.models import EventSponsor
            
            # Handle Order
            if hasattr(target, 'status') and hasattr(target, 'transition_to'):
                from apps.products.models import OrderStatusChoices
                if target.status in ['DRAFT', 'PENDING']:
                    target.transition_to(OrderStatusChoices.PROCESSING)
                    target.save()
                    self.log_event(f"Updated {target.__class__.__name__} {target.pk} to PROCESSING")
            
            # Handle Booking - tickets are created separately, status managed elsewhere

            if isinstance(target, EventSponsor):
                if not target.is_verified:
                    target.mark_verified(verifier=None)
                if not target.is_processed:
                    target.mark_processed(processor=None)
                self.log_event(f"Updated EventSponsor {target.pk} to official paid sponsor")
            
        except Exception as e:
            self.log_event(f"Failed to update target status: {str(e)}", level='warning')


class PaymentIntentPaymentFailedHandler(WebhookEventHandler):
    """Handle payment_intent.payment_failed events."""
    
    def handle(self) -> Dict:
        """Mark Payment as FAILED when PaymentIntent fails."""
        from apps.payments.models import Payment, PaymentStatusChoices, PaymentHistoryAction
        
        payment_intent_id = self.data.id
        error_message = None
        
        # Extract error details
        if hasattr(self.data, 'last_payment_error') and self.data.last_payment_error:
            error_message = self.data.last_payment_error.get('message', 'Unknown error')
        
        try:
            with transaction.atomic():
                payment = Payment.objects.select_for_update().filter(
                    stripe_payment_intent=payment_intent_id
                ).first()
                
                if not payment:
                    self.log_event(
                        f"Payment not found for PaymentIntent {payment_intent_id}",
                        level='warning'
                    )
                    return {'status': 'ignored', 'message': 'Payment not found'}
                
                # Check idempotency
                if payment.status == PaymentStatusChoices.FAILED:
                    return {'status': 'already_processed', 'payment_id': str(payment.payment_id)}
                
                # Store event ID
                if not payment.metadata:
                    payment.metadata = {}
                event_ids = payment.metadata.get('stripe_event_ids', [])
                if self.event_id in event_ids:
                    return {'status': 'already_processed'}
                event_ids.append(self.event_id)
                payment.metadata['stripe_event_ids'] = event_ids
                
                # Transition to FAILED
                payment.transition_to(PaymentStatusChoices.FAILED)
                payment.save()
                
                # Log history
                PaymentHistoryAction.objects.create(
                    payment=payment,
                    action='webhook_payment_failed',
                    performed_by=None,
                    metadata={
                        'event_id': self.event_id,
                        'payment_intent_id': payment_intent_id,
                        'error_message': error_message,
                    }
                )
                
                self.log_event(
                    f"Payment {payment.payment_reference} marked as FAILED: {error_message}",
                    level='warning'
                )
                
                return {
                    'status': 'success',
                    'payment_id': str(payment.payment_id),
                    'error': error_message
                }
                
        except Exception as e:
            self.log_event(f"Error processing event: {str(e)}", level='error')
            logger.exception(f"Failed to process payment_intent.payment_failed: {str(e)}")
            raise StripeWebhookError(
                message=f"Failed to process webhook: {str(e)}"
            )


class PaymentIntentCanceledHandler(WebhookEventHandler):
    """Handle payment_intent.canceled events."""
    
    def handle(self) -> Dict:
        """Mark Payment as CANCELLED when PaymentIntent is canceled."""
        from apps.payments.models import Payment, PaymentStatusChoices, PaymentHistoryAction
        
        payment_intent_id = self.data.id
        cancellation_reason = getattr(self.data, 'cancellation_reason', None)
        
        try:
            with transaction.atomic():
                payment = Payment.objects.select_for_update().filter(
                    stripe_payment_intent=payment_intent_id
                ).first()
                
                if not payment:
                    return {'status': 'ignored', 'message': 'Payment not found'}
                
                if payment.status == PaymentStatusChoices.CANCELLED:
                    return {'status': 'already_processed'}
                
                # Store event ID
                if not payment.metadata:
                    payment.metadata = {}
                event_ids = payment.metadata.get('stripe_event_ids', [])
                if self.event_id in event_ids:
                    return {'status': 'already_processed'}
                event_ids.append(self.event_id)
                payment.metadata['stripe_event_ids'] = event_ids
                
                # Transition to CANCELLED
                payment.transition_to(PaymentStatusChoices.CANCELLED)
                payment.save()
                
                # Log history
                PaymentHistoryAction.objects.create(
                    payment=payment,
                    action='webhook_payment_canceled',
                    performed_by=None,
                    metadata={
                        'event_id': self.event_id,
                        'payment_intent_id': payment_intent_id,
                        'cancellation_reason': cancellation_reason,
                    }
                )
                
                self.log_event(
                    f"Payment {payment.payment_reference} marked as CANCELLED",
                    level='info'
                )
                
                return {'status': 'success', 'payment_id': str(payment.payment_id)}
                
        except Exception as e:
            self.log_event(f"Error processing event: {str(e)}", level='error')
            raise StripeWebhookError(message=f"Failed to process webhook: {str(e)}")


class ChargeRefundedHandler(WebhookEventHandler):
    """Handle charge.refunded events."""
    
    def handle(self) -> Dict:
        """
        Mark RefundRequest as PROCESSED when refund succeeds.
        
        Updates:
        - RefundRequest.status -> PROCESSED
        - RefundRequest.metadata['stripe_refund_id']
        - Payment.status -> REFUNDED (if full refund)
        - Restore stock if applicable
        """
        from apps.payments.models import Payment, PaymentStatusChoices, RefundRequest
        from apps.common.models.verification import VerificationStatus
        
        charge_id = self.data.id
        refunds = self.data.refunds.data if hasattr(self.data.refunds, 'data') else []
        
        try:
            with transaction.atomic():
                # Find payment by charge ID
                payment = Payment.objects.select_for_update().filter(
                    stripe_charge_id=charge_id
                ).first()
                
                if not payment:
                    self.log_event(
                        f"Payment not found for Charge {charge_id}",
                        level='warning'
                    )
                    return {'status': 'ignored', 'message': 'Payment not found'}
                
                # Process each refund
                for refund_data in refunds:
                    refund_id = refund_data.id
                    refund_amount = refund_data.amount  # in cents
                    refund_status = refund_data.status  # succeeded, pending, failed, canceled
                    
                    if refund_status != 'succeeded':
                        continue
                    
                    # Find RefundRequest by payment and mark as processed
                    # Match by amount or link via metadata
                    refund_request = RefundRequest.objects.filter(
                        payment=payment,
                        is_active=True,
                        status=VerificationStatus.VERIFIED
                    ).first()
                    
                    if refund_request:
                        # Store Stripe refund ID
                        if not refund_request.metadata:
                            refund_request.metadata = {}
                        refund_request.metadata['stripe_refund_id'] = refund_id
                        refund_request.metadata['stripe_event_id'] = self.event_id
                        
                        # Mark as processed
                        refund_request.mark_processed()
                        refund_request.save()
                        
                        self.log_event(
                            f"RefundRequest {refund_request.refund_reference} marked as PROCESSED",
                            level='info'
                        )
                
                # Check if payment should be marked as refunded
                total_refunded = sum(r.amount for r in refunds if r.status == 'succeeded')
                payment_amount_cents = int(payment.base_amount.amount * 100)
                
                if total_refunded >= payment_amount_cents:
                    # Full refund
                    if payment.status != PaymentStatusChoices.REFUNDED:
                        payment.transition_to(PaymentStatusChoices.PENDING_REFUND)
                        payment.transition_to(PaymentStatusChoices.REFUNDED)
                        payment.save()
                        
                        self.log_event(
                            f"Payment {payment.payment_reference} marked as REFUNDED",
                            level='info'
                        )
                
                return {
                    'status': 'success',
                    'payment_id': str(payment.payment_id),
                    'refunds_processed': len(refunds)
                }
                
        except Exception as e:
            self.log_event(f"Error processing event: {str(e)}", level='error')
            logger.exception(f"Failed to process charge.refunded: {str(e)}")
            raise StripeWebhookError(message=f"Failed to process webhook: {str(e)}")


class ChargeDisputeCreatedHandler(WebhookEventHandler):
    """Handle charge.dispute.created events."""
    
    def handle(self) -> Dict:
        """
        Log dispute creation in PaymentHistoryAction.
        
        Disputes require manual review - notifies admins via history action.
        """
        from apps.payments.models import Payment, PaymentHistoryAction
        
        dispute_data = self.data
        charge_id = dispute_data.charge
        dispute_id = dispute_data.id
        reason = dispute_data.reason
        amount = dispute_data.amount
        
        try:
            payment = Payment.objects.filter(stripe_charge_id=charge_id).first()
            
            if not payment:
                self.log_event(
                    f"Payment not found for disputed Charge {charge_id}",
                    level='warning'
                )
                return {'status': 'ignored', 'message': 'Payment not found'}
            
            # Create history action for admin review
            PaymentHistoryAction.objects.create(
                payment=payment,
                action='dispute_created',
                performed_by=None,
                metadata={
                    'event_id': self.event_id,
                    'dispute_id': dispute_id,
                    'charge_id': charge_id,
                    'reason': reason,
                    'amount': amount,
                    'evidence_details': dispute_data.evidence_details if hasattr(dispute_data, 'evidence_details') else None,
                }
            )
            
            self.log_event(
                f"Dispute created for Payment {payment.payment_reference}: {reason}",
                level='warning'
            )
            
            # TODO: Send notification to admins
            
            return {
                'status': 'success',
                'payment_id': str(payment.payment_id),
                'dispute_id': dispute_id
            }
            
        except Exception as e:
            self.log_event(f"Error processing event: {str(e)}", level='error')
            raise StripeWebhookError(message=f"Failed to process webhook: {str(e)}")


# Event handler registry
EVENT_HANDLERS: Dict[str, Callable] = {
    'payment_intent.succeeded': PaymentIntentSucceededHandler,
    'payment_intent.payment_failed': PaymentIntentPaymentFailedHandler,
    'payment_intent.canceled': PaymentIntentCanceledHandler,
    'charge.refunded': ChargeRefundedHandler,
    'charge.dispute.created': ChargeDisputeCreatedHandler,
}


def process_webhook_event(event: stripe.Event) -> Dict:
    """
    Process a Stripe webhook event.
    
    Args:
        event: Validated Stripe Event object
        
    Returns:
        Dict: Processing result with status
        
    Raises:
        StripeWebhookError: If processing fails
    """
    event_type = event.type
    
    handler_class = EVENT_HANDLERS.get(event_type)
    
    if not handler_class:
        logger.info(f"No handler for event type: {event_type}. Ignoring.")
        return {'status': 'ignored', 'message': f'No handler for {event_type}'}
    
    handler = handler_class(event)
    result = handler.handle()
    
    return result


def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
    """
    Verify Stripe webhook signature and construct Event.
    
    Args:
        payload: Raw request body bytes
        sig_header: Stripe-Signature header value
        
    Returns:
        stripe.Event: Verified event object
        
    Raises:
        StripeWebhookError: If signature verification fails
    """
    webhook_secret = StripeClient.get_webhook_secret()
    
    if not webhook_secret:
        raise StripeWebhookError(
            message="Webhook secret not configured",
            user_message="Webhook processing error"
        )
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        return event
        
    except ValueError as e:
        # Invalid payload
        raise StripeWebhookError(
            message=f"Invalid payload: {str(e)}",
            user_message="Invalid webhook payload"
        )
    except Exception as e:
        # Invalid signature or other error
        # Catch any exception from construct_event (including mocked errors in tests)
        if 'signature' in str(e).lower() or e.__class__.__name__ == 'SignatureVerificationError':
            raise StripeWebhookError(
                message=f"Signature verification failed: {str(e)}",
                user_message="Webhook signature verification failed"
            )
        raise StripeWebhookError(
            message=f"Webhook processing error: {str(e)}",
            user_message="Webhook processing error"
        )
