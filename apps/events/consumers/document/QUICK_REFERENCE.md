# BaseRealtimeConsumer Quick Reference

## 🚀 Quick Start: Create a New Consumer in 5 Minutes

```python
# apps/myapp/consumers/my_consumer.py
from typing import Dict, Any
from channels.db import database_sync_to_async
from apps.events.consumers.base import BaseRealtimeConsumer

class MyResourceConsumer(BaseRealtimeConsumer):
    """Real-time updates for MyResource."""
    
    resource_name = "my_resources"  # Used in logs
    
    async def connect(self):
        # Extract URL parameters BEFORE calling super()
        self.resource_id = self.scope['url_route']['kwargs']['resource_id']
        await super().connect()
    
    # REQUIRED: Implement these 6 methods
    
    async def get_room_name(self) -> str:
        return f"resource_{self.resource_id}"
    
    async def get_presence_room_name(self) -> str:
        return f"resource_{self.resource_id}_presence"
    
    async def get_presence_key(self) -> str:
        return f"resource_presence:{self.resource_id}"
    
    async def check_permission(self) -> bool:
        return await self.check_my_permission()
    
    async def get_user_context(self) -> Dict[str, Any]:
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': self.user.get_full_name(),
        }
    
    async def handle_authenticated_message(self, message_type: str, data: dict):
        # Handle custom messages from clients
        pass
    
    # OPTIONAL: Add channel layer event handlers
    
    async def resource_event(self, event: Dict[str, Any]):
        """Handle broadcasts from Django code."""
        await self.send(text_data=json.dumps(event.get('data', {})))
    
    # HELPER: Database queries
    
    @database_sync_to_async
    def check_my_permission(self) -> bool:
        from myapp.models import MyResource
        resource = MyResource.objects.get(id=self.resource_id)
        return resource.user == self.user or self.user.is_staff
```

## 📋 Required Implementations Checklist

- [ ] Set `resource_name` property
- [ ] Override `connect()` to extract URL parameters
- [ ] Implement `get_room_name()` 
- [ ] Implement `get_presence_room_name()`
- [ ] Implement `get_presence_key()`
- [ ] Implement `check_permission()`
- [ ] Implement `get_user_context()`
- [ ] Implement `handle_authenticated_message()`
- [ ] Add channel layer event handlers (e.g., `resource_event()`)
- [ ] Add routing configuration
- [ ] Test connection flow

## 🎯 Naming Conventions Reference

| Item | Format | Example |
|------|--------|---------|
| Resource name | `lowercase_plural` | `"questions"`, `"bookings"` |
| Room name | `{resource}_{id}_{purpose}` | `"event_123_questions"` |
| Presence room | `{resource}_{id}_presence` | `"event_123_presence"` |
| Redis key | `{resource}_presence:{id}` | `"event_presence:123"` |
| Message type | `{resource}.{action}` | `"question.created"` |
| Log prefix | `[{resource}]` | `"[questions]"` |
| Consumer class | `{Resource}{Purpose}Consumer` | `EventQuestionConsumer` |

## 🔌 Routing Configuration

```python
# apps/myapp/routing.py
from django.urls import path
from .consumers import MyResourceConsumer

websocket_urlpatterns = [
    path('ws/resources/<str:resource_id>/', MyResourceConsumer.as_asgi()),
]
```

## 📡 Broadcasting from Django Code

### From Views/Signals/Tasks

```python
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone

channel_layer = get_channel_layer()

# Send to all clients in room
async_to_sync(channel_layer.group_send)(
    f"resource_{resource_id}",  # Must match get_room_name()
    {
        'type': 'resource_event',  # Converts to resource_event() method
        'data': {
            'type': 'resource.created',  # Client message type
            'resource': {
                'id': str(resource.id),
                'name': resource.name,
                # ... more fields
            },
            'timestamp': timezone.now().isoformat()
        }
    }
)
```

### From Signals (Auto-broadcast on save)

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=MyResource)
def broadcast_resource_change(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f"resource_{instance.id}",
        {
            'type': 'resource_event',
            'data': {
                'type': 'resource.created' if created else 'resource.updated',
                'resource': serialize_resource(instance),
                'timestamp': timezone.now().isoformat()
            }
        }
    )
```

## 💻 Client-Side Connection Example

```javascript
// 1. Connect
const ws = new WebSocket('ws://localhost:8000/ws/resources/123/');

// 2. Send authentication
ws.onopen = () => {
    ws.send(JSON.stringify({
        type: 'authenticate',
        token: localStorage.getItem('jwt_token')
    }));
};

