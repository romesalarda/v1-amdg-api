# BaseRealtimeConsumer Documentation

## Overview

`BaseRealtimeConsumer` is a production-grade abstract base class for building real-time WebSocket consumers in Django Channels. It provides a complete infrastructure for JWT authentication, Redis presence tracking, connection lifecycle management, and error handling.

## Architecture

### What's in the Base Class

The base class handles all common WebSocket infrastructure:

#### 1. **Authentication & Authorization**
- JWT token validation via message protocol (not URL params)
- User extraction from JWT tokens
- Abstract `check_permission()` for resource-specific access control
- Secure connection flow: connect → authenticate → authorize → join groups

#### 2. **Connection Lifecycle**
- `connect()`: Accepts WebSocket, initializes state
- `disconnect()`: Cleans up presence, leaves groups
- `receive()`: Routes messages based on authentication state
- Error handling with proper close codes

#### 3. **Presence Tracking**
- Redis-based active user tracking
- `add_to_presence()`: Adds user to Redis set
- `remove_from_presence()`: Removes user from Redis set
- `get_active_users()`: Retrieves list of connected users
- `broadcast_presence()`: Notifies all clients of join/leave events
- Automatic cleanup on disconnect

#### 4. **Message Handling**
- `authenticate` message: JWT validation and setup
- `ping` message: Keepalive with automatic `pong` response
- Custom messages: Routed to `handle_authenticated_message()`
- JSON parsing with error handling

#### 5. **Broadcasting Infrastructure**
- Channel layer group management
- Separate groups for main events and presence
- `presence_event()`: Forwards presence updates to clients
- Helper methods for sending errors and pongs

#### 6. **Logging & Error Handling**
- Resource-specific log prefixes (e.g., `[questions]`)
- Comprehensive error logging with stack traces
- Client-friendly error messages
- Production-ready exception handling

### What Subclasses Must Implement

Subclasses define resource-specific behavior through abstract methods:

#### Required Properties

```python
@property
@abstractmethod
def resource_name(self) -> str:
    """Resource identifier (e.g., 'questions', 'bookings')"""
    pass
```

#### Required Methods

```python
@abstractmethod
async def get_room_name(self) -> str:
    """Generate channel layer group name for broadcasts"""
    pass

@abstractmethod
async def get_presence_room_name(self) -> str:
    """Generate channel layer group name for presence"""
    pass

@abstractmethod
async def get_presence_key(self) -> str:
    """Generate Redis key for presence set"""
    pass

@abstractmethod
async def check_permission(self) -> bool:
    """Validate user access to this resource"""
    pass

@abstractmethod
async def handle_authenticated_message(self, message_type: str, data: dict):
    """Handle resource-specific messages"""
    pass

@abstractmethod
async def get_user_context(self) -> Dict[str, Any]:
    """Generate user data for authentication response"""
    pass
```

## Creating a Subclass

### Example: EventQuestionConsumer

Here's a complete example of how to extend `BaseRealtimeConsumer`:

```python
from typing import Dict, Any
from channels.db import database_sync_to_async
from .base import BaseRealtimeConsumer

class EventQuestionConsumer(BaseRealtimeConsumer):
    """WebSocket consumer for event question updates."""
    
    # 1. Define resource identifier
    resource_name = "questions"
    
    # 2. Extract context in connect (before calling super())
    async def connect(self):
        self.event_id = self.scope['url_route']['kwargs']['event_id']
        await super().connect()
    
    # 3. Implement room naming
    async def get_room_name(self) -> str:
        return f"event_{self.event_id}_questions"
    
    async def get_presence_room_name(self) -> str:
        return f"event_{self.event_id}_presence"
    
    async def get_presence_key(self) -> str:
        return f"event_presence:{self.event_id}"
    
    # 4. Implement permission check
    async def check_permission(self) -> bool:
        return await self.check_event_permission()
    
    @database_sync_to_async
    def check_event_permission(self) -> bool:
        from apps.events.models import Event
        event = Event.objects.get(event_id=self.event_id)
        return (
            event.created_by == self.user or
            event.staff_members.filter(user=self.user).exists() or
            self.user.is_staff
        )
    
    # 5. Provide user context
    async def get_user_context(self) -> Dict[str, Any]:
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': self.user.get_full_name(),
            'event_id': str(self.event_id),
        }
    
    # 6. Handle custom messages
    async def handle_authenticated_message(self, message_type: str, data: dict):
        if message_type == 'subscribe.question':
            # Handle subscription to specific question
            pass
        else:
            logger.debug(f"Unhandled message: {message_type}")
    
    # 7. Add channel layer event handlers
    async def question_event(self, event: Dict[str, Any]):
        """Handle question broadcasts from channel layer."""
        data = event.get('data', {})
        await self.send(text_data=json.dumps(data))
```

