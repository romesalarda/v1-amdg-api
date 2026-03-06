"""
Celery tasks for managing event status transitions.
"""
from celery import shared_task
from django.utils import timezone
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)


@shared_task(name='events.mark_completed_events')
def mark_completed_events():
    """
    Mark events as COMPLETED when their end_datetime has passed.
    
    This task should be run periodically (e.g., hourly or daily) to 
    automatically transition events that have ended to COMPLETED status.
    
    Returns:
        dict: Summary of updated events with counts and event codes
    """
    from apps.events.models import Event, EventStatusChoices
    
    now = timezone.now()
    
    # Find events that have ended but are not yet marked as completed
    # Exclude terminal states: COMPLETED, CANCELLED, DELETED, ARCHIVED
    eligible_events = Event.objects.filter(
        end_datetime__lt=now
    ).exclude(
        status__in=[
            EventStatusChoices.COMPLETED,
            EventStatusChoices.CANCELLED,
            EventStatusChoices.DELETED,
            EventStatusChoices.ARCHIVED
        ]
    )
    
    updated_count = 0
    updated_events = []
    
    for event in eligible_events:
        old_status = event.status
        event.status = EventStatusChoices.COMPLETED
        event.save(update_fields=['status', 'updated_at'])
        
        updated_count += 1
        updated_events.append({
            'display_code': event.display_code,
            'title': event.title,
            'old_status': old_status,
            'new_status': EventStatusChoices.COMPLETED,
            'end_datetime': event.end_datetime.isoformat()
        })
        
        logger.info(
            f"Event {event.display_code} ({event.title}) marked as COMPLETED. "
            f"Previous status: {old_status}, End datetime: {event.end_datetime}"
        )
    
    result = {
        'updated_count': updated_count,
        'events': updated_events,
        'checked_at': now.isoformat()
    }
    
    if updated_count > 0:
        logger.info(f"Mark completed events task: Updated {updated_count} event(s) to COMPLETED status")
    else:
        logger.debug("Mark completed events task: No events needed status update")
    
    return result
