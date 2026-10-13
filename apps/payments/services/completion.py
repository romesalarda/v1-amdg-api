"""
Payment completion & fulfilment.

Explicit replacement for the former ``post_save(Payment)`` signal.

Flow
----
1. A producer (Stripe webhook, reconciliation, admin, staff endpoint, checkout)
   calls ``complete_payment(payment)`` — or, if it created/saved the payment as
   COMPLETED itself, ``schedule_payment_fulfilment(payment.pk)``.
2. Fulfilment is scheduled with ``transaction.on_commit`` so it only runs once
   the caller's transaction has committed.
3. ``fulfil_payment(pk)`` locks the payment row, checks the durable
   ``Payment.fulfilled_at`` marker, runs the target-specific processing in a
   savepoint and stamps ``fulfilled_at`` on success. The row lock makes it safe
   against concurrent workers (webhook vs. reconciliation vs. sweeper).
4. ``fulfil_outstanding_payments()`` (run periodically by Celery) retries any
   COMPLETED payment that was never fulfilled, e.g. because the process died
   between commit and the ``on_commit`` callback.

Failures flag ``metadata['requires_manual_review']`` and are excluded from the
sweeper; clear the flag to have a payment retried.

Business logic lives in:
  - apps.bookings.services.process_booking_payment  (Booking targets)
  - apps.products.services.OrderPaymentProcessor    (Order targets)
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.payments.models import Payment, PaymentStatusChoices, PaymentMethodTypeChoices

from apps.bookings.models import Booking
from apps.bookings.services import (
    finalize_from_payment,
    process_booking_payment,
    should_create_tickets_for_payment,
)
from apps.organisations.models import EventSponsor
from apps.payments.models import Donation
from apps.products.models import Order
from apps.products.services import process_order_payment
from apps.common.models.verification import VerificationStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def complete_payment(payment: Payment) -> Payment:
    """
    Transition ``payment`` to COMPLETED (validated) and schedule fulfilment.

    Raises ``django.core.exceptions.ValidationError`` for invalid transitions
    (e.g. bank transfer without verified evidence), exactly like
    ``Payment.transition_to``.
    """
    payment.transition_to(PaymentStatusChoices.COMPLETED)
    schedule_payment_fulfilment(payment.pk)
    return payment


def schedule_payment_fulfilment(payment_pk: int) -> None:
    """Run ``fulfil_payment`` after the current transaction commits."""
    transaction.on_commit(lambda: fulfil_payment(payment_pk))


def fulfil_payment(payment_pk: int) -> bool:
    """
    Run post-completion processing for a COMPLETED payment, exactly once.

    Returns True if this call fulfilled the payment, False if it was skipped
    (not completed, already fulfilled, missing) or failed.
    """
    with transaction.atomic():
        try:
            payment = (
                Payment.objects.select_for_update(of=('self',))
                .select_related('method')
                .get(pk=payment_pk)
            )
        except Payment.DoesNotExist:
            logger.error("fulfil_payment: Payment pk=%s not found.", payment_pk)
            return False

        if payment.status != PaymentStatusChoices.COMPLETED:
            return False
        if payment.fulfilled_at is not None:
            logger.debug("Payment %s already fulfilled. Skipping.", payment.payment_reference)
            return False

        try:
            with transaction.atomic():
                _run_fulfilment(payment)
        except Exception as e:
            logger.error(
                "Failed to fulfil payment %s: %s", payment.payment_reference, e, exc_info=True
            )
            _mark_requires_review(payment_pk, str(e))
            # Do not re-raise: the payment is already committed; raising would
            # surface a 500 to webhook callers with no benefit.
            return False

        Payment.objects.filter(pk=payment_pk).update(fulfilled_at=timezone.now())
        return True


def fulfil_outstanding_payments(min_age_minutes: int = 5, batch_size: int = 100) -> dict:
    """
    Retry COMPLETED payments that were never fulfilled.

    Payments flagged ``requires_manual_review`` are skipped. A minimum age avoids
    racing the normal ``on_commit`` path for payments that just completed.
    """
    cutoff = timezone.now() - timedelta(minutes=min_age_minutes)
    candidates = (
        Payment.objects.filter(
            status=PaymentStatusChoices.COMPLETED,
            fulfilled_at__isnull=True,
            updated_at__lt=cutoff,
        )
        .order_by('updated_at')
        .values_list('pk', flat=True)[:batch_size]
    )

    found = fulfilled = 0
    for pk in list(candidates):
        found += 1
        payment_meta = Payment.objects.filter(pk=pk).values_list('metadata', flat=True).first()
        if (payment_meta or {}).get('requires_manual_review'):
            continue
        if fulfil_payment(pk):
            fulfilled += 1
    return {'found': found, 'fulfilled': fulfilled}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _run_fulfilment(payment: Payment) -> None:
    """Deferred finalisation, auto-processing gate and target dispatch."""
    # Phase 1: deferred booking finalisation (two-phase checkout).
    if payment.target is None and (payment.metadata or {}).get('checkout_intent_id'):
        result = finalize_from_payment(payment)
        if result.get('booking'):
            # finalize_from_payment writes target_type/target_id; refetch to see them.
            payment = Payment.objects.select_related('method').get(pk=payment.pk)
            logger.info(
                "Finalized deferred checkout payment %s into booking %s",
                payment.payment_reference,
                result['booking'].booking_reference,
            )

    # Phase 2: auto-processing gate.
    if not should_create_tickets_for_payment(payment):
        logger.info(
            "Skipping auto-processing for payment %s with method %s",
            payment.payment_reference,
            payment.method.method_type if payment.method else 'None',
        )
        return

    # Phase 3: dispatch on target type.
    target = payment.target
    if isinstance(target, Booking):
        process_booking_payment(payment, target)
    elif isinstance(target, Order):
        process_order_payment(payment, target)
    elif isinstance(target, Donation):
        _handle_donation_payment(payment, target)
    elif isinstance(target, EventSponsor):
        _handle_sponsorship_payment(payment, target)
    elif target is None:
        logger.info(
            "Payment %s completed with no target (likely standalone). No action required.",
            payment.payment_reference,
        )
    else:
        logger.warning(
            "Payment %s has unexpected target type: %s. No action taken.",
            payment.payment_reference,
            type(target).__name__,
        )


def _handle_donation_payment(payment: Payment, donation) -> None:
    """
    Auto-verify donations once the provider has confirmed funds.
    Bank-transfer donations still need manual evidence review.
    """

    if payment.method and payment.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
        logger.info(
            "Bank-transfer payment completed for donation %s (payment %s). Awaiting admin verification.",
            donation.tracking_reference,
            payment.payment_reference,
        )
        return

    if donation.verification_status != VerificationStatus.VERIFIED:
        donation.verification_status = VerificationStatus.VERIFIED
        donation.save(update_fields=['verification_status'])
        logger.info(
            "Auto-verified donation %s after payment %s completed.",
            donation.tracking_reference,
            payment.payment_reference,
        )


def _handle_sponsorship_payment(payment: Payment, sponsor) -> None:
    """Queue the sponsorship confirmation email once the transaction commits."""
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


def _mark_requires_review(payment_pk: int, error: str) -> None:
    """Flag the payment; uses a queryset update so no model save logic runs."""
    current = Payment.objects.filter(pk=payment_pk).values_list('metadata', flat=True).first()
    Payment.objects.filter(pk=payment_pk).update(
        metadata={
            **(current or {}),
            'processing_error': error,
            'requires_manual_review': True,
        }
    )