### Step-by-Step Guide

#### Step 1: Import and Inherit

```python
from .base import BaseRealtimeConsumer

class MyConsumer(BaseRealtimeConsumer):
    resource_name = "my_resource"  # Used in logs
```

#### Step 2: Extract URL Parameters

Override `connect()` to extract context from URL before calling `super()`:

```python
async def connect(self):
    # Extract whatever you need from self.scope['url_route']['kwargs']
    self.resource_id = self.scope['url_route']['kwargs']['resource_id']
    
    # Must call super() to complete connection setup
    await super().connect()
```

#### Step 3: Define Room Names

Implement the three room/key methods:

```python
async def get_room_name(self) -> str:
    # Main channel layer group for broadcasts
    return f"resource_{self.resource_id}"

async def get_presence_room_name(self) -> str:
    # Separate group for presence updates
    return f"resource_{self.resource_id}_presence"

async def get_presence_key(self) -> str:
    # Redis key for storing active users
    return f"resource_presence:{self.resource_id}"
```

**Naming Conventions:**
- Main room: `{resource_type}_{id}` or `{resource_type}_{id}_{subtype}`
- Presence room: `{resource_type}_{id}_presence`
- Redis key: `{resource_type}_presence:{id}`

#### Step 4: Implement Permission Check

Define who can access this resource:

```python
async def check_permission(self) -> bool:
    return await self.check_my_permission()

@database_sync_to_async
def check_my_permission(self) -> bool:
    # Query database to check if self.user has access
    # Return True to allow, False to deny
    from myapp.models import MyResource
    resource = MyResource.objects.get(id=self.resource_id)
    return resource.user == self.user or self.user.is_staff
```

#### Step 5: Provide User Context

Define what user data clients receive:

```python
async def get_user_context(self) -> Dict[str, Any]:
    return {
        'id': self.user.id,
        'email': self.user.email,
        'name': self.user.get_full_name(),
        # Add any resource-specific context
        'role': await self.get_user_role(),
    }
```

#### Step 6: Handle Custom Messages

Process resource-specific messages from clients:

```python
async def handle_authenticated_message(self, message_type: str, data: dict):
    if message_type == 'action.create':
        # Handle create action
        pass
    elif message_type == 'action.update':
        # Handle update action
        pass
    else:
        # Unknown message types can be logged for debugging
        logger.debug(f"[{self.resource_name}] Unknown: {message_type}")
```

#### Step 7: Add Channel Layer Handlers

Define handlers for broadcasts from Django code:

```python
async def my_resource_event(self, event: Dict[str, Any]):
    """
    Handle broadcasts sent via:
    channel_layer.group_send(
        room_name,
        {
            'type': 'my_resource_event',  # Converts to method name
            'data': {...}
        }
    )
    """
    data = event.get('data', {})
    await self.send(text_data=json.dumps(data))
```

## Broadcasting from Django Code

### From Views/Signals/Tasks

