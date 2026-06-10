
from apps.events.models import EventNotification
from apps.events.models.notifications import NotificationPriorityChoices, NotificationTypeChoices

from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from apps.bookings.models import Booking
    from apps.products.models import Order
    from apps.payments.models import Payment
    from apps.events.models import Event

def create_notification(
    payment: "Payment" = None,
    locked_order: "Order" = None,
    booking: "Booking" = None,
    event: "Event" = None,
    message: str = "",
    metadata: Dict[str, Any] = None,
    priority: str = NotificationPriorityChoices.NORMAL,
    notification_type: str = NotificationTypeChoices.GENERAL,
    force_create: bool = False,
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
    if metadata is None:
        metadata = {}
    if metadata.get('message') is None:
        metadata['message'] = message
        
    if force_create:
        # Create a new notification regardless of existing ones
        new_notification = EventNotification.objects.create(
            event=event,
            priority=priority,
            related_payment=payment,
            related_order=locked_order,
            related_booking=booking,
            notification_type=notification_type,
            metadata=metadata,
        )
        return new_notification

    new_notification, created = EventNotification.objects.get_or_create(
        notification_type=notification_type,
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