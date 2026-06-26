"""
Booking payment processor service.

Handles all post-payment actions for Booking targets: ticket creation and
related order dispatch. Lives in the bookings app so payment-specific
knowledge does not leak into apps.payments.
"""
import logging

from django.db import transaction

from apps.bookings.tasks import (
    send_booking_confirmation_email,
)
from apps.bookings.models import Booking
from apps.payments.models import Payment
from apps.events.models import EventNotification, NotificationTypeChoices, NotificationPriorityChoices

from apps.bookings.services.ticket_creator import TicketCreatorService, TicketCreationError

logger = logging.getLogger(__name__)

class BookingPaymentProcessor:
    """
    Processes completed payments whose target is a Booking.

    Responsibilities:
    - Create tickets for all attendees via TicketCreatorService.
    - Transition or notify for related orders (from booking packages with
      products), honouring the event's ``orders_require_approval`` setting.

    All work is expected to run inside a ``transaction.atomic()`` block
    initiated by the caller (signal handler via ``on_commit``).
    """

    @classmethod
    def process(cls, payment: Payment, booking: Booking) -> None:
        """
        Execute all post-payment actions for a booking payment.

        Args:
            payment: Completed Payment instance.
            booking: Booking instance that is the payment target.

        Raises:
            TicketCreationError: If ticket creation fails (propagated so the
                atomic block in the caller can roll back).
            Exception: Any unexpected error is re-raised after logging.
        """
        cls._create_tickets(payment, booking)
        cls._handle_related_orders(payment, booking)

        # Dispatch the booking confirmation email (with ticket QR cards) after
        # the enclosing atomic block commits so the task always sees committed data.
        _booking_pk = booking.pk
        _payment_pk = payment.pk
        transaction.on_commit(
            lambda: send_booking_confirmation_email.delay(_booking_pk, _payment_pk)
        )
        logger.info(
            "Queued booking confirmation email for booking %s (payment %s)",
            booking.booking_reference,
            payment.payment_reference,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _create_tickets(cls, payment: Payment, booking: Booking) -> None:
        '''
        Create tickets for all attendees in the booking via TicketCreatorService.

        Args:
            payment: Completed Payment instance.
            booking: Booking instance that is the payment target.

        Raises:
            TicketCreationError: If ticket creation fails (propagated so the
                atomic block in the caller can roll back).
            Exception: Any unexpected error is re-raised after logging.
        '''
        try:
            tickets = TicketCreatorService.create_tickets_for_payment(payment)
            logger.info(
                f"Created {len(tickets)} tickets for booking {booking.booking_reference} "
                f"(payment {payment.payment_reference})"
            )
        except TicketCreationError:
            # Re-raise: the caller's atomic block must roll back so order
            # transitions don't proceed without tickets.
            raise
        except Exception:
            logger.error(
                f"Unexpected error creating tickets for booking {booking.booking_reference}",
                exc_info=True,
            )
            raise

    @classmethod
    def _handle_related_orders(cls, payment: Payment, booking: Booking) -> None:
        '''
        Handle related orders for a booking after payment is completed.

        Args:
            payment: Completed Payment instance.
            booking: Booking instance that is the payment target.
        '''
        from apps.products.models import Order, OrderStatusChoices

        related_orders = booking.get_related_orders()
        if not related_orders.exists():
            return

        event = booking.event
        event_settings = getattr(event, 'settings', None)

        # Auto-process when orders do NOT require approval.
        auto_process = bool(
            event_settings and not event_settings.orders_require_approval
        )

        for order in related_orders:
            # Acquire a row lock before checking transition eligibility to
            # prevent a race with concurrent webhook deliveries.
            locked_order = Order.objects.select_for_update().get(pk=order.pk)

            if auto_process:
                if locked_order.can_transition_to(OrderStatusChoices.PROCESSING):
                    locked_order.transition_to(OrderStatusChoices.PROCESSING)
                    logger.info(
                        f"Auto-transitioned order {locked_order.order_reference_id} to PROCESSING "
                        f"(booking {booking.booking_reference})"
                    )

                EventNotification.objects.get_or_create(
                    notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
                    related_payment=payment,
                    related_order=locked_order,
                    defaults=dict(
                        event=event,
                        priority=NotificationPriorityChoices.NORMAL,
                        related_booking=booking,
                        metadata={
                            'message': f'Order {locked_order.order_reference_id} ready for fulfillment',
                            'auto_processed': True,
                            'booking_reference': booking.booking_reference,
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
                        related_booking=booking,
                        metadata={
                            'message': (
                                f'Order {locked_order.order_reference_id} requires approval before processing'
                            ),
                            'auto_processed': False,
                            'requires_approval': True,
                            'booking_reference': booking.booking_reference,
                        },
                    ),
                )
                logger.info(
                    f"Created approval notification for order {locked_order.order_reference_id} "
                    f"(event requires manual approval)"
                )
