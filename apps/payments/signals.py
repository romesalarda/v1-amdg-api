"""
Payment signals

Handles automatic actions when payments change state.

Architecture note
-----------------
The signal handler is intentionally thin: it validates preconditions and
schedules work via ``transaction.on_commit`` so side-effects only execute
after the outer DB transaction commits. All business logic lives in
dedicated service classes in their respective apps:

  - apps.bookings.services.BookingPaymentProcessor  (Booking targets)
  - apps.products.services.OrderPaymentProcessor    (standalone Order targets)
"""
import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.payments.models import Payment, PaymentStatusChoices, PaymentMethodTypeChoices
from apps.bookings.services import (
    TicketCreatorService,
    BookingCheckoutFinalizer,
    CheckoutFinalizationError,
)

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Payment)
def handle_payment_completion(sender, instance, created, **kwargs):
    """
    Schedule post-payment processing via transaction.on_commit.

    Only COMPLETED payments are processed. A ``signal_processed`` flag in
    ``metadata`` prevents double-processing if the payment row is saved again
    after completion (e.g. Stripe webhook attaching charge IDs, admin edits).

    The actual work is deferred to ``_process_completed_payment`` so that
    side-effects (ticket creation, order transitions, notifications) only run
    after the caller's DB transaction has fully committed.
    """
    if instance.status != PaymentStatusChoices.COMPLETED:
        return

    # Guard: skip re-saves of already-processed payments.
    # Use update_fields as a fast-path: if this save didn't touch 'status'
    # it cannot be a new COMPLETED transition (still guarded by the metadata
    # flag below for callers that omit update_fields).
    update_fields = kwargs.get('update_fields')
    if update_fields is not None and 'status' not in update_fields:
        return

    if (instance.metadata or {}).get('signal_processed'):
        logger.debug(
            f"Payment {instance.payment_reference} already signal-processed. Skipping."
        )
        return

    payment_pk = instance.pk
    transaction.on_commit(lambda: _process_completed_payment(payment_pk))


# ---------------------------------------------------------------------------
# Core processor — executes after the outer transaction commits
# ---------------------------------------------------------------------------

def _process_completed_payment(payment_pk: int) -> None:
    """
    Fetch the payment fresh from the database and run all post-completion logic.

    Fetching fresh avoids stale GenericForeignKey descriptor caches and ensures
    we see the fully committed state (including any target set by
    BookingCheckoutFinalizer).
    """
    try:
        payment = Payment.objects.select_related('method').get(pk=payment_pk)
    except Payment.DoesNotExist:
        logger.error(f"_process_completed_payment: Payment pk={payment_pk} not found.")
        return

    # Re-check status after commit — it could have changed between the signal
    # firing and this callback running.
    if payment.status != PaymentStatusChoices.COMPLETED:
        return

    # Re-check idempotency guard after re-fetch (covers concurrent workers).
    if (payment.metadata or {}).get('signal_processed'):
        logger.debug(
            f"Payment {payment.payment_reference} already signal-processed (post-commit check). Skipping."
        )
        return

    # ------------------------------------------------------------------
    # Phase 1: Deferred booking finalization (two-phase checkout)
    # ------------------------------------------------------------------
    if payment.target is None and (payment.metadata or {}).get('checkout_intent_id'):
        try:
            result = BookingCheckoutFinalizer.finalize_from_payment(payment)
            booking = result.get('booking')
            if booking:
                # Re-fetch to get the updated target after finalization.
                # finalize_from_payment sets target_type/target_id inside its
                # own atomic block; we need a fresh instance to see those writes.
                payment = Payment.objects.select_related('method').get(pk=payment_pk)
                logger.info(
                    f"Finalized deferred checkout payment {payment.payment_reference} "
                    f"into booking {booking.booking_reference}"
                )
        except CheckoutFinalizationError as e:
            logger.error(
                f"Failed deferred checkout finalization for payment {payment.payment_reference}: {e}",
                exc_info=True,
            )
            _mark_requires_review(payment, str(e))
            return
        except Exception as e:
            logger.error(
                f"Unexpected deferred finalization error for payment {payment.payment_reference}: {e}",
                exc_info=True,
            )
            _mark_requires_review(payment, str(e))
            return

    # ------------------------------------------------------------------
    # Phase 2: Auto-processing gate
    # ------------------------------------------------------------------
    if not TicketCreatorService.should_create_tickets_for_payment(payment):
        logger.info(
            f"Skipping auto-processing for payment {payment.payment_reference} "
            f"with method {payment.method.method_type if payment.method else 'None'}"
        )
        _mark_signal_processed(payment)
        return

    # ------------------------------------------------------------------
    # Phase 3: Dispatch to the appropriate processor
    # ------------------------------------------------------------------
    from apps.bookings.models import Booking
    from apps.products.models import Order
    from apps.payments.models import Donation
    from apps.organisations.models import EventSponsor
    from apps.bookings.services import BookingPaymentProcessor
    from apps.products.services import OrderPaymentProcessor

    target = payment.target

    try:
        with transaction.atomic():
            if isinstance(target, Booking):
                BookingPaymentProcessor.process(payment, target)
            elif isinstance(target, Order):
                OrderPaymentProcessor.process(payment, target)
            elif isinstance(target, Donation):
                _handle_donation_payment(payment, target)
            elif isinstance(target, EventSponsor):
                _handle_sponsorship_payment(payment, target)
            elif target is None:
                logger.info(
                    f"Payment {payment.payment_reference} completed with no target "
                    "(likely a donation or standalone payment). No action required."
                )
            else:
                logger.warning(
                    f"Payment {payment.payment_reference} has unexpected target type: "
                    f"{type(target).__name__}. No action taken."
                )
    except Exception as e:
        logger.error(
            f"Failed to process payment {payment.payment_reference}: {e}",
            exc_info=True,
        )
        _mark_requires_review(payment, str(e))
        # Do not re-raise — the payment row is already committed; raising here
        # would surface a 500 to the webhook caller with no benefit.
        return

    _mark_signal_processed(payment)