```python
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

channel_layer = get_channel_layer()

# Send to all clients in room
async_to_sync(channel_layer.group_send)(
    f"event_{event_id}_questions",  # Must match get_room_name()
    {
        'type': 'question_event',  # Converts dots to underscores -> question_event()
        'data': {
            'type': 'question.created',
            'question': {
                'id': str(question.id),
                'text': question.text,
                # ... more data
            },
            'timestamp': timezone.now().isoformat()
        }
    }
)
```

### Event Type Naming

The `type` field in `channel_layer.group_send()` determines which consumer method is called:

- `'question_event'` → calls `async def question_event(self, event)`
- `'booking.update'` → calls `async def booking_update(self, event)`
- `'my_custom_event'` → calls `async def my_custom_event(self, event)`

## Client Connection Flow

### 1. Client Connects

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/events/123/questions/');

ws.onopen = () => {
    // Connection accepted, but not authenticated yet
};
```

### 2. Client Authenticates

```javascript
ws.send(JSON.stringify({
    type: 'authenticate',
    token: 'eyJ0eXAiOiJKV1QiLCJhbGc...'  // JWT from login
}));
```

### 3. Server Response (Success)

```json
{
    "type": "authenticated",
    "message": "Authentication successful",
    "user": {
        "id": 1,
        "email": "user@example.com",
        "name": "John Doe",
        "event_id": "123"
    },
    "timestamp": "2026-01-27T10:30:00Z"
}
```

### 4. Server Sends Presence List

```json
{
    "type": "presence.list",
    "users": [
        {"id": 2, "email": "other@example.com", "name": "Jane Doe"},
        {"id": 3, "email": "admin@example.com", "name": "Admin"}
    ],
    "timestamp": "2026-01-27T10:30:00Z"
}
```

### 5. Client Receives Presence Updates

```json
{
    "type": "user.joined",
    "user": {
        "id": 4,
        "email": "new@example.com",
        "name": "New User"
    },
    "timestamp": "2026-01-27T10:31:00Z"
}
```

### 6. Client Receives Resource Updates

```json
{
    "type": "question.created",
    "question": {
        "id": "456",
        "text": "What is your favorite color?",
        "order": 1
    },
    "timestamp": "2026-01-27T10:32:00Z"
}
```

### 7. Client Sends Keepalive Ping

```javascript
// Send ping every 30 seconds
setInterval(() => {
    ws.send(JSON.stringify({ type: 'ping' }));
}, 30000);

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'pong') {
        console.log('Connection alive');
    }
};
```

## Error Handling

### Authentication Errors

**Missing Token:**
```json
{
    "type": "error",
    "message": "No token provided",
    "timestamp": "2026-01-27T10:30:00Z"
}
// WebSocket closes with code 4003
```

**Invalid Token:**
```json
{
    "type": "error",
    "message": "Invalid token",
    "timestamp": "2026-01-27T10:30:00Z"
}
// WebSocket closes with code 4003
```

**Permission Denied:**
```json
{
    "type": "error",
    "message": "Access denied",
    "timestamp": "2026-01-27T10:30:00Z"
}
// WebSocket closes with code 4003
```

### Client-Side Error Handling

```javascript
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === 'error') {
        console.error('WebSocket error:', data.message);
        // Handle error (show notification, retry, etc.)
    }
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

ws.onclose = (event) => {
    console.log('WebSocket closed:', event.code, event.reason);
    
    if (event.code === 4003) {
        // Authentication failed - redirect to login
        window.location.href = '/login';
    } else {
        // Network error - attempt reconnect
        setTimeout(reconnect, 3000);
    }
};
```

## Redis Presence Details

### How It Works

1. **User Joins:**
   - User data serialized to JSON: `{"id": 1, "email": "user@example.com", "name": "John Doe"}`
   - Added to Redis set: `SADD event_presence:123 '{"id": 1, ...}'`
   - Set expiry: `EXPIRE event_presence:123 86400` (24 hours)

2. **Get Active Users:**
   - Fetch all members: `SMEMBERS event_presence:123`
   - Parse JSON and filter out current user
   - Return list to client

3. **User Leaves:**
   - Find all entries with matching user ID
   - Remove from set: `SREM event_presence:123 '{"id": 1, ...}'`
   - Handles duplicates (multiple connections)

### Presence Key Format

```
{resource_type}_presence:{resource_id}
```

Examples:
- `event_presence:123` - Event questions
- `workshop_presence:456` - Workshop dashboard
- `booking_presence:789` - Booking collaboration

## Testing

### Unit Testing Example

```python
import pytest
from channels.testing import WebsocketCommunicator
from myapp.consumers import MyConsumer

