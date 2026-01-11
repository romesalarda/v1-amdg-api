"""
Celery tasks for booking intent management and cleanup.

Tasks:
    - process_expired_booking_intents: Periodic task to expire and soft-delete intents
    - hard_delete_old_booking_intents: Periodic task to permanently delete old intents

Author: AMDG Platform Team
Version: 1.0.0
"""
from celery import shared_task
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


@shared_task(name='bookings.process_expired_booking_intents')
def process_expired_booking_intents():
    """
    Process expired booking intents.
    
    This task:
    1. Marks expired pending intents as EXPIRED
    2. Soft-deletes expired intents
    
    Runs periodically (recommended: every 5 minutes)
    """
    from apps.bookings.models import BookingIntent, BookingIntentStatusChoices
    
    now = timezone.now()
    
    # Find pending intents that have expired
    expired_intents = BookingIntent.objects.filter(
        status=BookingIntentStatusChoices.PENDING,
        expires_at__lte=now,
        deleted_at__isnull=True
    )
    
    count = expired_intents.count()
    
    if count > 0:
        # Mark them as expired
        for intent in expired_intents:
            intent.mark_expired(save=False)
        
        # Bulk update
        BookingIntent.objects.bulk_update(expired_intents, ['status'])
        
        # Soft delete them
        expired_intents.update(deleted_at=now)
        
        logger.info(f"Processed {count} expired booking intents")
    
    return {
        'processed': count,
        'timestamp': now.isoformat()
    }


@shared_task(name='bookings.hard_delete_old_booking_intents')
def hard_delete_old_booking_intents():
    """
    Permanently delete old booking intents that have passed their complete_delete_at date.
    
    This task permanently removes booking intents from the database after they have been
    soft-deleted and the retention period has passed.
    
    Runs periodically (recommended: daily)
    """
    from apps.bookings.models import BookingIntent
    
    now = timezone.now()
    
    # Find intents that should be permanently deleted
    old_intents = BookingIntent.objects.filter(
        complete_delete_at__lte=now,
        deleted_at__isnull=False  # Only delete already soft-deleted intents
    )
    
    count = old_intents.count()
    
    if count > 0:
        # Permanently delete
        old_intents.delete()
        logger.info(f"Hard deleted {count} old booking intents")
    
    return {
        'deleted': count,
        'timestamp': now.isoformat()
    }


@shared_task(name='bookings.cleanup_abandoned_intents')
def cleanup_abandoned_intents():
    """
    Clean up abandoned booking intents (optional task).
    
    This task finds pending intents that have been around longer than expected
    but haven't been properly marked as expired. This is a safety net.
    
    Runs periodically (recommended: hourly)
    """
    from apps.bookings.models import BookingIntent, BookingIntentStatusChoices
    
    now = timezone.now()
    
    # Find pending intents older than 1 hour (well past expiry time of 20 mins)
    abandoned_threshold = now - timezone.timedelta(hours=1)
    
    abandoned_intents = BookingIntent.objects.filter(
        status=BookingIntentStatusChoices.PENDING,
        created_at__lte=abandoned_threshold,
        deleted_at__isnull=True
    )
    
    count = abandoned_intents.count()
    
    if count > 0:
        # Mark as expired and soft delete
        for intent in abandoned_intents:
            intent.mark_expired(save=False)
        
        BookingIntent.objects.bulk_update(abandoned_intents, ['status'])
        abandoned_intents.update(deleted_at=now)
        
        logger.warning(f"Cleaned up {count} abandoned booking intents")
    
    return {
        'cleaned': count,
        'timestamp': now.isoformat()
    }


@shared_task(name='bookings.expire_specific_intent')
def expire_specific_intent(intent_id):
    """
    Expire a specific booking intent by ID.
    
    This task can be scheduled to run at the exact expiry time of an intent
    for immediate processing (alternative to periodic processing).
    
    Args:
        intent_id: UUID string of the booking intent to expire
    """
    from apps.bookings.models import BookingIntent, BookingIntentStatusChoices
    import uuid
    
    try:
        intent = BookingIntent.objects.get(
            booking_intent_id=uuid.UUID(intent_id),
            status=BookingIntentStatusChoices.PENDING
        )
        
        if intent.is_expired:
            intent.mark_expired(save=True)
            intent.deleted_at = timezone.now()
            intent.save(update_fields=['deleted_at'])
            
            logger.info(f"Expired booking intent {intent_id}")
            return {'success': True, 'intent_id': intent_id}
        else:
            return {'success': False, 'reason': 'Not yet expired', 'intent_id': intent_id}
            
    except BookingIntent.DoesNotExist:
        logger.warning(f"Booking intent {intent_id} not found or already processed")
        return {'success': False, 'reason': 'Not found', 'intent_id': intent_id}
