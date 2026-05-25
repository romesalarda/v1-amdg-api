"""
Celery tasks for the products app.

All order-related background jobs are defined here so that the
task registry is cleanly separated from service logic.
"""
import logging

from celery import shared_task

from apps.products.email_service import OrderEmailService

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
        success = OrderEmailService.send_order_confirmation(order_pk, payment_pk)
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
        success = OrderEmailService.send_order_pending_bank_transfer(order_pk, payment_pk)
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