@pytest.mark.asyncio
async def test_connect_and_authenticate():
    communicator = WebsocketCommunicator(MyConsumer.as_asgi(), "/ws/resource/123/")
    connected, _ = await communicator.connect()
    assert connected
    
    # Send authentication
    await communicator.send_json_to({
        'type': 'authenticate',
        'token': 'valid_jwt_token'
    })
    
    # Check authentication response
    response = await communicator.receive_json_from()
    assert response['type'] == 'authenticated'
    assert 'user' in response
    
    await communicator.disconnect()

@pytest.mark.asyncio
async def test_permission_denied():
    communicator = WebsocketCommunicator(MyConsumer.as_asgi(), "/ws/resource/999/")
    connected, _ = await communicator.connect()
    assert connected
    
    await communicator.send_json_to({
        'type': 'authenticate',
        'token': 'valid_jwt_token_no_permission'
    })
    
    response = await communicator.receive_json_from()
    assert response['type'] == 'error'
    assert response['message'] == 'Access denied'
    
    # Check connection closed
    assert await communicator.receive_nothing(timeout=0.1)
```

### Integration Testing

```python
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_broadcast_to_clients():
    # Connect two clients
    comm1 = WebsocketCommunicator(MyConsumer.as_asgi(), "/ws/resource/123/")
    comm2 = WebsocketCommunicator(MyConsumer.as_asgi(), "/ws/resource/123/")
    
    await comm1.connect()
    await comm2.connect()
    
    # Authenticate both
    for comm in [comm1, comm2]:
        await comm.send_json_to({'type': 'authenticate', 'token': valid_token})
        await comm.receive_json_from()  # Authenticated response
    
    # Trigger broadcast from Django code
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "resource_123",
        {
            'type': 'resource_event',
            'data': {'type': 'resource.updated', 'id': '123'}
        }
    )
    
    # Both clients should receive the message
    msg1 = await comm1.receive_json_from(timeout=1)
    msg2 = await comm2.receive_json_from(timeout=1)
    
    assert msg1['type'] == 'resource.updated'
    assert msg2['type'] == 'resource.updated'
    
    await comm1.disconnect()
    await comm2.disconnect()
```

## Performance Considerations

### Redis Connection Pooling

The current implementation creates a new Redis connection for each presence operation. For high-traffic applications, consider:

```python
# Add to your base consumer or settings
class BaseRealtimeConsumer(AsyncWebsocketConsumer, ABC):
    _redis_pool = None
    
    @classmethod
    async def get_redis_connection(cls):
        if cls._redis_pool is None:
            import redis.asyncio as redis
            from django.conf import settings
            
            redis_config = settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0]
            cls._redis_pool = redis.ConnectionPool.from_url(redis_config)
        
        return redis.Redis(connection_pool=cls._redis_pool, decode_responses=True)
