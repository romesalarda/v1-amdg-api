"""
Order payment processor service.

Handles all post-payment actions for standalone Order targets (i.e. orders
whose payment target is the order directly, not via a booking). Lives in the
products app so payment-specific knowledge does not leak into apps.payments.
"""
import logging

from django.db import transaction

from apps.products.tasks import send_order_confirmation_email

logger = logging.getLogger(__name__)


class OrderPaymentProcessor:
    """
    Processes completed payments whose target is a standalone Order.

    Responsibilities:
    - Transition the order to PROCESSING (or notify for manual approval),
      honouring the event's ``orders_require_approval`` setting.

    All work is expected to run inside a ``transaction.atomic()`` block
    initiated by the caller (signal handler via ``on_commit``).
    """

    @classmethod
    def process(cls, payment, order) -> None:
        """
        Execute all post-payment actions for a standalone order payment.

        Args:
            payment: Completed Payment instance.
            order:   Order instance that is the payment target.

        Raises:
            Exception: Any unexpected error is re-raised after logging.
        """
        from apps.products.models import Order, OrderStatusChoices
        from apps.events.models import EventNotification, NotificationTypeChoices, NotificationPriorityChoices

        event = order.attendee.event if order.attendee else None
        if not event:
            logger.error(
                f"Order {order.order_reference_id} has no associated event. "
                "Cannot determine settings for post-payment processing."
            )
            raise ValueError(
                f"Order {order.order_reference_id} cannot be processed because attendee/event context is missing."
            )

        event_settings = getattr(event, 'settings', None)

        # Both booking-related and standalone orders use the same setting:
        # ``orders_require_approval``. Auto-process when approval is NOT required.
        auto_process = bool(
            event_settings and not event_settings.orders_require_approval
        )

        # Acquire a row lock before checking transition eligibility.
        locked_order = Order.objects.select_for_update().get(pk=order.pk)

        if auto_process:
            if locked_order.can_transition_to(OrderStatusChoices.PROCESSING):
                locked_order.transition_to(OrderStatusChoices.PROCESSING)
                logger.info(
                    f"Auto-transitioned standalone order {locked_order.order_reference_id} to PROCESSING"
                )

            EventNotification.objects.get_or_create(
                notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
                related_payment=payment,
                related_order=locked_order,
                defaults=dict(
                    event=event,
                    priority=NotificationPriorityChoices.NORMAL,
                    metadata={
                        'message': f'Order {locked_order.order_reference_id} ready for fulfillment',
                        'auto_processed': True,
                        'standalone_order': True,
                    },
                ),
            )
        else:
            EventNotification.objects.get_or_create(
                notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
                related_payment=payment,
                related_order=locked_order,
                defaults=dict(
                    event=event,
                    priority=NotificationPriorityChoices.HIGH,
                    metadata={
                        'message': (
                            f'Order {locked_order.order_reference_id} requires approval before processing'
                        ),
                        'auto_processed': False,
                        'requires_approval': True,
                        'standalone_order': True,
                    },
                ),
            )
            logger.info(
                f"Created approval notification for order {locked_order.order_reference_id} "
                f"(event requires manual approval)"
            )

        # Queue order confirmation email for both auto-processed and manual-approval paths.
        # Payment is confirmed in both cases; the customer is notified immediately.
        _order_pk = locked_order.pk
        _payment_pk = payment.pk
        transaction.on_commit(
            lambda: send_order_confirmation_email.delay(_order_pk, _payment_pk)
        )
        logger.info(
            "Queued order confirmation email for order %s (payment %s)",
            locked_order.order_reference_id,
            payment.payment_reference,
        )