// 3. Handle messages
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch (data.type) {
        case 'authenticated':
            console.log('Connected as:', data.user);
            break;
        
        case 'presence.list':
            console.log('Active users:', data.users);
            break;
        
        case 'user.joined':
            console.log('User joined:', data.user);
            break;
        
        case 'user.left':
            console.log('User left:', data.user);
            break;
        
        case 'resource.created':
        case 'resource.updated':
            console.log('Resource changed:', data.resource);
            updateUI(data.resource);
            break;
        
        case 'pong':
            // Keepalive response
            break;
        
        case 'error':
            console.error('Error:', data.message);
            break;
    }
};

// 4. Send keepalive pings
setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
    }
}, 30000);

// 5. Handle errors
ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

// 6. Handle close
ws.onclose = (event) => {
    console.log('WebSocket closed:', event.code);
    
    if (event.code === 4003) {
        // Authentication failed - redirect to login
        window.location.href = '/login';
    } else {
        // Network error - attempt reconnect
        setTimeout(reconnect, 3000);
    }
};
```

## 🧪 Testing Template

```python
import pytest
from channels.testing import WebsocketCommunicator
from myapp.consumers import MyResourceConsumer

@pytest.mark.asyncio
@pytest.mark.django_db
async def test_connect_and_authenticate(user, jwt_token):
    """Test connection and authentication flow."""
    communicator = WebsocketCommunicator(
        MyResourceConsumer.as_asgi(),
        "/ws/resources/123/"
    )
    
    # Connect
    connected, _ = await communicator.connect()
    assert connected
    
    # Authenticate
    await communicator.send_json_to({
        'type': 'authenticate',
        'token': jwt_token
    })
    
    # Check response
    response = await communicator.receive_json_from()
    assert response['type'] == 'authenticated'
    assert response['user']['id'] == user.id
    
    # Check presence list
    presence = await communicator.receive_json_from()
    assert presence['type'] == 'presence.list'
    
    # Disconnect
    await communicator.disconnect()

@pytest.mark.asyncio
@pytest.mark.django_db
async def test_permission_denied(jwt_token_no_permission):
    """Test permission denial."""
    communicator = WebsocketCommunicator(
        MyResourceConsumer.as_asgi(),
        "/ws/resources/999/"
    )
    
    await communicator.connect()
    await communicator.send_json_to({
        'type': 'authenticate',
        'token': jwt_token_no_permission
    })
    
    response = await communicator.receive_json_from()
    assert response['type'] == 'error'
    assert response['message'] == 'Access denied'
    
    await communicator.disconnect()

@pytest.mark.asyncio
@pytest.mark.django_db
async def test_broadcast(user, jwt_token):
    """Test broadcasting to clients."""
    comm = WebsocketCommunicator(
        MyResourceConsumer.as_asgi(),
        "/ws/resources/123/"
    )
    
    await comm.connect()
    await comm.send_json_to({'type': 'authenticate', 'token': jwt_token})
    await comm.receive_json_from()  # authenticated
    await comm.receive_json_from()  # presence.list
    
    # Trigger broadcast
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "resource_123",
        {
            'type': 'resource_event',
            'data': {'type': 'resource.updated', 'resource': {'id': '123'}}
        }
    )
    
    # Receive broadcast
    msg = await comm.receive_json_from(timeout=1)
    assert msg['type'] == 'resource.updated'
    
    await comm.disconnect()
```

## ⚠️ Common Pitfalls & Solutions

### ❌ Pitfall 1: Not calling `super().connect()`
```python
# WRONG
async def connect(self):
    self.resource_id = self.scope['url_route']['kwargs']['resource_id']
    # Missing super().connect()!

# CORRECT
async def connect(self):
    self.resource_id = self.scope['url_route']['kwargs']['resource_id']
    await super().connect()  # ✓
```

### ❌ Pitfall 2: Wrong channel layer event type
```python
# WRONG - dots in type don't convert to method names
channel_layer.group_send(room, {'type': 'resource.event', ...})

# CORRECT - underscores convert to method names
channel_layer.group_send(room, {'type': 'resource_event', ...})
# Calls: async def resource_event(self, event): ...
```

### ❌ Pitfall 3: Forgetting `@database_sync_to_async`
```python
# WRONG - can't call sync code from async context
async def check_permission(self) -> bool:
    resource = MyResource.objects.get(id=self.resource_id)  # ❌ Error!
    return resource.user == self.user

# CORRECT
async def check_permission(self) -> bool:
    return await self.check_my_permission()

@database_sync_to_async
def check_my_permission(self) -> bool:
    resource = MyResource.objects.get(id=self.resource_id)  # ✓
    return resource.user == self.user
