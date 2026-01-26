"""
WebSocket consumer for real-time event question updates.

Handles WebSocket connections for the registration form builder,
broadcasting question create/update/delete events to connected clients.
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


class EventQuestionConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time event question updates.
    
    Clients connect to: ws://host/ws/events/{event_id}/questions/
    
    Features:
    - Authenticated connections only (via JWTWebSocketMiddleware)
    - Permission-based access control
    - Real-time broadcasts for question CRUD operations
    - Ping/pong keepalive support
    - Comprehensive error handling and logging
    
    Group Structure:
    - Room name: event_{event_id}_questions
    - One WebSocket per event for form builder updates
    
    Message Types:
    - question.created: New question added
    - question.updated: Question modified
    - question.deleted: Question removed
    - connected: Client successfully connected
    - pong: Response to ping for keepalive
    """
    
    async def connect(self):
        """
        Handle WebSocket connection request.
        
        Validates user permissions and joins the event question group.
        Sends initial connection confirmation with user info.
        """
        # Get event_id from URL route
        self.event_id = self.scope['url_route']['kwargs']['event_id']
        self.group_name = f"event_{self.event_id}_questions"
        
        # Get authenticated user from scope (set by JWTWebSocketMiddleware)
        self.user = self.scope.get('user')
        
        if not self.user or not self.user.is_authenticated:
            logger.warning(
                f"Unauthenticated WebSocket connection attempt for event {self.event_id}"
            )
            await self.close(code=4003)
            return
        
        # Verify user has permission to access this event
        has_permission = await self.check_event_permission()
        if not has_permission:
            logger.warning(
                f"User {self.user.email} denied access to event {self.event_id} WebSocket"
            )
            await self.close(code=4003)
            return
        
        # Join the event question group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        # Accept the WebSocket connection
        await self.accept()
        
        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connected',
            'message': 'Successfully connected to event questions',
            'event_id': str(self.event_id),
            'user': {
                'id': self.user.id,
                'email': self.user.email,
            },
            'timestamp': timezone.now().isoformat()
        }))
        
        logger.info(
            f"WebSocket connected: user={self.user.email}, event={self.event_id}, "
            f"channel={self.channel_name}"
        )
    
    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnection.
        
        Removes client from the event question group and logs disconnection.
        
        Args:
            close_code: The WebSocket close code
        """
        # Leave the event question group
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
        
        logger.info(
            f"WebSocket disconnected: user={getattr(self, 'user', 'unknown')}, "
            f"event={getattr(self, 'event_id', 'unknown')}, code={close_code}"
        )
    
    async def receive(self, text_data):
        """
        Handle messages received from WebSocket client.
        
        Currently supports:
        - ping: Keepalive check, responds with pong
        - Future: Could handle client-initiated actions
        
        Args:
            text_data: JSON-encoded message from client
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'ping':
                # Respond to keepalive ping
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': timezone.now().isoformat()
                }))
            else:
                # Log unhandled message types for future features
                logger.debug(
                    f"Unhandled WebSocket message type: {message_type} "
                    f"from user {self.user.email}"
                )
        
        except json.JSONDecodeError as e:
            logger.error(
                f"Invalid JSON received on WebSocket: {text_data[:100]} - {str(e)}"
            )
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format',
                'timestamp': timezone.now().isoformat()
            }))
        
        except Exception as e:
            logger.error(
                f"Error processing WebSocket message: {str(e)}",
                exc_info=True
            )
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Internal server error',
                'timestamp': timezone.now().isoformat()
            }))
    
    async def question_event(self, event):
        """
        Handle question events from the channel layer.
        
        This method is called when messages are sent to the group via
        channel_layer.group_send() with type='question_event'.
        
        Forwards the event data to the WebSocket client.
        
        Args:
            event: Event dictionary containing:
                - type: 'question_event'
                - data: The actual message payload to send to client
        """
        try:
            # Extract the data payload
            data = event.get('data', {})
            
            # Forward to WebSocket client
            await self.send(text_data=json.dumps(data))
            
            logger.debug(
                f"Broadcasted {data.get('type')} to user {self.user.email}"
            )
        
        except Exception as e:
            logger.error(
                f"Error broadcasting question event: {str(e)}",
                exc_info=True
            )
    
    @database_sync_to_async
    def check_event_permission(self):
        """
        Check if user has permission to access this event's questions.
        
        Grants access if user is:
        - Event creator
        - Event staff member
        - Staff/superuser
        
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
            logger.warning(f"Event {self.event_id} not found during permission check")
            return False
        
        except Exception as e:
            logger.error(
                f"Error checking event permission: {str(e)}",
                exc_info=True
            )
            return False
