"""
Stripe payment reconciliation and webhook retry tasks.

Handles cases where webhooks are missed or delayed:
- Reconcile individual payment status with Stripe
- Periodic sync of stale pending payments
- Exponential backoff retry mechanism
"""
from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
import stripe

from apps.payments.models import Payment, PaymentStatusChoices, PaymentHistoryAction
from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.payment_intents import PaymentIntentService
from apps.payments.services.stripe.exceptions import StripeServiceError

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,  # Start with 60 seconds
    autoretry_for=(StripeServiceError,),
)
def reconcile_stripe_payment(self, payment_id: str):
    """
    Reconcile a single payment's status with Stripe.
    
    Queries Stripe API to get current PaymentIntent status and updates
    local Payment record if webhook was missed.
    
    Args:
        payment_id: Payment.payment_id (UUID) to reconcile
        
    Retries:
        - 5 attempts with exponential backoff
        - Delays: 60s, 120s, 240s, 480s, 960s
    """
    StripeClient.initialize()
    
    try:
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(payment_id=payment_id)
            
            # Only reconcile payments with Stripe PaymentIntent
            if not payment.stripe_payment_intent:
                logger.warning(f"Payment {payment.payment_reference} has no Stripe PaymentIntent")
                return {'status': 'skipped', 'reason': 'no_payment_intent'}
            
            # Don't reconcile completed/refunded/cancelled payments
            if payment.status in [
                PaymentStatusChoices.COMPLETED,
                PaymentStatusChoices.REFUNDED,
                PaymentStatusChoices.CANCELLED
            ]:
                return {'status': 'skipped', 'reason': 'already_final'}
            
            # Retrieve current status from Stripe
            try:
                payment_intent = PaymentIntentService.retrieve(payment.stripe_payment_intent)
            except StripeServiceError as e:
                logger.error(f"Failed to retrieve PaymentIntent {payment.stripe_payment_intent}: {e.message}")
                # Retry with exponential backoff
                raise self.retry(
                    exc=e,
                    countdown=int(60 * (2 ** self.request.retries))
                )
            
            stripe_status = payment_intent.status
            logger.info(
                f"Reconciling Payment {payment.payment_reference}: "
                f"DB status={payment.status}, Stripe status={stripe_status}"
            )
            
            # Map Stripe status to our status
            status_changed = False
            new_status = None
            
            if stripe_status == 'succeeded' and payment.status != PaymentStatusChoices.COMPLETED:
                new_status = PaymentStatusChoices.COMPLETED
                status_changed = True
                
                # Update charge ID if available
                if hasattr(payment_intent, 'latest_charge') and payment_intent.latest_charge:
                    charge_id = payment_intent.latest_charge if isinstance(payment_intent.latest_charge, str) else payment_intent.latest_charge.id
                    payment.stripe_charge_id = charge_id
            
            elif stripe_status in ['canceled', 'cancelled'] and payment.status != PaymentStatusChoices.CANCELLED:
                new_status = PaymentStatusChoices.CANCELLED
                status_changed = True
            
            elif stripe_status in ['processing', 'requires_capture'] and payment.status not in [
                PaymentStatusChoices.PENDING,
                PaymentStatusChoices.COMPLETED
            ]:
                # Payment is processing in Stripe
                new_status = PaymentStatusChoices.PENDING
                status_changed = True
            
            elif stripe_status in ['requires_payment_method', 'requires_action'] and payment.status == PaymentStatusChoices.FAILED:
                # Already marked as failed, don't change
                pass
            
            if status_changed and new_status:
                payment.transition_to(new_status)
                payment.save()
                
                # Log reconciliation
                PaymentHistoryAction.objects.create(
                    payment=payment,
                    action='stripe_reconciliation',
                    performed_by=None,
                    metadata={
                        'task_id': self.request.id,
                        'stripe_status': stripe_status,
                        'previous_status': payment.status,
                        'new_status': new_status,
                        'payment_intent_id': payment.stripe_payment_intent,
                        'reconciliation_time': str(timezone.now()),
                    },
                    description=f"Status reconciled with Stripe: {payment.status} -> {new_status}"
                )
                
                logger.info(
                    f"Reconciled Payment {payment.payment_reference}: "
                    f"{payment.status} -> {new_status}"
                )
                
                return {
                    'status': 'updated',
                    'payment_reference': payment.payment_reference,
                    'previous_status': payment.status,
                    'new_status': new_status
                }
            
            return {
                'status': 'no_change',
                'payment_reference': payment.payment_reference,
                'current_status': payment.status
            }
            
    except Payment.DoesNotExist:
        logger.error(f"Payment {payment_id} not found")
        return {'status': 'error', 'reason': 'payment_not_found'}
    
    except Exception as e:
        logger.exception(f"Unexpected error reconciling payment {payment_id}: {str(e)}")
        # Don't retry on unexpected errors
        return {'status': 'error', 'reason': str(e)}


@shared_task
def sync_stale_pending_payments(max_age_minutes: int = 30, batch_size: int = 50):
    """
    Find and reconcile stale PENDING payments.
    
    Queries for payments that have been in PENDING status for longer than
    max_age_minutes and triggers reconciliation with Stripe.
    
    Args:
        max_age_minutes: Age threshold for considering a payment stale
        batch_size: Maximum number of payments to process in one run
        
    Returns:
        dict: Summary of reconciliation results
    """
    StripeClient.initialize()
    
    cutoff_time = timezone.now() - timedelta(minutes=max_age_minutes)
    
    # Find stale pending payments with Stripe PaymentIntent
    stale_payments = Payment.objects.filter(
        status=PaymentStatusChoices.PENDING,
        updated_at__lt=cutoff_time,
        stripe_payment_intent__isnull=False
    ).order_by('updated_at')[:batch_size]
    
    count = stale_payments.count()
    
    if count == 0:
        logger.info("No stale pending payments found")
        return {
            'status': 'success',
            'stale_payments_found': 0,
            'reconciliations_triggered': 0
        }
    
    logger.info(f"Found {count} stale pending payments older than {max_age_minutes} minutes")
    
    # Trigger reconciliation for each payment
    reconciliation_tasks = []
    for payment in stale_payments:
        task = reconcile_stripe_payment.delay(str(payment.payment_id))
        reconciliation_tasks.append(task.id)
        logger.info(f"Triggered reconciliation for Payment {payment.payment_reference} (task: {task.id})")
    
    return {
        'status': 'success',
        'stale_payments_found': count,
        'reconciliations_triggered': len(reconciliation_tasks),
        'task_ids': reconciliation_tasks
    }


@shared_task
def reconcile_payment_by_reference(payment_reference: str):
    """
    Reconcile a payment by its reference ID.
    
    Convenience task for manual reconciliation by payment reference.
    
    Args:
        payment_reference: Payment.payment_reference to reconcile
    """
    try:
        payment = Payment.objects.get(payment_reference=payment_reference)
        return reconcile_stripe_payment.delay(str(payment.payment_id))
    except Payment.DoesNotExist:
        logger.error(f"Payment {payment_reference} not found")
        return {'status': 'error', 'reason': 'payment_not_found'}
