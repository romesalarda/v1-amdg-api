"""
Celery tasks for the organisations app.

All organisation-related background jobs are defined here so that the
task registry is cleanly separated from service logic.
"""
import logging

from celery import shared_task

from apps.organisations.services.email import SponsorshipEmailService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_sponsorship_payment_confirmation_email(self, sponsor_pk: int, payment_pk: int) -> str:
    """
    Send the sponsorship payment confirmation email.

    Dispatched after a sponsorship payment transitions to COMPLETED (both Stripe
    and bank-transfer verified paths), via transaction.on_commit in the payment
    signal handler.

    Retries up to 3 times (60-second intervals) on unexpected errors.
    Email delivery failures (SMTP errors) are logged but do not trigger
    a retry — send_templated_email already logs those internally.

    Args:
        sponsor_pk: Integer primary key of the EventSponsor instance.
        payment_pk: Integer primary key of the Payment instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info(
        "send_sponsorship_payment_confirmation_email: sponsor_pk=%s payment_pk=%s",
        sponsor_pk,
        payment_pk,
    )
    try:
        success = SponsorshipEmailService.send_sponsorship_payment_confirmation(
            sponsor_pk, payment_pk
        )
        if success:
            return f"sponsorship confirmation email sent | sponsor_pk={sponsor_pk}"
        return (
            f"sponsorship confirmation email skipped (no recipient or missing record)"
            f" | sponsor_pk={sponsor_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_sponsorship_payment_confirmation_email: unexpected error for"
            " sponsor_pk=%s payment_pk=%s",
            sponsor_pk,
            payment_pk,
        )
        raise self.retry(exc=exc)