# ---------------------------------------------------------------------------
# Donation handler (remains in payments app — target type is local)
# ---------------------------------------------------------------------------

def _handle_donation_payment(payment: Payment, donation) -> None:
    """
    Handle payment completion for Donation targets.

    For Stripe (and other immediately-confirmed) payments the funds are confirmed
    by the payment provider, so the donation is auto-verified.
    Bank-transfer donations still require admin review before being marked verified
    because the evidence must be checked manually.
    """
    from apps.common.models.verification import VerificationStatus

    if payment.method and payment.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
        logger.info(
            f"Bank-transfer payment completed for donation {donation.tracking_reference} "
            f"(payment {payment.payment_reference}). Awaiting admin verification."
        )
        return

    # Stripe / Cash / Free — payment provider already confirmed funds; auto-verify.
    if donation.verification_status != VerificationStatus.VERIFIED:
        donation.verification_status = VerificationStatus.VERIFIED
        donation.save(update_fields=['verification_status'])
        logger.info(
            f"Auto-verified donation {donation.tracking_reference} "
            f"after payment {payment.payment_reference} completed."
        )


# ---------------------------------------------------------------------------
# Sponsorship handler (organisations app target)
# ---------------------------------------------------------------------------

def _handle_sponsorship_payment(payment: Payment, sponsor) -> None:
    """
    Handle payment completion for EventSponsor targets.

    Dispatches a confirmation email to the user who initiated the checkout.
    The email task is scheduled via transaction.on_commit so it fires only
    after the enclosing atomic block commits.
    """
    from apps.organisations.tasks import send_sponsorship_payment_confirmation_email

    sponsor_pk = sponsor.pk
    payment_pk = payment.pk
    transaction.on_commit(
        lambda: send_sponsorship_payment_confirmation_email.delay(sponsor_pk, payment_pk)
    )
    logger.info(
        "Queued sponsorship confirmation email for sponsor pk=%s payment %s",
        sponsor_pk,
        payment.payment_reference,
    )


# ---------------------------------------------------------------------------
# Metadata helpers — use .update() to avoid recursive signal firing
# ---------------------------------------------------------------------------

def _mark_signal_processed(payment: Payment) -> None:
    Payment.objects.filter(pk=payment.pk).update(
        metadata={**(payment.metadata or {}), 'signal_processed': True}
    )


def _mark_requires_review(payment: Payment, error: str) -> None:
    Payment.objects.filter(pk=payment.pk).update(
        metadata={
            **(payment.metadata or {}),
            'processing_error': error,
            'requires_manual_review': True,
        }
    )

