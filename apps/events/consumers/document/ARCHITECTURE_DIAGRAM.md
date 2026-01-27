# BaseRealtimeConsumer Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Client (Browser/App)                          │
│                                                                       │
│  ws://host/ws/events/123/questions/                                   │
│  ├─ Connect                                                           │
│  ├─ Send: { type: "authenticate", token: "jwt..." }                  │
│  ├─ Receive: { type: "authenticated", user: {...} }                  │
│  ├─ Receive: { type: "presence.list", users: [...] }                 │
│  ├─ Send: { type: "ping" }                                           │
│  ├─ Receive: { type: "pong" }                                        │
│  ├─ Receive: { type: "question.created", question: {...} }           │
│  └─ Disconnect                                                        │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                │ WebSocket Connection
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                     EventQuestionConsumer                             │
│                    (extends BaseRealtimeConsumer)                     │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Resource-Specific Implementation                             │    │
│  ├─────────────────────────────────────────────────────────────┤    │
│  │ • resource_name = "questions"                                │    │
│  │ • connect() - Extract event_id from URL                      │    │
│  │ • get_room_name() - Return "event_{id}_questions"            │    │
│  │ • get_presence_room_name() - Return "event_{id}_presence"    │    │
│  │ • get_presence_key() - Return "event_presence:{id}"          │    │
│  │ • check_permission() - Query Event model for access          │    │
│  │ • get_user_context() - Return user + event_id                │    │
│  │ • handle_authenticated_message() - Log for future features   │    │
│  │ • question_event() - Forward question broadcasts to client   │    │
│  │ • check_event_permission() - DB query for event access       │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Inherited from BaseRealtimeConsumer                          │    │
│  ├─────────────────────────────────────────────────────────────┤    │
│  │ • connect() - Accept WebSocket, initialize state             │    │
│  │ • disconnect() - Clean up presence, leave groups             │    │
│  │ • receive() - Route messages by auth state                   │    │
│  │ • handle_authentication() - Validate JWT, check permissions  │    │
│  │ • send_error() - Send error with optional close              │    │
│  │ • send_pong() - Respond to keepalive ping                    │    │
│  │ • broadcast_presence() - Notify join/leave events            │    │
│  │ • presence_event() - Forward presence updates                │    │
│  │ • get_active_users() - Query Redis for connected users       │    │
│  │ • add_to_presence() - Add user to Redis set                  │    │
│  │ • remove_from_presence() - Remove user from Redis set        │    │
│  │ • authenticate_token() - Validate JWT and extract user       │    │
│  └─────────────────────────────────────────────────────────────┘    │
└───────────────────────────┬───────────────────────┬─────────────────┘
                            │                       │
                            │                       │
        ┌───────────────────▼──────┐    ┌──────────▼──────────────┐
        │   Channel Layer (Redis)  │    │    Redis (Presence)     │
        │                          │    │                         │
        │  Groups:                 │    │  Keys:                  │
        │  • event_123_questions   │    │  • event_presence:123   │
        │  • event_123_presence    │    │                         │
        │                          │    │  Set Members:           │
        │  Messages:               │    │  • {"id":1,"email":...} │
        │  • question_event        │    │  • {"id":2,"email":...} │
        │  • presence_event        │    │  • {"id":3,"email":...} │
        └──────────▲───────────────┘    └─────────────────────────┘
                   │
                   │ Broadcast via channel_layer.group_send()
                   │
        ┌──────────┴────────────────────────────────────────────┐
        │         Django Code (Views/Signals/Tasks)             │
        │                                                       │
        │  from channels.layers import get_channel_layer       │
        │  from asgiref.sync import async_to_sync              │
        │                                                       │
        │  channel_layer = get_channel_layer()                 │
        │  async_to_sync(channel_layer.group_send)(            │
        │      "event_123_questions",                          │
        │      {                                               │
        │          'type': 'question_event',                   │
        │          'data': {                                   │
        │              'type': 'question.created',             │
        │              'question': {...}                       │
        │          }                                           │
        │      }                                               │
        │  )                                                   │
        └──────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                      Connection Flow Sequence                         │
└─────────────────────────────────────────────────────────────────────┘

Client                         Consumer                    Redis/Channel Layer
  │                               │                                │
  ├─ Connect ───────────────────>│                                │
  │                               ├─ accept()                      │
  │                               ├─ authenticated = False         │
  │                               ├─ user = None                   │
  │<────────── Connected ─────────┤                                │
  │                               │                                │
  ├─ authenticate message ──────>│                                │
  │   { token: "jwt..." }         ├─ authenticate_token()          │
  │                               ├─ check_permission()            │
  │                               ├─ get_room_name()               │
  │                               ├─ join groups ─────────────────>│
  │                               ├─ authenticated = True          │
  │<─ authenticated message ──────┤                                │
  │   { user: {...} }             │                                │
  │                               ├─ add_to_presence() ───────────>│
  │                               │                          [SADD key user]
  │                               ├─ broadcast_presence() ────────>│
  │                               │                       [group_send presence]
  │<─ user.joined ────────────────┤<───────────────────────────────┤
  │   (broadcast to all)          │                                │
  │                               ├─ get_active_users() ──────────>│
  │                               │                          [SMEMBERS key]
  │<─ presence.list ──────────────┤<───────────────────────────────┤
  │   { users: [...] }            │                                │
  │                               │                                │
  ├─ ping ───────────────────────>│                                │
  │<─ pong ───────────────────────┤                                │
  │                               │                                │
  │                               │<── group_send ─────────────────┤
  │                               │    (from Django code)          │
  │<─ question.created ───────────┤                                │
  │   { question: {...} }         │                                │
  │                               │                                │
  ├─ Disconnect ─────────────────>│                                │
  │                               ├─ remove_from_presence() ───────>│
  │                               │                          [SREM key user]
  │                               ├─ broadcast_presence() ────────>│
  │                               │                       [group_send presence]
  │                               ├─ leave groups ─────────────────>│
  │<────────── Closed ────────────┤                                │


