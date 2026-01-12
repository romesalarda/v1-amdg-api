"""
Payment signals

Handles automatic actions when payments change state.
"""
import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.payments.models import Payment, PaymentStatusChoices
from apps.bookings.services import TicketCreatorService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Payment)
def handle_payment_completion(sender, instance, created, **kwargs):
    """
    Handle post-payment actions based on payment target type.
    
    This handler supports multiple target types:
    - Booking: Creates tickets for attendees
    - Order: Transitions order to processing (based on event settings)
    - None/Other: Logs informational message (e.g., donations)
    
    All operations are atomic - if any step fails, changes are rolled back.
    
    Args:
        sender: Payment model class
        instance: Payment instance that was saved
        created: Boolean indicating if this is a new instance
        **kwargs: Additional signal arguments
    """
    from apps.bookings.models import Booking
    from apps.products.models import Order, OrderStatusChoices
    from apps.events.models import EventNotification, NotificationTypeChoices, NotificationPriorityChoices
    
    # Only process completed payments
    if instance.status != PaymentStatusChoices.COMPLETED:
        return
    
    # Check if we should auto-process this payment method
    if not TicketCreatorService.should_create_tickets_for_payment(instance):
        logger.info(
            f"Skipping auto-processing for payment {instance.payment_reference} "
            f"with method {instance.method.method_type if instance.method else 'None'}"
        )
        return
    
    target = instance.target
    
    # Handle different target types
    try:
        with transaction.atomic():
            if isinstance(target, Booking):
                _handle_booking_payment(instance, target)
            elif isinstance(target, Order):
                _handle_order_payment(instance, target)
            elif target is None:
                _handle_null_target_payment(instance)
            else:
                logger.warning(
                    f"Payment {instance.payment_reference} has unexpected target type: "
                    f"{type(target).__name__}. No action taken."
                )
    except Exception as e:
        logger.error(
            f"Signal handler: Failed to process payment {instance.payment_reference}: {str(e)}",
            exc_info=True
        )
        # Don't raise - we don't want to break the payment save
        # Manual intervention or retry mechanism can handle failures


def _handle_booking_payment(payment: Payment, booking) -> None:
    """
    Handle payment completion for Booking targets.
    
    Creates tickets for all attendees and processes any related orders
    (from booking packages with products).
    
    Args:
        payment: Completed payment instance
        booking: Booking associated with the payment
    """
    from apps.events.models import EventNotification, NotificationTypeChoices, NotificationPriorityChoices
    from apps.products.models import OrderStatusChoices
    from apps.bookings.services.ticket_creator import TicketCreationError
    
    # 1. Create tickets for the booking (if metadata is present)
    try:
        tickets = TicketCreatorService.create_tickets_for_payment(payment)
        logger.info(
            f"Created {len(tickets)} tickets for booking {booking.booking_reference} "
            f"(payment {payment.payment_reference})"
        )
    except TicketCreationError as e:
        # Ticket creation failed due to missing/invalid metadata or other issues
        # Log error but don't fail the entire payment processing
        logger.warning(
            f"Could not auto-create tickets for booking {booking.booking_reference}: {str(e)}. "
            f"Tickets may need to be created manually or payment metadata is incomplete."
        )
        # Continue processing - tickets might be created manually later
    except Exception as e:
        logger.error(
            f"Unexpected error creating tickets for booking {booking.booking_reference}: {str(e)}",
            exc_info=True
        )
        # Don't re-raise - continue with order processing
    
    # 2. Handle related orders (from booking packages with products)
    related_orders = booking.get_related_orders()
    
    if related_orders.exists():
        event = booking.event
        event_settings = getattr(event, 'settings', None)
        
        # Check if orders should be auto-processed
        auto_process = (
            event_settings and 
            not event_settings.orders_require_approval
        )
        
        for order in related_orders:
            if auto_process:
                # Automatically transition to processing
                try:
                    if order.can_transition_to(OrderStatusChoices.PROCESSING):
                        order.transition_to(OrderStatusChoices.PROCESSING)
                        logger.info(
                            f"Auto-transitioned order {order.order_reference_id} to PROCESSING "
                            f"(booking {booking.booking_reference})"
                        )
                        
                        # Create fulfillment notification
                        EventNotification.objects.create(
                            event=event,
                            notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
                            priority=NotificationPriorityChoices.NORMAL,
                            related_payment=payment,
                            related_order=order,
                            related_booking=booking,
                            metadata={
                                'message': f'Order {order.order_reference_id} ready for fulfillment',
                                'auto_processed': True,
                                'booking_reference': booking.booking_reference,
                            }
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to transition order {order.order_reference_id}: {str(e)}",
                        exc_info=True
                    )
                    raise
            else:
                # Requires manual approval - create notification
                EventNotification.objects.create(
                    event=event,
                    notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
                    priority=NotificationPriorityChoices.HIGH,
                    related_payment=payment,
                    related_order=order,
                    related_booking=booking,
                    metadata={
                        'message': f'Order {order.order_reference_id} requires approval before processing',
                        'auto_processed': False,
                        'requires_approval': True,
                        'booking_reference': booking.booking_reference,
                    }
                )
                logger.info(
                    f"Created approval notification for order {order.order_reference_id} "
                    f"(event requires manual approval)"
                )


