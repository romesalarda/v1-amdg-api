"""
Event notification model for tracking admin/staff tasks and alerts.
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

User = get_user_model()


class NotificationTypeChoices(models.TextChoices):
    """Types of event notifications."""
    ORDER_FULFILLMENT = 'ORDER_FULFILLMENT', _('Order Fulfillment Required')
    BOOKING_CONFIRMATION = 'BOOKING_CONFIRMATION', _('Booking Confirmed')
    REFUND_REQUEST = 'REFUND_REQUEST', _('Refund Requested')
    PAYMENT_FAILED = 'PAYMENT_FAILED', _('Payment Failed')
    CAPACITY_WARNING = 'CAPACITY_WARNING', _('Capacity Warning')
    AUTHORIZATION_REQUEST = 'AUTHORIZATION_REQUEST', _('Authorization Request')
    GENERAL = 'GENERAL', _('General Notification')


class NotificationPriorityChoices(models.TextChoices):
    """Priority levels for notifications."""
    LOW = 'LOW', _('Low')
    NORMAL = 'NORMAL', _('Normal')
    HIGH = 'HIGH', _('High')
    URGENT = 'URGENT', _('Urgent')


class EventNotification(models.Model):
    """
    Notifications for event admins and staff about tasks requiring attention.
    
    Examples:
    - Order needs fulfillment after payment
    - Refund request pending approval
    - Capacity threshold reached
    - Manual verification required
    """
    
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text=_("Event this notification belongs to")
    )
    
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationTypeChoices.choices,
        default=NotificationTypeChoices.GENERAL
    )
    
    priority = models.CharField(
        max_length=20,
        choices=NotificationPriorityChoices.choices,
        default=NotificationPriorityChoices.NORMAL
    )
    
    # Related objects for context
    related_payment = models.ForeignKey(
        'payments.Payment',
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True,
        help_text=_("Payment associated with this notification")
    )
    
    related_order = models.ForeignKey(
        'products.Order',
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True,
        help_text=_("Order associated with this notification")
    )
    
    related_booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True,
        help_text=_("Booking associated with this notification")
    )
    
    # Notification state
    is_read = models.BooleanField(
        default=False,
        help_text=_("Whether this notification has been read/acknowledged")
    )
    
    # Metadata for rendering (flexible JSON storage)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional metadata for rendering notification content")
    )
    
    # Audit fields
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_notifications',
        help_text=_("User who triggered this notification (null for system-generated)")
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the notification was marked as read")
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event', 'is_read']),
            models.Index(fields=['notification_type', 'priority']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = 'Event Notification'
        verbose_name_plural = 'Event Notifications'
    
    def __str__(self):
        return f"{self.get_notification_type_display()} - {self.event.title}"
    
    def __repr__(self):
        return f"<EventNotification {self.id} type={self.notification_type} event={self.event.display_code}>"
    
    def clean(self):
        """Validate at least one related object exists for non-general notifications."""
        if self.notification_type != NotificationTypeChoices.GENERAL:
            if not any([self.related_payment, self.related_order, self.related_booking]):
                raise ValidationError(
                    "Non-general notifications must have at least one related object "
                    "(payment, order, or booking)."
                )
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def mark_as_read(self):
        """Mark notification as read with timestamp."""
        from django.utils import timezone
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=['is_read', 'read_at'])