┌─────────────────────────────────────────────────────────────────────┐
│                    Class Hierarchy & Inheritance                      │
└─────────────────────────────────────────────────────────────────────┘

                    AsyncWebsocketConsumer (Django Channels)
                               │
                               │ extends
                               │
                    ┌──────────▼───────────┐
                    │  BaseRealtimeConsumer │  (abstract base class)
                    │         (ABC)         │
                    └──────────┬───────────┘
                               │
                 ┌─────────────┼──────────────────┐
                 │             │                  │
        ┌────────▼───────┐    │         ┌────────▼────────┐
        │ EventQuestion  │    │         │  Workshop       │
        │   Consumer     │    │         │  Consumer       │
        └────────────────┘    │         └─────────────────┘
                              │
                     ┌────────▼────────┐
                     │   Booking       │
                     │   Consumer      │
                     │   (future)      │
                     └─────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                        Abstract Method Pattern                        │
└─────────────────────────────────────────────────────────────────────┘

BaseRealtimeConsumer (Base Class)
├─ Abstract Methods (Subclass MUST implement)
│  ├─ resource_name (property)              → "questions"
│  ├─ get_room_name()                       → "event_123_questions"
│  ├─ get_presence_room_name()              → "event_123_presence"
│  ├─ get_presence_key()                    → "event_presence:123"
│  ├─ check_permission()                    → True/False
│  ├─ get_user_context()                    → {"id":1, "email":...}
│  └─ handle_authenticated_message()        → (custom logic)
│
└─ Concrete Methods (Inherited, can be overridden)
   ├─ connect()                              → Accept, initialize
   ├─ disconnect()                           → Cleanup, leave groups
   ├─ receive()                              → Route messages
   ├─ handle_authentication()                → JWT validation
   ├─ send_error()                           → Error response
   ├─ send_pong()                            → Keepalive response
   ├─ broadcast_presence()                   → Join/leave broadcast
   ├─ presence_event()                       → Forward presence
   ├─ get_active_users()                     → Query Redis
   ├─ add_to_presence()                      → Add to Redis
   ├─ remove_from_presence()                 → Remove from Redis
   └─ authenticate_token()                   → Validate JWT


┌─────────────────────────────────────────────────────────────────────┐
│                         Message Type Routing                          │
└─────────────────────────────────────────────────────────────────────┘

Client Message → receive() → Route by type and auth state:

Unauthenticated:
  ├─ "authenticate" → handle_authentication() → Join groups, send confirmation
  └─ anything else  → send_error("Not authenticated") → close(4003)

Authenticated:
  ├─ "ping"         → send_pong()
  └─ custom types   → handle_authenticated_message() (subclass implements)

Channel Layer Message → Route by type (method name):
  ├─ "question_event"  → question_event()    (forward to client)
  ├─ "presence_event"  → presence_event()    (forward to client)
  └─ "custom_event"    → custom_event()      (subclass implements)


┌─────────────────────────────────────────────────────────────────────┐
│                        Redis Presence Structure                       │
└─────────────────────────────────────────────────────────────────────┘

Redis Key: event_presence:123
Type: Set
TTL: 86400 seconds (24 hours)

Members (JSON strings):
├─ '{"id": 1, "email": "user1@example.com", "name": "User One"}'
├─ '{"id": 2, "email": "user2@example.com", "name": "User Two"}'
└─ '{"id": 3, "email": "user3@example.com", "name": "User Three"}'

Operations:
├─ SADD event_presence:123 '{"id": 4, ...}'     (add user)
├─ SREM event_presence:123 '{"id": 4, ...}'     (remove user)
├─ SMEMBERS event_presence:123                  (get all users)
└─ EXPIRE event_presence:123 86400              (refresh TTL)


┌─────────────────────────────────────────────────────────────────────┐
│                    Channel Layer Group Structure                      │
└─────────────────────────────────────────────────────────────────────┘

Main Group: event_123_questions
├─ channel_name_1 (User 1's connection)
├─ channel_name_2 (User 2's connection)
└─ channel_name_3 (User 3's connection)

Presence Group: event_123_presence
├─ channel_name_1 (User 1's connection)
├─ channel_name_2 (User 2's connection)
└─ channel_name_3 (User 3's connection)

Broadcasting:
├─ Main group receives:      question.created, question.updated, question.deleted
└─ Presence group receives:  user.joined, user.left

```
