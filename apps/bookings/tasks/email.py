"""
Celery tasks for the bookings app.

All booking-related background jobs are defined here so that the
task registry is cleanly separated from service logic.
"""
import logging

from celery import shared_task

from apps.bookings.email_service import BookingEmailService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_booking_confirmation_email(self, booking_pk: int, payment_pk: int) -> str:
    """
    Send the 'You're In!' booking confirmation email with per-attendee ticket QR cards.

    Dispatched immediately after ticket creation commits to the database,
    both for Stripe direct-confirmation and bank-transfer-verified paths
    (both routes flow through BookingPaymentProcessor.process).

    Retries up to 3 times (60-second intervals) on unexpected errors.
    Email delivery failures (SMTP errors) are logged but do not trigger
    a retry — send_templated_email already logs those internally.

    Args:
        booking_pk: Integer primary key of the Booking instance.
        payment_pk: Integer primary key of the Payment instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info(
        "send_booking_confirmation_email: booking_pk=%s payment_pk=%s",
        booking_pk,
        payment_pk,
    )
    try:
        success = BookingEmailService.send_booking_confirmation(booking_pk, payment_pk)
        if success:
            return f"confirmation email sent | booking_pk={booking_pk}"
        return f"confirmation email skipped (no recipient or missing record) | booking_pk={booking_pk}"
    except Exception as exc:
        logger.exception(
            "send_booking_confirmation_email: unexpected error for booking_pk=%s payment_pk=%s",
            booking_pk,
            payment_pk,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_booking_pending_bank_transfer_email(self, booking_pk: int, payment_pk: int) -> str:
    """
    Send the 'Booking received, awaiting bank transfer' email.

    Dispatched immediately after the booking is created during bank-transfer
    checkout (before the payment is verified by an administrator).

    Retries up to 3 times (60-second intervals) on unexpected errors.

    Args:
        booking_pk: Integer primary key of the Booking instance.
        payment_pk: Integer primary key of the Payment instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info(
        "send_booking_pending_bank_transfer_email: booking_pk=%s payment_pk=%s",
        booking_pk,
        payment_pk,
    )
    try:
        success = BookingEmailService.send_booking_pending_bank_transfer(
            booking_pk, payment_pk
        )
        if success:
            return f"pending bank transfer email sent | booking_pk={booking_pk}"
        return (
            f"pending bank transfer email skipped (no recipient or missing record) "
            f"| booking_pk={booking_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_booking_pending_bank_transfer_email: unexpected error for "
            "booking_pk=%s payment_pk=%s",
            booking_pk,
            payment_pk,
        )
        raise self.retry(exc=exc)
