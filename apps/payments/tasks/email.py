"""
Celery tasks for the payments app — transactional email.

Dispatches refund confirmation emails after a RefundRequest reaches
PROCESSED status.  All tasks follow the shared conventions:
  - bind=True  (access self.retry)
  - max_retries=3, default_retry_delay=60
  - Model imports inside the function body to prevent circular imports
  - Return a human-readable status string for Celery result inspection
"""
import logging

from celery import shared_task

from apps.payments.services.email_service import RefundEmailService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_refund_email(self, refund_request_pk: int) -> str:
    """
    Send the refund confirmation email once a RefundRequest is PROCESSED.

    Detects whether the payment is a booking payment or a standalone order
    payment and dispatches the appropriate email template.

    Dispatched via ``transaction.on_commit`` from:
      - ``RefundRequestViewSet.process()`` (bank-transfer / manual path)
      - ``ChargeRefundedHandler.handle()`` (Stripe webhook path)

    Retries up to 3 times (60-second intervals) on unexpected errors.
    Email delivery failures (SMTP errors) are logged but do not trigger
    a retry — send_templated_email already logs those internally.

    Args:
        refund_request_pk: Integer primary key of the RefundRequest instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info("send_refund_email: refund_request_pk=%s", refund_request_pk)
    try:
        from apps.payments.models import RefundRequest
        from apps.payments.services.attendee_refunds import AttendeeRefundService

        try:
            refund_request = RefundRequest.objects.select_related("payment").get(
                pk=refund_request_pk
            )
        except RefundRequest.DoesNotExist:
            logger.error(
                "send_refund_email: RefundRequest pk=%s not found", refund_request_pk
            )
            return f"skipped (RefundRequest not found) | pk={refund_request_pk}"

        payment = refund_request.payment
        is_booking = AttendeeRefundService.is_booking_payment(payment)

        if is_booking:
            success = RefundEmailService.send_booking_refund(refund_request_pk)
            label = "booking refund"
        else:
            success = RefundEmailService.send_order_refund(refund_request_pk)
            label = "order refund"

        if success:
            return f"{label} email sent | refund_pk={refund_request_pk}"
        return (
            f"{label} email skipped (no recipient or missing record) "
            f"| refund_pk={refund_request_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_refund_email: unexpected error for refund_request_pk=%s",
            refund_request_pk,
        )
        raise self.retry(exc=exc)