```

### ❌ Pitfall 4: Mismatched room names
```python
# WRONG - room names don't match
async def get_room_name(self) -> str:
    return f"resource_{self.resource_id}"

# Broadcasting code:
channel_layer.group_send(
    f"resources_{self.resource_id}",  # ❌ Different name!
    {...}
)

# CORRECT - must match exactly
async def get_room_name(self) -> str:
    return f"resource_{self.resource_id}"

channel_layer.group_send(
    f"resource_{self.resource_id}",  # ✓ Matches!
    {...}
)
```

### ❌ Pitfall 5: Not handling errors in channel layer handlers
```python
# WRONG - no error handling
async def resource_event(self, event):
    data = event['data']  # ❌ Might not exist!
    await self.send(text_data=json.dumps(data))

# CORRECT
async def resource_event(self, event):
    try:
        data = event.get('data', {})  # ✓ Safe access
        await self.send(text_data=json.dumps(data))
    except Exception as e:
        logger.error(f"Error broadcasting: {str(e)}", exc_info=True)
```

## 🎨 Message Type Patterns

### Server → Client Message Types

| Type | Purpose | Example Payload |
|------|---------|-----------------|
| `authenticated` | Confirmation of authentication | `{user: {...}}` |
| `error` | Error message | `{message: "Error text"}` |
| `pong` | Keepalive response | `{}` |
| `presence.list` | Active users list | `{users: [...]}` |
| `user.joined` | User joined notification | `{user: {...}}` |
| `user.left` | User left notification | `{user: {...}}` |
| `{resource}.created` | Resource created | `{resource: {...}}` |
| `{resource}.updated` | Resource updated | `{resource: {...}}` |
| `{resource}.deleted` | Resource deleted | `{id: "123"}` |

### Client → Server Message Types

| Type | Purpose | Required Fields |
|------|---------|-----------------|
| `authenticate` | Initial authentication | `{token: "jwt..."}` |
| `ping` | Keepalive check | `{}` |
| Custom types | Resource-specific actions | Defined by subclass |

## 📊 What's Included in Base Class

### ✅ Handled by Base Class (You get for free)

- JWT authentication
- User extraction and validation
- Permission checking flow (you provide logic)
- WebSocket connection/disconnection
- Message routing by auth state
- Ping/pong keepalive
- Error handling and logging
- Redis presence tracking
- Active users list
- Join/leave broadcasts
- Channel layer group management
- Error responses with close codes
- Type hints and docstrings

### 🔧 Your Responsibility (Subclass implements)

- Resource identifier (`resource_name`)
- Room naming strategy
- Permission check logic
- User context serialization
- Custom message handling
- Channel layer event handlers
- Database queries
- Business logic

## 🔍 Debugging Tips

### Check WebSocket Connection

```python
# Add to consumer for debugging
async def connect(self):
    logger.info(f"Connection attempt: {self.scope['url_route']}")
    await super().connect()
```

### Log All Messages

```python
async def receive(self, text_data):
    logger.debug(f"Received: {text_data}")
    await super().receive(text_data)
```

### Check Redis Presence

```bash
# In Redis CLI
redis-cli
> SMEMBERS resource_presence:123
> TTL resource_presence:123
```

### Check Channel Layer Groups

```python
# In Django shell
from channels.layers import get_channel_layer
channel_layer = get_channel_layer()

# Send test message
from asgiref.sync import async_to_sync
async_to_sync(channel_layer.group_send)(
    "resource_123",
    {'type': 'resource_event', 'data': {'test': True}}
)
```

## 📚 Full Documentation

- **Complete Guide:** `BASE_REALTIME_CONSUMER_GUIDE.md`
- **Architecture Diagrams:** `ARCHITECTURE_DIAGRAM.md`
- **Refactoring Summary:** `REFACTORING_SUMMARY.md`
- **Source Code:** `base.py` (extensively documented)

## 🆘 Need Help?

1. Check the comprehensive guide: `BASE_REALTIME_CONSUMER_GUIDE.md`
2. Review the example consumers: `questions.py`
3. Check architecture diagrams: `ARCHITECTURE_DIAGRAM.md`
4. Look at docstrings in `base.py`
5. Review test examples in documentation

## 🚀 Next Steps After Creating Consumer

1. ✅ Add consumer to `__init__.py` exports
2. ✅ Add routing in `routing.py`
3. ✅ Create signal handlers for auto-broadcasting
4. ✅ Write unit tests
5. ✅ Write integration tests
6. ✅ Test with real client
7. ✅ Document client-side usage
8. ✅ Deploy and monitor

---

**Happy coding! Build powerful real-time features with confidence! 🎉**
