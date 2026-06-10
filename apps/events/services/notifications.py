
from apps.events.models import EventNotification
from apps.events.models.notifications import NotificationPriorityChoices, NotificationTypeChoices

from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from apps.bookings.models import Booking
    from apps.products.models import Order
    from apps.payments.models import Payment
    from apps.events.models import Event

def create_notification(
    payment: "Payment",
    locked_order: "Order",
    booking: "Booking",
    event: "Event",
    message: str,
    metadata: Dict[str, Any],
    priority: str = NotificationPriorityChoices.NORMAL,
    notif_type: str = NotificationTypeChoices.GENERAL
) -> EventNotification:
    '''
    Create or update an event notification.

    Args:
        payment (Payment): The related payment instance.
        locked_order (Order): The related order instance.
        booking (Booking): The related booking instance.
        event (Event): The related event instance.
        metadata (Dict[str, Any]): Additional metadata for the notification.

    Returns:
        EventNotification: The created or updated event notification instance.
    '''
    if metadata.get('message') is None:
        metadata['message'] = message

    new_notification, created = EventNotification.objects.get_or_create(
        notification_type=notif_type,
        related_payment=payment,
        related_order=locked_order,
        defaults=dict(
            event=event,
            priority=priority,
            related_booking=booking,
            metadata=metadata,
        ),
    )

    if not created:
        # Update metadata if notification already exists
        new_notification.metadata.update(metadata)
        new_notification.save()

    return new_notification