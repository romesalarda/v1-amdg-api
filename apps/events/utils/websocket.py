"""
WebSocket utility functions for broadcasting events.

Provides helper functions to broadcast model changes to WebSocket clients
through Django Channels.
"""
import logging
from typing import Any, Dict, Optional
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone

logger = logging.getLogger(__name__)


def broadcast_question_event_sync(
    event_id: str,
    event_type: str,
    question_data: Dict[str, Any],
    actor: Optional[Dict[str, Any]] = None
) -> None:
    """
    Synchronous wrapper for broadcasting question events to WebSocket clients.
    
    Broadcasts to all clients in the event_{event_id}_questions group.
    
    Args:
        event_id: UUID of the event
        event_type: Type of event ('question.created', 'question.updated', 'question.deleted')
        question_data: Serialized question data
        actor: Dictionary with user info (id, email, name) who triggered the event (optional)
        
    Example:
        >>> broadcast_question_event_sync(
        ...     event_id='123e4567-e89b-12d3-a456-426614174000',
        ...     event_type='question.created',
        ...     question_data={'id': '...', 'question_title': 'Name'},
        ...     actor={'id': 1, 'email': 'admin@example.com', 'name': 'Admin'}
        ... )
    """
    channel_layer = get_channel_layer()
    
    if channel_layer is None:
        logger.warning("Channel layer not configured, skipping WebSocket broadcast")
        return
    
    group_name = f"event_{event_id}_questions"
    
    message = {
        "type": "question_event",  # Maps to consumer method name (with underscores)
        "data": {
            "type": event_type,
            "question": question_data,
            "timestamp": timezone.now().isoformat(),
            "actor": actor,
        }
    }
    
    try:
        async_to_sync(channel_layer.group_send)(group_name, message)
        logger.debug(
            f"Broadcast {event_type} to {group_name}: question={question_data.get('id')}"
        )
    except Exception as e:
        logger.error(
            f"Failed to broadcast {event_type} to {group_name}: {e}",
            exc_info=True
        )


def broadcast_question_option_event_sync(
    event_id: str,
    question_id: str,
    actor: Optional[str] = None
) -> None:
    """
    Broadcast that a question's options were modified.
    
    This triggers clients to refetch the question with updated options.
    
    Args:
        event_id: UUID of the event
        question_id: UUID of the question
        actor: Email or ID of user who triggered the event (optional)
    """
    # For option changes, we broadcast a question.updated event
    # The consumer will need to fetch the full question with options
    channel_layer = get_channel_layer()
    
    if channel_layer is None:
        logger.warning("Channel layer not configured, skipping WebSocket broadcast")
        return
    
    group_name = f"event_{event_id}_questions"
    
    message = {
        "type": "question_event",
        "data": {
            "type": "question.updated",
            "question_id": str(question_id),
            "reason": "options_changed",
            "timestamp": timezone.now().isoformat(),
            "actor": actor,
        }
    }
    
    try:
        async_to_sync(channel_layer.group_send)(group_name, message)
        logger.debug(
            f"Broadcast options changed for question {question_id} to {group_name}"
        )
    except Exception as e:
        logger.error(
            f"Failed to broadcast option change to {group_name}: {e}",
            exc_info=True
        )


def broadcast_multiple_questions_event_sync(
    event_id: str,
    event_type: str,
    questions_data: list,
    actor: Optional[str] = None
) -> None:
    """
    Broadcast multiple question changes at once (for bulk operations).
    
    Args:
        event_id: UUID of the event
        event_type: Type of event ('questions.reordered', 'questions.bulk_created')
        questions_data: List of serialized question data
        actor: Email or ID of user who triggered the event
    """
    channel_layer = get_channel_layer()
    
    if channel_layer is None:
        logger.warning("Channel layer not configured, skipping WebSocket broadcast")
        return
    
    group_name = f"event_{event_id}_questions"
    
    message = {
        "type": "question_event",
        "data": {
            "type": event_type,
            "questions": questions_data,
            "timestamp": timezone.now().isoformat(),
            "actor": actor,
        }
    }
    
    try:
        async_to_sync(channel_layer.group_send)(group_name, message)
        logger.debug(
            f"Broadcast {event_type} ({len(questions_data)} questions) to {group_name}"
        )
    except Exception as e:
        logger.error(
            f"Failed to broadcast bulk event to {group_name}: {e}",
            exc_info=True
        )