```

### Channel Layer Considerations

- Use Redis as channel layer backend (already configured)
- Consider Redis Sentinel for high availability
- Monitor channel layer message queue depth
- Set appropriate `capacity` and `expiry` in channel layer config

### Presence Cleanup

The 24-hour expiry on presence keys is a safety net. Consider:

- Shorter expiry (1-2 hours) for more active cleanup
- Background task to clean stale presence data
- Heartbeat mechanism to refresh expiry

## Security Best Practices

### 1. JWT Validation

✅ **DO:**
- Validate token signature
- Check token expiration
- Verify token hasn't been revoked (if using blacklist)

❌ **DON'T:**
- Pass JWT in URL query parameters (use message protocol)
- Store JWT in localStorage without encryption
- Use weak SECRET_KEY

### 2. Permission Checks

✅ **DO:**
- Check permissions for every resource access
- Use database queries to verify current state
- Log permission denials for security monitoring

❌ **DON'T:**
- Trust client-side permission checks
- Cache permissions for too long
- Grant broad permissions

### 3. Input Validation

✅ **DO:**
- Validate all client messages
- Sanitize message data before processing
- Set message size limits

❌ **DON'T:**
- Trust client data without validation
- Process unbounded message sizes
- Execute client-provided code

## Patterns and Conventions

### Naming Conventions

1. **Consumer Class Names:**
   - Format: `{Resource}{Purpose}Consumer`
   - Examples: `EventQuestionConsumer`, `BookingCollaborationConsumer`

2. **Resource Names:**
   - Lowercase plural: `questions`, `bookings`, `workshops`
   - Used in logs: `[questions]`, `[bookings]`

3. **Room Names:**
   - Format: `{resource}_{id}_{purpose}`
   - Examples: `event_123_questions`, `booking_456_collaboration`

4. **Redis Keys:**
   - Format: `{resource}_presence:{id}`
   - Examples: `event_presence:123`, `booking_presence:456`

5. **Message Types:**
   - Format: `{resource}.{action}` or `{category}.{action}`
   - Examples: `question.created`, `user.joined`, `booking.updated`

### Code Organization

```
apps/
  myapp/
    consumers/
      __init__.py       # Export all consumers
      base.py           # BaseRealtimeConsumer (if needed)
      questions.py      # QuestionConsumer
      bookings.py       # BookingConsumer
    routing.py          # WebSocket URL routing
    signals.py          # Trigger broadcasts on model changes
```

### Signal-Based Broadcasting

Automatically broadcast changes when models are saved:

```python
from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

@receiver(post_save, sender=Question)
def broadcast_question_change(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f"event_{instance.event_id}_questions",
        {
            'type': 'question_event',
            'data': {
                'type': 'question.created' if created else 'question.updated',
                'question': {
                    'id': str(instance.id),
                    'text': instance.text,
                    # ... serialize full object
                },
                'timestamp': timezone.now().isoformat()
            }
        }
    )
```

## Migration Guide

### From Standalone Consumer to BaseRealtimeConsumer

If you have an existing consumer without a base class:

1. **Identify Common Logic:**
   - JWT authentication
   - Presence tracking
   - Connection lifecycle
   - Error handling

2. **Extract URL Parameters:**
   ```python
   # Before
   async def connect(self):
       self.event_id = self.scope['url_route']['kwargs']['event_id']
       self.group_name = f"event_{self.event_id}_questions"
       await self.accept()
   
   # After
   async def connect(self):
       self.event_id = self.scope['url_route']['kwargs']['event_id']
       await super().connect()
   ```

3. **Convert Methods to Abstract Method Implementations:**
   ```python
   # Before
   async def connect(self):
       # ... authentication logic ...
   
   # After
   async def check_permission(self) -> bool:
       return await self.check_event_permission()
   ```

4. **Remove Duplicate Code:**
   - Delete `authenticate_token()`
   - Delete `add_to_presence()`, `remove_from_presence()`, `get_active_users()`
   - Delete generic `receive()` and `disconnect()` logic

5. **Update Imports:**
   ```python
   from .base import BaseRealtimeConsumer
   ```

6. **Test Thoroughly:**
   - Verify authentication still works
   - Check presence tracking
   - Test all message types
   - Verify broadcasts work

## Complete Example: Workshop Consumer

Here's a complete example for a different resource type:

```python
"""
WebSocket consumer for workshop collaboration.
"""
import json
import logging
from typing import Dict, Any
from channels.db import database_sync_to_async
from .base import BaseRealtimeConsumer