def _handle_order_payment(payment: Payment, order) -> None:
    """
    Handle payment completion for standalone Order targets.
    
    Transitions order to processing status (if event settings allow)
    and creates notifications for admin fulfillment.
    
    Args:
        payment: Completed payment instance
        order: Order associated with the payment
    """
    from apps.events.models import EventNotification, NotificationTypeChoices, NotificationPriorityChoices
    from apps.products.models import OrderStatusChoices
    
    event = order.event
    if not event:
        logger.warning(
            f"Order {order.order_reference_id} has no associated event. Cannot determine settings."
        )
        return
    
    event_settings = getattr(event, 'settings', None)
    
    # Check if orders should be auto-processed
    auto_process = (
        event_settings and 
        not event_settings.orders_require_approval
    )
    
    if auto_process:
        # Automatically transition to processing
        try:
            if order.can_transition_to(OrderStatusChoices.PROCESSING):
                order.transition_to(OrderStatusChoices.PROCESSING)
                logger.info(
                    f"Auto-transitioned standalone order {order.order_reference_id} to PROCESSING"
                )
                
                # Create fulfillment notification
                EventNotification.objects.create(
                    event=event,
                    notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
                    priority=NotificationPriorityChoices.NORMAL,
                    related_payment=payment,
                    related_order=order,
                    metadata={
                        'message': f'Order {order.order_reference_id} ready for fulfillment',
                        'auto_processed': True,
                        'standalone_order': True,
                    }
                )
        except Exception as e:
            logger.error(
                f"Failed to transition order {order.order_reference_id}: {str(e)}",
                exc_info=True
            )
            raise
    else:
        # Requires manual approval - create notification
        EventNotification.objects.create(
            event=event,
            notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
            priority=NotificationPriorityChoices.HIGH,
            related_payment=payment,
            related_order=order,
            metadata={
                'message': f'Order {order.order_reference_id} requires approval before processing',
                'auto_processed': False,
                'requires_approval': True,
                'standalone_order': True,
            }
        )
        logger.info(
            f"Created approval notification for order {order.order_reference_id} "
            f"(event requires manual approval)"
        )


def _handle_null_target_payment(payment: Payment) -> None:
    """
    Handle payment completion for null targets (e.g., donations).
    
    Args:
        payment: Completed payment instance with no target
    """
    logger.info(
        f"Payment {payment.payment_reference} completed with no target "
        f"(likely a donation or standalone payment). No action required."
    )
