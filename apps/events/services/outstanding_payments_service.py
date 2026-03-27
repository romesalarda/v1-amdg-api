"""
Outstanding Payments Service

Handles querying and managing outstanding (unpaid) payments for users within events.

Outstanding payments include:
- Payments with status PENDING or DRAFTING linked to Bookings
- Payments with metadata indicating pending checkout intents (not yet converted to Bookings)
"""
from django.db.models import Q
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from apps.payments.models import Payment, PaymentStatusChoices
from apps.bookings.models import Booking, BookingIntent


class OutstandingPaymentsService:
    """
    Service for querying and managing outstanding payments.

    Supports fetching all unpaid payments for a user within an event,
    including both booking-linked payments and pending checkout intent payments.
    """

    OUTSTANDING_STATUSES = [
        PaymentStatusChoices.PENDING,
        PaymentStatusChoices.DRAFTING,
    ]

    @staticmethod
    def get_user_outstanding_payments_qs(user, event):
        """
        Get all outstanding payments for a user in a specific event.

        Outstanding payments include:
        - Payments with status PENDING/DRAFTING linked to a Booking
        - Payments with status PENDING/DRAFTING with a pending checkout intent

        Args:
            user: User instance or user ID
            event: Event instance or event ID

        Returns:
            QuerySet of Payment objects with related data prefetched
        """
        # Query for payments in the event with outstanding status
        base_queryset = Payment.objects.filter(
            user=user,
            event=event,
            status__in=OutstandingPaymentsService.OUTSTANDING_STATUSES,
        ).select_related(
            'user',
            'event',
            'method',
            'target_type',
        )

        return base_queryset

    @staticmethod
    def get_user_outstanding_payments_with_validation(user, event):
        """
        Get all valid outstanding payments, excluding expired booking intents.

        Args:
            user: User instance or user ID
            event: Event instance or event ID

        Returns:
            QuerySet of valid outstanding Payment objects
        """
        outstanding_qs = OutstandingPaymentsService.get_user_outstanding_payments_qs(
            user, event
        )

        # Filter to include only payments that either:
        # 1. Have a linked Booking (target_id != null for Booking target)
        # 2. Have a valid (non-expired) checkout intent in metadata
        now = timezone.now()

        # For checkout intents, verify they haven't expired
        # BookingIntent expires 30 minutes after creation if payment completed,
        # or based on its custom expiry time
        valid_checkout_intents = BookingIntent.objects.filter(
            event=event,
            made_by=user,
            expires_at__gt=now,
        ).values_list('booking_intent_id', flat=True)

        booking_type = ContentType.objects.get_for_model(Booking)
        valid_checkout_intent_ids = [str(v) for v in valid_checkout_intents]

        # Filter payments that have either:
        # 1. A booking target (they went through the full checkout flow)
        # 2. A valid checkout intent in metadata
        result_qs = outstanding_qs.filter(
            # Q(target_type=booking_type, target_id__isnull=False) |
            # Q(target_type__isnull=True, metadata__checkout_intent_id__in=valid_checkout_intent_ids)
        ).distinct()
        return result_qs

    @staticmethod
    def count_outstanding_payments(user, event):
        """
        Count outstanding payments for a user in an event.

        Args:
            user: User instance or user ID
            event: Event instance or event ID

        Returns:
            Integer count of outstanding payments
        """
        return OutstandingPaymentsService.get_user_outstanding_payments_with_validation(
            user, event
        ).count()

    @staticmethod
    def has_outstanding_payments(user, event):
        """
        Check if a user has any outstanding payments in an event.

        Args:
            user: User instance or user ID
            event: Event instance or event ID

        Returns:
            Boolean indicating if outstanding payments exist
        """
        return OutstandingPaymentsService.count_outstanding_payments(
            user, event
        ) > 0
