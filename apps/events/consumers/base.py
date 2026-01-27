"""
Base WebSocket consumer for real-time Django Channels features.

Provides a production-grade foundation for building real-time consumers with:
- JWT authentication and authorization
- Redis-based presence tracking
- Connection lifecycle management
- Heartbeat/keepalive handling
- Error handling and logging
- Room/group management

Subclasses must implement resource-specific logic while inheriting
common infrastructure patterns.
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, TYPE_CHECKING

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model
    User = get_user_model()

logger = logging.getLogger(__name__)


class BaseRealtimeConsumer(AsyncWebsocketConsumer, ABC):
    """
    Abstract base consumer for real-time WebSocket connections.
    
    Provides common infrastructure for:
    - JWT-based authentication via message protocol
    - Permission-based access control
    - Redis presence tracking
    - Ping/pong keepalive
    - Group/room management
    - Error handling and logging
    
    Subclasses must implement:
    - resource_name: Identifier for the resource type
    - get_room_name(): Generate room name based on context
    - get_presence_room_name(): Generate presence room name
    - get_presence_key(): Generate Redis key for presence
    - check_permission(): Validate user access
    - handle_authenticated_message(): Handle resource-specific messages
    - get_user_context(): Provide user data for authentication response
    
    Connection Flow:
    1. Client connects -> accept() called
    2. Client sends authenticate message with JWT
    3. Token validated, user extracted
    4. Permission check performed
    5. User added to room groups and presence tracking
    6. Client receives authenticated confirmation
    7. Subsequent messages routed to handle_authenticated_message()
    
    Example Subclass:
    ```python
    class EventQuestionConsumer(BaseRealtimeConsumer):
        resource_name = "questions"
        
        async def get_room_name(self) -> str:
            return f"event_{self.event_id}_questions"
        
        async def get_presence_room_name(self) -> str:
            return f"event_{self.event_id}_presence"
        
        async def get_presence_key(self) -> str:
            return f"event_presence:{self.event_id}"
        
        async def check_permission(self) -> bool:
            # Check if user can access this event
            return await self.check_event_permission()
        
        async def handle_authenticated_message(self, message_type: str, data: dict):
            # Handle question-specific messages
            pass
    ```
    """
    
    # Abstract property - subclass must define
    @property
    @abstractmethod
    def resource_name(self) -> str:
        """
        Resource identifier for logging and error messages.
        
        Examples: 'questions', 'bookings', 'workshops', 'dashboard'
        
        Returns:
            str: Resource name in lowercase plural form
        """
        pass
    
    # Abstract methods - subclass must implement
    @abstractmethod
    async def get_room_name(self) -> str:
        """
        Generate the channel layer group name for broadcasting.
        
        This method determines which WebSocket clients receive broadcasts
        for resource updates. Typically based on URL parameters.
        
        Example:
            return f"event_{self.event_id}_questions"
        
        Returns:
            str: Group name for channel layer
        """
        pass
    
    @abstractmethod
    async def get_presence_room_name(self) -> str:
        """
        Generate the channel layer group name for presence broadcasts.
        
        Separate from main room to allow independent presence management.
        
        Example:
            return f"event_{self.event_id}_presence"
        
        Returns:
            str: Group name for presence updates
        """
        pass
    
    @abstractmethod
    async def get_presence_key(self) -> str:
        """
        Generate Redis key for storing active users.
        
        Used for presence tracking. Should be unique per resource instance.
        
        Example:
            return f"event_presence:{self.event_id}"
        
        Returns:
            str: Redis key for presence set
        """
        pass
    
    @abstractmethod
    async def check_permission(self) -> bool:
        """
        Validate if authenticated user has access to this resource.
        
        Called after JWT authentication succeeds. Should check resource-specific
        permissions (e.g., event staff, organization member, etc.).
        
        Returns:
            bool: True if user has access, False otherwise
        """
        pass
    
    @abstractmethod
    async def handle_authenticated_message(self, message_type: str, data: dict):
        """
        Handle resource-specific WebSocket messages.
        
        Called for all messages after authentication succeeds.
        Does not need to handle 'ping' - that's handled by base class.
        
        Args:
            message_type: Type field from client message
            data: Full message dictionary from client
        """
        pass
    
    @abstractmethod
    async def get_user_context(self) -> Dict[str, Any]:
        """
        Generate user context for authentication response.
        
        Allows subclasses to include additional user information
        in the authenticated confirmation message.
        
        Example:
            return {
                'id': self.user.id,
                'email': self.user.email,
                'name': self.user.get_full_name(),
                'role': self.get_user_role(),
            }
        
        Returns:
            dict: User data to send to client
        """
        pass
    
    # Concrete methods - shared infrastructure
    
    async def connect(self):
        """
        Handle WebSocket connection request.
        
        Accepts connection immediately and waits for authentication message.
        This pattern is more secure than passing JWT in URL parameters.
        
        Connection is accepted but marked as unauthenticated until
        client sends valid JWT via 'authenticate' message.
        """
        # Accept connection (authentication happens via message)
        await self.accept()
        
        # Initialize authentication state
        self.authenticated = False
        self.user = None
        
        # Initialize group tracking
        self.group_name = None
        self.presence_group_name = None
        self.presence_key = None
        
        logger.info(
            f"[{self.resource_name}] WebSocket connection accepted, "
            f"awaiting authentication"
        )
    
    async def disconnect(self, close_code: int):
        """
        Handle WebSocket disconnection.
        
        Removes user from presence tracking and channel groups.
        Broadcasts presence update to remaining clients.
        
        Args:
            close_code: WebSocket close code
        """
        # Remove from presence tracking and broadcast departure
        if self.authenticated and self.user:
            await self.remove_from_presence()
            await self.broadcast_presence('left')
        
        # Leave channel layer groups
        if self.group_name:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
        
        if self.presence_group_name:
            await self.channel_layer.group_discard(
                self.presence_group_name,
                self.channel_name
            )
        
        logger.info(
            f"[{self.resource_name}] WebSocket disconnected: "
            f"user={getattr(self.user, 'email', 'unknown')}, "
            f"code={close_code}"
        )
    
    async def receive(self, text_data: str):
        """
        Handle messages received from WebSocket client.
        
        Routes messages based on authentication state:
        - 'authenticate' message: Validates JWT and establishes session
        - 'ping' message: Responds with pong for keepalive
        - Other messages: Routed to handle_authenticated_message()
        
        All messages except 'authenticate' require prior authentication.
        
        Args:
            text_data: JSON-encoded message from client
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            # Handle authentication (unauthenticated clients only send this)
            if message_type == 'authenticate':
                await self.handle_authentication(data.get('token'))
                return
            
            # All other messages require authentication
            if not self.authenticated:
                await self.send_error(
                    'Not authenticated',
                    code=4003,
                    close_connection=True
                )
                return
            
            # Handle keepalive ping
            if message_type == 'ping':
                await self.send_pong()
                return
            
            # Route to subclass handler
            await self.handle_authenticated_message(message_type, data)
        
        except json.JSONDecodeError as e:
            logger.error(
                f"[{self.resource_name}] Invalid JSON received: "
                f"{text_data[:100]} - {str(e)}"
            )
            await self.send_error('Invalid JSON format')
        
        except Exception as e:
            logger.error(
                f"[{self.resource_name}] Error processing message: {str(e)}",
                exc_info=True
            )
            await self.send_error('Internal server error')
    
    async def handle_authentication(self, token: Optional[str]):
        """
        Authenticate WebSocket connection using JWT token.
        
        Validates token, extracts user, checks permissions, and joins groups.
        Sends success or error response to client.
        
        Args:
            token: JWT token from client authenticate message
        """
        if not token:
            await self.send_error(
                'No token provided',
                code=4003,
                close_connection=True
            )
            return
        
        try:
            # Validate JWT and extract user
            user = await self.authenticate_token(token)
            
            if not user:
                await self.send_error(
                    'Invalid token',
                    code=4003,
                    close_connection=True
                )
                return
            
            self.user = user
            
            # Check resource-specific permissions
            has_permission = await self.check_permission()
            if not has_permission:
                logger.warning(
                    f"[{self.resource_name}] User {self.user.email} "
                    f"denied access"
                )
                await self.send_error(
                    'Access denied',
                    code=4003,
                    close_connection=True
                )
                return
            
            # Initialize room names (call abstract methods)
            self.group_name = await self.get_room_name()
            self.presence_group_name = await self.get_presence_room_name()
            self.presence_key = await self.get_presence_key()
            
            # Join channel layer groups
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            await self.channel_layer.group_add(
                self.presence_group_name,
                self.channel_name
            )
            
            self.authenticated = True
            
            # Send authentication confirmation with user context
            user_context = await self.get_user_context()
            await self.send(text_data=json.dumps({
                'type': 'authenticated',
                'message': 'Authentication successful',
                'user': user_context,
                'timestamp': timezone.now().isoformat()
            }))
            
            # Broadcast presence and send active users list
            await self.broadcast_presence('joined')
            
            logger.info(
                f"[{self.resource_name}] WebSocket authenticated: "
                f"user={self.user.email}"
            )
        
        except Exception as e:
            logger.error(
                f"[{self.resource_name}] Authentication error: {str(e)}",
                exc_info=True
            )
            await self.send_error(
                'Authentication failed',
                code=4003,
                close_connection=True
            )
    
    async def send_error(
        self,
        message: str,
        code: Optional[int] = None,
        close_connection: bool = False
    ):
        """
        Send error message to client.
        
        Args:
            message: Error message to send
            code: Optional close code if closing connection
            close_connection: Whether to close connection after sending
        """
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message,
            'timestamp': timezone.now().isoformat()
        }))
        
        if close_connection and code:
            await self.close(code=code)
    
    async def send_pong(self):
        """
        Respond to client ping with pong for keepalive.
        """
        await self.send(text_data=json.dumps({
            'type': 'pong',
            'timestamp': timezone.now().isoformat()
        }))
    
    # Presence tracking methods
    
    async def broadcast_presence(self, status: str):
        """
        Broadcast user presence status to all clients in room.
        
        On 'joined', adds user to Redis presence set and sends
        list of active users to the joining client.
        
        On 'left', presence removal happens in disconnect().
        
        Args:
            status: Either 'joined' or 'left'
        """
        if not self.user:
            return
        
        # Add to presence tracking on join
        if status == 'joined':
            await self.add_to_presence()
        
        # Get user context for presence broadcast
        user_context = await self.get_user_context()
        
        # Broadcast to all clients in presence group
        await self.channel_layer.group_send(
            self.presence_group_name,
            {
                'type': 'presence_event',
                'data': {
                    'type': f'user.{status}',
                    'user': user_context,
                    'timestamp': timezone.now().isoformat()
                }
            }
        )
        
        # If joining, send list of existing users to this client
        if status == 'joined':
            active_users = await self.get_active_users()
            await self.send(text_data=json.dumps({
                'type': 'presence.list',
                'users': active_users,
                'timestamp': timezone.now().isoformat()
            }))
    
    async def presence_event(self, event: Dict[str, Any]):
        """
        Handle presence events from channel layer.
        
        Called when presence updates are broadcast to the group.
        Forwards the event to the WebSocket client.
        
        Args:
            event: Event dictionary from channel layer
        """
        try:
            data = event.get('data', {})
            await self.send(text_data=json.dumps(data))
        except Exception as e:
            logger.error(
                f"[{self.resource_name}] Error broadcasting presence: {str(e)}",
                exc_info=True
            )
    
    async def get_active_users(self) -> List[Dict[str, Any]]:
        """
        Get list of currently connected users from Redis presence set.
        
        Excludes the current user from the returned list.
        
        Returns:
            List of user context dictionaries (same format as get_user_context)
        """
        try:
            import redis.asyncio as redis
            from django.conf import settings
            
            # Get Redis configuration from channel layer settings
            redis_config = getattr(
                settings, 'CHANNEL_LAYERS', {}
            ).get('default', {}).get('CONFIG', {}).get('hosts', [('localhost', 6379)])[0]
            
            # Connect to Redis
            if isinstance(redis_config, tuple):
                r = redis.Redis(
                    host=redis_config[0],
                    port=redis_config[1],
                    decode_responses=True
                )
            else:
                r = redis.from_url(redis_config, decode_responses=True)
            
            # Get all users in presence set
            user_data_list = await r.smembers(self.presence_key)
            
            active_users = []
            for user_json in user_data_list:
                try:
                    user_data = json.loads(user_json)
                    # Exclude current user from list
                    if user_data.get('id') != self.user.id:
                        active_users.append(user_data)
                except json.JSONDecodeError:
                    logger.warning(
                        f"[{self.resource_name}] Invalid user data in presence: {user_json}"
                    )
                    continue
            
            await r.close()
            return active_users
        
        except Exception as e:
            logger.error(
                f"[{self.resource_name}] Error getting active users: {str(e)}",
                exc_info=True
            )
            return []
    
    async def add_to_presence(self):
        """
        Add current user to Redis presence tracking set.
        
        Stores user context as JSON string in Redis set.
        Sets 24-hour expiry on the presence key.
        """
        try:
            import redis.asyncio as redis
            from django.conf import settings
            
            redis_config = getattr(
                settings, 'CHANNEL_LAYERS', {}
            ).get('default', {}).get('CONFIG', {}).get('hosts', [('localhost', 6379)])[0]
            
            if isinstance(redis_config, tuple):
                r = redis.Redis(
                    host=redis_config[0],
                    port=redis_config[1],
                    decode_responses=True
                )
            else:
                r = redis.from_url(redis_config, decode_responses=True)
            
            # Get user context and serialize
            user_context = await self.get_user_context()
            user_data = json.dumps(user_context)
            
            # Add to Redis set with 24-hour expiry
            await r.sadd(self.presence_key, user_data)
            await r.expire(self.presence_key, 86400)
            
            await r.close()
        
        except Exception as e:
            logger.error(
                f"[{self.resource_name}] Error adding to presence: {str(e)}",
                exc_info=True
            )
    
    async def remove_from_presence(self):
        """
        Remove current user from Redis presence tracking set.
        
        Handles potential duplicates by removing all entries
        matching the current user's ID.
        """
        try:
            import redis.asyncio as redis
            from django.conf import settings
            
            redis_config = getattr(
                settings, 'CHANNEL_LAYERS', {}
            ).get('default', {}).get('CONFIG', {}).get('hosts', [('localhost', 6379)])[0]
            
            if isinstance(redis_config, tuple):
                r = redis.Redis(
                    host=redis_config[0],
                    port=redis_config[1],
                    decode_responses=True
                )
            else:
                r = redis.from_url(redis_config, decode_responses=True)
            
            # Remove all entries for this user (handles duplicates)
            members = await r.smembers(self.presence_key)
            for member in members:
                try:
                    user_data = json.loads(member)
                    if user_data.get('id') == self.user.id:
                        await r.srem(self.presence_key, member)
                except json.JSONDecodeError:
                    continue
            
            await r.close()
        
        except Exception as e:
            logger.error(
                f"[{self.resource_name}] Error removing from presence: {str(e)}",
                exc_info=True
            )
    
    # Authentication helper
    
    @database_sync_to_async
    def authenticate_token(self, token: str) -> Optional[Any]:
        """
        Validate JWT token and return associated user.
        
        Uses django-rest-framework-simplejwt for token validation.
        
        Args:
            token: JWT token string
        
        Returns:
            User object if token is valid, None otherwise
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
            decoded = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=['HS256']
            )
            user_id = decoded.get('user_id')
            
            if not user_id:
                return None
            
            # Get and return user
            return User.objects.get(id=user_id)
        
        except (InvalidToken, TokenError, User.DoesNotExist, Exception) as e:
            logger.debug(
                f"[{self.resource_name}] Token validation failed: {str(e)}"
            )
            return None
