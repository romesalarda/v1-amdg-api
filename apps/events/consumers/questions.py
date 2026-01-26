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
        
        Accepts connection first, then waits for authentication message.
        This is more secure than passing JWT in URL.
        """
        # Get event_id from URL route
        self.event_id = self.scope['url_route']['kwargs']['event_id']
        self.group_name = f"event_{self.event_id}_questions"
        self.presence_group_name = f"event_{self.event_id}_presence"
        
        # Accept connection immediately (will authenticate via message)
        await self.accept()
        
        # Mark as not yet authenticated
        self.authenticated = False
        self.user = None
        
        logger.info(
            f"WebSocket connection accepted, awaiting authentication for event {self.event_id}"
        )
    
    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnection.
        
        Broadcasts presence update and removes client from groups.
        
        Args:
            close_code: The WebSocket close code
        """
        # Broadcast that user left (if authenticated)
        if self.authenticated and self.user:
            await self.broadcast_presence('left')
        
        # Leave groups
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
        if hasattr(self, 'presence_group_name'):
            await self.channel_layer.group_discard(
                self.presence_group_name,
                self.channel_name
            )
        
        logger.info(
            f"WebSocket disconnected: user={getattr(self, 'user', 'unknown')}, "
            f"event={getattr(self, 'event_id', 'unknown')}, code={close_code}"
        )
    
    async def receive(self, text_data):
        """
        Handle messages received from WebSocket client.
        
        Supports:
        - authenticate: Initial authentication with JWT token
        - ping: Keepalive check, responds with pong
        
        Args:
            text_data: JSON-encoded message from client
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'authenticate':
                # Handle authentication
                await self.handle_authentication(data.get('token'))
                return
            
            # All other messages require authentication
            if not self.authenticated:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Not authenticated',
                    'timestamp': timezone.now().isoformat()
                }))
                await self.close(code=4003)
                return
            
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
                    f"from user {self.user.email if self.user else 'unauthenticated'}"
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
    
    async def handle_authentication(self, token):
        """
        Authenticate WebSocket connection using JWT token.
        
        Args:
            token: JWT token from client
        """
        if not token:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'No token provided',
                'timestamp': timezone.now().isoformat()
            }))
            await self.close(code=4003)
            return
        
        try:
            # Validate token and get user
            user = await self.authenticate_token(token)
            
            if not user:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Invalid token',
                    'timestamp': timezone.now().isoformat()
                }))
                await self.close(code=4003)
                return
            
            self.user = user
            
            # Check event permissions
            has_permission = await self.check_event_permission()
            if not has_permission:
                logger.warning(
                    f"User {self.user.email} denied access to event {self.event_id}"
                )
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Access denied',
                    'timestamp': timezone.now().isoformat()
                }))
                await self.close(code=4003)
                return
            
            # Join groups
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            await self.channel_layer.group_add(
                self.presence_group_name,
                self.channel_name
            )
            
            self.authenticated = True
            
            # Send authentication confirmation
            await self.send(text_data=json.dumps({
                'type': 'authenticated',
                'message': 'Authentication successful',
                'event_id': str(self.event_id),
                'user': {
                    'id': self.user.id,
                    'email': self.user.email,
                    'name': getattr(self.user, 'get_full_name', lambda: self.user.email)(),
                },
                'timestamp': timezone.now().isoformat()
            }))
            
            # Broadcast presence
            await self.broadcast_presence('joined')
            
            logger.info(
                f"WebSocket authenticated: user={self.user.email}, event={self.event_id}"
            )
            
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}", exc_info=True)
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Authentication failed',
                'timestamp': timezone.now().isoformat()
            }))
            await self.close(code=4003)
    
    async def broadcast_presence(self, status):
        """
        Broadcast user presence status to all clients in event.
        
        Args:
            status: 'joined' or 'left'
        """
        if not self.user:
            return
        
        await self.channel_layer.group_send(
            self.presence_group_name,
            {
                'type': 'presence_event',
                'data': {
                    'type': f'user.{status}',
                    'user': {
                        'id': self.user.id,
                        'email': self.user.email,
                        'name': getattr(self.user, 'get_full_name', lambda: self.user.email)(),
                    },
                    'timestamp': timezone.now().isoformat()
                }
            }
        )
    
    async def presence_event(self, event):
        """
        Handle presence events from channel layer.
        
        Args:
            event: Event dictionary with presence data
        """
        try:
            data = event.get('data', {})
            await self.send(text_data=json.dumps(data))
        except Exception as e:
            logger.error(f"Error broadcasting presence: {str(e)}", exc_info=True)
    
    @database_sync_to_async
    def authenticate_token(self, token):
        """
        Validate JWT token and return user.
        
        Args:
            token: JWT token string
            
        Returns:
            User object if valid, None otherwise
        """
        from rest_framework_simplejwt.tokens import UntypedToken
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
        from django.contrib.auth import get_user_model
        import jwt
        from django.conf import settings
        
        User = get_user_model()
        
        try:
            # Validate token structure
            UntypedToken(token)
            
            # Decode to get user_id
            decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            user_id = decoded.get('user_id')
            
            if not user_id:
                return None
            
            # Get user
            return User.objects.get(id=user_id)
            
        except (InvalidToken, TokenError, User.DoesNotExist, Exception):
            return None
    
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
