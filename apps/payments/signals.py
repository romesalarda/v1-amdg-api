"""
Payment signals

Handles automatic actions when payments change state.
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.payments.models import Payment, PaymentStatusChoices
from apps.bookings.services import TicketCreatorService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Payment)
def handle_payment_completion(sender, instance, created, **kwargs):
    """
    Auto-create tickets when payment completes.
    
    This handler:
    1. Triggers on Payment status change to COMPLETED
    2. Checks if tickets should be auto-created (excludes BANK_TRANSFER)
    3. Calls TicketCreatorService to create tickets atomically
    4. Logs success or failures for auditing
    
    BANK_TRANSFER payments are excluded - tickets are created manually
    via the verify_bank_transfer endpoint after admin approval.
    """
    # Only process if payment is completed
    if instance.status != PaymentStatusChoices.COMPLETED:
        return
    
    # Check if we should auto-create tickets for this payment method
    if not TicketCreatorService.should_create_tickets_for_payment(instance):
        logger.info(
            f"Skipping auto-ticket creation for payment {instance.payment_reference} "
            f"with method {instance.method.method_type if instance.method else 'None'}"
        )
        return
    
    # Create tickets
    try:
        tickets = TicketCreatorService.create_tickets_for_payment(instance)
        logger.info(
            f"Signal handler: Created {len(tickets)} tickets for "
            f"payment {instance.payment_reference}"
        )
    except Exception as e:
        logger.error(
            f"Signal handler: Failed to create tickets for "
            f"payment {instance.payment_reference}: {str(e)}",
            exc_info=True
        )
        # Don't raise - we don't want to break the payment save
        # Tickets can be created manually or via retry mechanism
