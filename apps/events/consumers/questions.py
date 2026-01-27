"""
WebSocket consumer for real-time event question updates.

Handles WebSocket connections for the registration form builder,
broadcasting question create/update/delete events to connected clients.
"""
import json
import logging
from typing import Dict, Any

from channels.db import database_sync_to_async

from .base import BaseRealtimeConsumer

logger = logging.getLogger(__name__)


class EventQuestionConsumer(BaseRealtimeConsumer):
    """
    WebSocket consumer for real-time event question updates.
    
    Extends BaseRealtimeConsumer with event question-specific logic.
    
    Clients connect to: ws://host/ws/events/{event_id}/questions/
    
    Features:
    - JWT authentication (inherited from base)
    - Event staff/creator permission checks
    - Real-time broadcasts for question CRUD operations
    - Presence tracking for active editors (inherited from base)
    - Ping/pong keepalive (inherited from base)
    
    Message Types Sent:
    - question.created: New question added
    - question.updated: Question modified
    - question.deleted: Question removed
    - authenticated: Client successfully connected (inherited)
    - pong: Response to ping for keepalive (inherited)
    - user.joined/user.left: Presence updates (inherited)
    - presence.list: Active users list (inherited)
    
    Permission Requirements:
    - User must be event creator, staff member, or site admin/superuser
    """
    
    # Resource identifier for base class
    resource_name = "questions"
    
    async def connect(self):
        """
        Initialize event-specific context before base connection handling.
        
        Extracts event_id from URL route for room naming and permission checks.
        """
        # Extract event_id from URL route
        self.event_id = self.scope['url_route']['kwargs']['event_id']
        
        # Call base class connection handling
        await super().connect()
    
    # Implement abstract methods from BaseRealtimeConsumer
    
    async def get_room_name(self) -> str:
        """
        Generate room name for event questions channel.
        
        Returns:
            str: Channel layer group name
        """
        return f"event_{self.event_id}_questions"
    
    async def get_presence_room_name(self) -> str:
        """
        Generate presence room name for this event.
        
        Returns:
            str: Presence group name
        """
        return f"event_{self.event_id}_presence"
    
    async def get_presence_key(self) -> str:
        """
        Generate Redis key for presence tracking.
        
        Returns:
            str: Redis key for active users set
        """
        return f"event_presence:{self.event_id}"
    
    async def check_permission(self) -> bool:
        """
        Verify user has access to this event's questions.
        
        Grants access if user is:
        - Event creator
        - Event staff member
        - Site staff/superuser
        
        Returns:
            bool: True if authorized, False otherwise
        """
        return await self.check_event_permission()
    
    async def get_user_context(self) -> Dict[str, Any]:
        """
        Generate user context for client messages.
        
        Returns:
            dict: User data including id, email, name, and event_id
        """
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': getattr(self.user, 'get_full_name', lambda: self.user.email)(),
            'event_id': str(self.event_id),
        }
    
    async def handle_authenticated_message(self, message_type: str, data: dict):
        """
        Handle event question-specific WebSocket messages.
        
        Currently logs unhandled message types for future feature development.
        Can be extended to support client-initiated actions like:
        - Creating/updating questions from WebSocket
        - Requesting question lists
        - Subscribing to specific question updates
        
        Args:
            message_type: Message type from client
            data: Full message dictionary
        """
        # Log for future feature development
        logger.debug(
            f"[questions] Unhandled message type: {message_type} "
            f"from user {self.user.email}"
        )
    
    # Event-specific channel layer handlers
    
    async def question_event(self, event: Dict[str, Any]):
        """
        Handle question events from the channel layer.
        
        Called when question create/update/delete events are broadcast
        to the group via channel_layer.group_send() with type='question_event'.
        
        Forwards the event data to the connected WebSocket client.
        
        Args:
            event: Event dictionary containing:
                - type: 'question_event'
                - data: Payload with question data and action type
        """
        try:
            # Extract the data payload
            data = event.get('data', {})
            
            # Forward to WebSocket client
            await self.send(text_data=json.dumps(data))
            
            logger.debug(
                f"[questions] Broadcasted {data.get('type')} "
                f"to user {self.user.email}"
            )
        
        except Exception as e:
            logger.error(
                f"[questions] Error broadcasting question event: {str(e)}",
                exc_info=True
            )
    
    # Event-specific permission check
    
    @database_sync_to_async
    def check_event_permission(self) -> bool:
        """
        Check if user has permission to access this event's questions.
        
        Grants access if user is:
        - Event creator
        - Event staff member
        - Site staff/superuser
        
        Returns:
            bool: True if user has permission, False otherwise
        """
        from apps.events.models import Event
        
        try:
            event = Event.objects.select_related('created_by').prefetch_related(
                'staff_members'
            ).get(event_id=self.event_id)
            
            # Check if user is event creator
            if event.created_by == self.user:
                return True
            
            # Check if user is staff member
            if event.staff_members.filter(user=self.user).exists():
                return True
            
            # Check if user is admin/superuser
            if self.user.is_staff or self.user.is_superuser:
                return True
            
            return False
        
        except Event.DoesNotExist:
            logger.warning(
                f"[questions] Event {self.event_id} not found "
                f"during permission check"
            )
            return False
        
        except Exception as e:
            logger.error(
                f"[questions] Error checking event permission: {str(e)}",
                exc_info=True
            )
            return False