logger = logging.getLogger(__name__)


class WorkshopConsumer(BaseRealtimeConsumer):
    """
    Real-time collaboration for workshop sessions.
    
    Allows instructors and participants to collaborate on
    workshop content, see who's active, and receive live updates.
    """
    
    resource_name = "workshops"
    
    async def connect(self):
        """Extract workshop ID and user role."""
        self.workshop_id = self.scope['url_route']['kwargs']['workshop_id']
        await super().connect()
    
    async def get_room_name(self) -> str:
        return f"workshop_{self.workshop_id}"
    
    async def get_presence_room_name(self) -> str:
        return f"workshop_{self.workshop_id}_presence"
    
    async def get_presence_key(self) -> str:
        return f"workshop_presence:{self.workshop_id}"
    
    async def check_permission(self) -> bool:
        """Check if user is instructor or participant."""
        return await self.check_workshop_access()
    
    async def get_user_context(self) -> Dict[str, Any]:
        """Include user role in context."""
        role = await self.get_user_role()
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': self.user.get_full_name(),
            'role': role,  # 'instructor' or 'participant'
            'workshop_id': str(self.workshop_id),
        }
    
    async def handle_authenticated_message(self, message_type: str, data: dict):
        """Handle workshop-specific messages."""
        if message_type == 'content.update':
            # User is editing content
            await self.broadcast_content_update(data)
        elif message_type == 'cursor.move':
            # User moved cursor (for collaborative editing)
            await self.broadcast_cursor_position(data)
        else:
            logger.debug(f"[workshops] Unhandled: {message_type}")
    
    # Channel layer event handlers
    
    async def workshop_event(self, event: Dict[str, Any]):
        """Handle workshop content broadcasts."""
        data = event.get('data', {})
        await self.send(text_data=json.dumps(data))
    
    async def cursor_event(self, event: Dict[str, Any]):
        """Handle cursor position broadcasts."""
        data = event.get('data', {})
        await self.send(text_data=json.dumps(data))
    
    # Workshop-specific methods
    
    @database_sync_to_async
    def check_workshop_access(self) -> bool:
        """Verify user can access workshop."""
        from apps.workshops.models import Workshop
        try:
            workshop = Workshop.objects.get(id=self.workshop_id)
            return (
                workshop.instructor == self.user or
                workshop.participants.filter(id=self.user.id).exists() or
                self.user.is_staff
            )
        except Workshop.DoesNotExist:
            return False
    
    @database_sync_to_async
    def get_user_role(self) -> str:
        """Get user's role in workshop."""
        from apps.workshops.models import Workshop
        workshop = Workshop.objects.get(id=self.workshop_id)
        if workshop.instructor == self.user:
            return 'instructor'
        return 'participant'
    
    async def broadcast_content_update(self, data: dict):
        """Broadcast content changes to all participants."""
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'workshop_event',
                'data': {
                    'type': 'content.updated',
                    'user_id': self.user.id,
                    'content': data.get('content'),
                    'timestamp': timezone.now().isoformat()
                }
            }
        )
    
    async def broadcast_cursor_position(self, data: dict):
        """Broadcast cursor position to other users."""
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'cursor_event',
                'data': {
                    'type': 'cursor.moved',
                    'user_id': self.user.id,
                    'position': data.get('position'),
                    'timestamp': timezone.now().isoformat()
                }
            }
        )
```

## Summary

`BaseRealtimeConsumer` provides a complete, production-ready foundation for building real-time features in Django Channels. It handles all the boilerplate code for authentication, presence tracking, and connection management, allowing you to focus on your resource-specific logic.

Key benefits:
- **Consistent patterns** across all real-time features
- **Less code duplication** - write once, reuse everywhere
- **Production-ready** error handling and logging
- **Secure** JWT authentication with proper permission checks
- **Scalable** Redis-based presence tracking
- **Maintainable** clear separation of concerns

Start with the example consumers, customize for your resources, and build powerful real-time features with confidence!
