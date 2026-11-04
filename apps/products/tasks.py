"""
Celery tasks for the products app.

All order-related background jobs are defined here so that the
task registry is cleanly separated from service logic.
"""
import logging

from celery import shared_task
from django.utils import timezone

from apps.products.services import email as email_service
from apps.products.models import Order, OPEN_ORDER_STATUSES

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_confirmation_email(self, order_pk: int, payment_pk: int) -> str:
    """
    Send the 'Order Confirmed' email after a standalone order payment completes.

    Dispatched via ``transaction.on_commit`` from ``OrderPaymentProcessor.process``
    after the payment signal confirms the order.  Runs for standalone orders only
    (booking-linked orders are covered by ``send_booking_confirmation_email``).

    Retries up to 3 times (60-second intervals) on unexpected errors.
    Email delivery failures (SMTP errors) are logged but do not trigger
    a retry — send_templated_email already logs those internally.

    Args:
        order_pk:   Integer primary key of the Order instance.
        payment_pk: Integer primary key of the Payment instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info(
        "send_order_confirmation_email: order_pk=%s payment_pk=%s",
        order_pk,
        payment_pk,
    )
    try:
        success = email_service.send_order_confirmation(order_pk, payment_pk)
        if success:
            return f"order confirmation email sent | order_pk={order_pk}"
        return (
            f"order confirmation email skipped (no recipient or missing record) "
            f"| order_pk={order_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_order_confirmation_email: unexpected error for "
            "order_pk=%s payment_pk=%s",
            order_pk,
            payment_pk,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_pending_bank_transfer_email(self, order_pk: int, payment_pk: int) -> str:
    """
    Send the 'Order Received — awaiting bank transfer' email.

    Dispatched via ``transaction.on_commit`` from the ``checkout`` action in
    ``OrderViewSet`` immediately after the bank transfer payment is created and
    linked to the order, before admin verification of the transfer.

    Retries up to 3 times (60-second intervals) on unexpected errors.

    Args:
        order_pk:   Integer primary key of the Order instance.
        payment_pk: Integer primary key of the Payment instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info(
        "send_order_pending_bank_transfer_email: order_pk=%s payment_pk=%s",
        order_pk,
        payment_pk,
    )
    try:
        success = email_service.send_order_pending_bank_transfer(order_pk, payment_pk)
        if success:
            return f"order pending bank transfer email sent | order_pk={order_pk}"
        return (
            f"order pending bank transfer email skipped (no recipient or missing record) "
            f"| order_pk={order_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_order_pending_bank_transfer_email: unexpected error for "
            "order_pk=%s payment_pk=%s",
            order_pk,
            payment_pk,
        )
        raise self.retry(exc=exc)


@shared_task(name='products.expire_order_hold')
def expire_order_hold(order_pk: int) -> str:
    """Expire a single order whose stock hold has lapsed (no-op if extended or paid)."""

    order = Order.objects.filter(pk=order_pk).first()
    if order is None or not order.is_expired:
        return f"order hold not expired | order_pk={order_pk}"
    expired = order.expire()
    return f"order hold {'expired' if expired else 'kept'} | order_pk={order_pk}"


@shared_task(name='products.expire_order_holds')
def expire_order_holds() -> dict:
    """Periodic sweep: cancel unpaid orders whose hold has lapsed and release their stock."""

    now = timezone.now()
    candidates = Order.objects.filter(
        status__in=OPEN_ORDER_STATUSES,
        expires_at__isnull=False,
        expires_at__lte=now,
    )
    expired = 0
    for order in candidates.iterator():
        try:
            if order.expire():
                expired += 1
        except Exception:
            logger.exception("expire_order_holds: failed to expire order_pk=%s", order.pk)
    if expired:
        logger.info("expire_order_holds: expired %s order(s)", expired)
    return {'expired': expired, 'timestamp': now.isoformat()}
