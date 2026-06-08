"""
WebSocket consumer for real-time event question updates.

Handles WebSocket connections for the registration form builder,
broadcasting question create/update/delete events to connected clients.
Supports WebSocket-first architecture with mutation handlers.
"""
import json
import logging
from typing import Dict, Any, Optional

from channels.db import database_sync_to_async
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

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
    - WebSocket-first mutation handlers (create/update/delete/reorder)
    - Transaction ID tracking for client-side deduplication
    - Presence tracking for active editors (inherited from base)
    - Ping/pong keepalive (inherited from base)
    
    Message Types Received (Client → Server):
    - question.create: Create new question
    - question.update: Update existing question
    - question.delete: Delete question
    - question.reorder: Bulk reorder questions
    
    Message Types Sent (Server → Client):
    - question.created: New question added (broadcast to all)
    - question.updated: Question modified (broadcast to all)
    - question.deleted: Question removed (broadcast to all)
    - question.reordered: Questions reordered (broadcast to all)
    - error: Validation/permission error (sent to sender only)
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
        
        Extracts event_identifier from URL route, resolves it to an event object,
        and sets up context for room naming and permission checks.
        """
        # Extract event_identifier from URL route
        self.event_identifier = self.scope['url_route']['kwargs']['event_identifier']
        
        # Resolve event and store it on the consumer instance
        self.event = await self.get_event()
        
        if not self.event:
            logger.warning(f"[questions] Event not found for identifier: {self.event_identifier}")
            await self.close()
            return
            
        # Use the event's UUID for all internal operations
        self.event_id = self.event.event_id
        
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
        if not self.event:
            return False
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
        
        Routes authenticated client messages to appropriate mutation handlers.
        Supports CRUD operations and bulk reordering.
        
        Args:
            message_type: Message type from client
            data: Full message dictionary including txn_id and mutation data
        """
        logger.debug(
            f"[questions] Received message type '{message_type}' "
            f"from user {self.user.email}"
        )
        
        # Route to appropriate handler
        if message_type == 'question.create':
            await self.handle_question_create(data)
        elif message_type == 'question.update':
            await self.handle_question_update(data)
        elif message_type == 'question.delete':
            await self.handle_question_delete(data)
        elif message_type == 'question.reorder':
            await self.handle_question_reorder(data)
        else:
            logger.debug(
                f"[questions] Unhandled message type: {message_type} "
                f"from user {self.user.email}"
            )
    
    # Mutation Handlers
    
    async def handle_question_create(self, data: dict):
        """Handle question creation from WebSocket."""
        txn_id = data.get('txn_id')
        question_data = data.get('data', {})
        
        try:
            if not question_data.get('question_title'):
                await self.send_error_to_sender(
                    txn_id=txn_id, error='Question title is required', code='VALIDATION_ERROR'
                )
                return
            
            question_data['event_id'] = self.event_id
            result = await self.create_question_db(question_data)
            
            if result['success']:
                await self.broadcast_to_room({
                    'type': 'question.created',
                    'txn_id': txn_id,
                    'question': result['question'],
                    'actor': self.get_actor_info(),
                    'timestamp': timezone.now().isoformat()
                })
                logger.info(f"[questions] Created question {result['question']['id']} by {self.user.email}")
            else:
                await self.send_error_to_sender(txn_id=txn_id, error=result['error'], code=result['code'])
        except Exception as e:
            logger.error(f"[questions] Error creating question: {str(e)}", exc_info=True)
            await self.send_error_to_sender(txn_id=txn_id, error='Internal server error', code='SERVER_ERROR')
    
    async def handle_question_update(self, data: dict):
        """Handle question update from WebSocket."""
        txn_id = data.get('txn_id')
        question_id = data.get('question_id')
        update_data = data.get('data', {})
        
        try:
            if not question_id:
                await self.send_error_to_sender(txn_id=txn_id, error='Question ID is required', code='VALIDATION_ERROR')
                return
            
            result = await self.update_question_db(question_id, update_data)
            
            if result['success']:
                await self.broadcast_to_room({
                    'type': 'question.updated',
                    'txn_id': txn_id,
                    'question': result['question'],
                    'actor': self.get_actor_info(),
                    'timestamp': timezone.now().isoformat()
                })
                logger.info(f"[questions] Updated question {question_id} by {self.user.email}")
            else:
                await self.send_error_to_sender(txn_id=txn_id, error=result['error'], code=result['code'])
        except Exception as e:
            logger.error(f"[questions] Error updating question: {str(e)}", exc_info=True)
            await self.send_error_to_sender(txn_id=txn_id, error='Internal server error', code='SERVER_ERROR')
    
    async def handle_question_delete(self, data: dict):
        """Handle question deletion from WebSocket."""
        txn_id = data.get('txn_id')
        question_id = data.get('question_id')
        
        try:
            if not question_id:
                await self.send_error_to_sender(txn_id=txn_id, error='Question ID is required', code='VALIDATION_ERROR')
                return
            
            result = await self.delete_question_db(question_id)
            
            if result['success']:
                await self.broadcast_to_room({
                    'type': 'question.deleted',
                    'txn_id': txn_id,
                    'question_id': question_id,
                    'actor': self.get_actor_info(),
                    'timestamp': timezone.now().isoformat()
                })
                logger.info(f"[questions] Deleted question {question_id} by {self.user.email}")
            else:
                await self.send_error_to_sender(txn_id=txn_id, error=result['error'], code=result['code'])
        except Exception as e:
            logger.error(f"[questions] Error deleting question: {str(e)}", exc_info=True)
            await self.send_error_to_sender(txn_id=txn_id, error='Internal server error', code='SERVER_ERROR')
    
    async def handle_question_reorder(self, data: dict):
        """Handle bulk question reordering from WebSocket."""
        txn_id = data.get('txn_id')
        questions_order = data.get('questions', [])
        
        try:
            if not questions_order or not isinstance(questions_order, list):
                await self.send_error_to_sender(txn_id=txn_id, error='Questions array is required', code='VALIDATION_ERROR')
                return
            
            for item in questions_order:
                if 'id' not in item or 'order' not in item:
                    await self.send_error_to_sender(txn_id=txn_id, error='Each question must have id and order', code='VALIDATION_ERROR')
                    return
            
            result = await self.reorder_questions_db(questions_order)
            
            if result['success']:
                await self.broadcast_to_room({
                    'type': 'question.reordered',
                    'txn_id': txn_id,
                    'questions': questions_order,
                    'actor': self.get_actor_info(),
                    'timestamp': timezone.now().isoformat()
                })
                logger.info(f"[questions] Reordered {len(questions_order)} questions by {self.user.email}")
            else:
                await self.send_error_to_sender(txn_id=txn_id, error=result['error'], code=result['code'])
        except Exception as e:
            logger.error(f"[questions] Error reordering questions: {str(e)}", exc_info=True)
            await self.send_error_to_sender(txn_id=txn_id, error='Internal server error', code='SERVER_ERROR')
    
    # Database Operations
    
    @database_sync_to_async
    def get_event(self):
        """
        Fetches the event from the database using either a UUID or a URL-safe title.

        This method attempts to retrieve an event based on the `event_identifier` 
        provided in the URL. It first tries to match it as a UUID. If that fails, 
        it assumes the identifier is a `url_safe_title` and queries the database accordingly.

        Returns:
            The event object if found, otherwise None.
        """
        from uuid import UUID
        from apps.events.models import Event
        from django.db.models import Q

        try:
            # First, try to interpret the identifier as a UUID
            event_uuid = UUID(self.event_identifier)
            return Event.objects.get(event_id=event_uuid)
        except (ValueError, Event.DoesNotExist):
            # If it's not a valid UUID or no event is found,
            # try finding it by the url_safe_title
            try:
                return Event.objects.get(url_safe_title=self.event_identifier)
            except Event.DoesNotExist:
                # If no event is found by either method, return None
                return None

    @database_sync_to_async
    def create_question_db(self, question_data: dict) -> dict:
        """Create question in database with validation."""
        from apps.events.api.serializers import EventQuestionSerializer
        from apps.events.models import Event
        try:
            try:
                event = Event.objects.get(id=question_data['event'])
            except Event.DoesNotExist:
                return {'success': False, 'error': 'Event not found', 'code': 'NOT_FOUND'}
            serializer_data = {**question_data, 'event': event.event_id}
            serializer_data.pop('event_id', None)
            
            # Clean data based on question type
            question_type = serializer_data.get('question_type')
            
            # Remove min_value and max_value for non-slider questions
            if question_type != 'slider':
                serializer_data.pop('min_value', None)
                serializer_data.pop('max_value', None)
            
            # Remove options for non-choice questions
            if question_type not in ['multiple_choice', 'single_choice']:
                serializer_data.pop('options', None)
            serializer = EventQuestionSerializer(data=serializer_data, context={'request': None})
            
            if not serializer.is_valid():
                error_msg = '; '.join([f"{field}: {', '.join(errors)}" for field, errors in serializer.errors.items()])
                return {'success': False, 'error': error_msg, 'code': 'VALIDATION_ERROR'}
            
            with transaction.atomic():
                question = serializer.save()
                question.refresh_from_db()
                response_serializer = EventQuestionSerializer(question)
                question_json = json.loads(json.dumps(response_serializer.data, cls=DjangoJSONEncoder))
            
            return {'success': True, 'question': question_json}
        except Exception as e:
            logger.error(f"[questions] Database error creating question: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e), 'code': 'DATABASE_ERROR'}
    
    @database_sync_to_async
    def update_question_db(self, question_id: str, update_data: dict) -> dict:
        """Update question in database with validation."""
        from apps.events.api.serializers import EventQuestionSerializer
        from apps.events.models import EventQuestion
        
        try:
            try:
                question = EventQuestion.objects.select_related('event').prefetch_related('options').get(
                    id=question_id, event__event_id=self.event_id
                )
            except EventQuestion.DoesNotExist:
                return {'success': False, 'error': 'Question not found', 'code': 'NOT_FOUND'}
            
            # Clean data based on question type (use existing or new question_type)
            question_type = update_data.get('question_type', question.question_type)
            
            # Remove min_value and max_value for non-slider questions
            if question_type != 'slider':
                update_data.pop('min_value', None)
                update_data.pop('max_value', None)
            
            # Remove options for non-choice questions
            if question_type not in ['multiple_choice', 'single_choice']:
                update_data.pop('options', None)
            
            serializer = EventQuestionSerializer(question, data=update_data, partial=True, context={'request': None})
            
            if not serializer.is_valid():
                error_msg = '; '.join([f"{field}: {', '.join(errors)}" for field, errors in serializer.errors.items()])
                return {'success': False, 'error': error_msg, 'code': 'VALIDATION_ERROR'}
            
            with transaction.atomic():
                question = serializer.save()
                question.refresh_from_db()
                response_serializer = EventQuestionSerializer(question)
                question_json = json.loads(json.dumps(response_serializer.data, cls=DjangoJSONEncoder))
            
            return {'success': True, 'question': question_json}
        except Exception as e:
            logger.error(f"[questions] Database error updating question: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e), 'code': 'DATABASE_ERROR'}
    
    @database_sync_to_async
    def delete_question_db(self, question_id: str) -> dict:
        """Delete question from database."""
        from apps.events.models import EventQuestion
        
        try:
            try:
                question = EventQuestion.objects.get(id=question_id, event__event_id=self.event_id)
            except EventQuestion.DoesNotExist:
                return {'success': False, 'error': 'Question not found', 'code': 'NOT_FOUND'}
            
            with transaction.atomic():
                question.delete()
            
            return {'success': True}
        except Exception as e:
            logger.error(f"[questions] Database error deleting question: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e), 'code': 'DATABASE_ERROR'}
    
    @database_sync_to_async
    def reorder_questions_db(self, questions_order: list) -> dict:
        """Reorder questions using two-phase update strategy."""
        from apps.events.models import EventQuestion
        
        try:
            with transaction.atomic():
                question_ids = [item['id'] for item in questions_order]
                questions = EventQuestion.objects.filter(
                    event__event_id=self.event_id
                ).select_for_update().order_by('id')
                
                questions_dict = {str(q.id): q for q in questions}
                
                for item in questions_order:
                    if str(item['id']) not in questions_dict:
                        return {'success': False, 'error': f"Question {item['id']} not found", 'code': 'NOT_FOUND'}
                
                # Phase 1: Move to temporary high orders
                temp_order_start = 900000
                for idx, item in enumerate(questions_order):
                    question = questions_dict[str(item['id'])]
                    question.order = temp_order_start + idx
                    question.save(update_fields=['order'])
                
                # Phase 2: Update to final orders
                for item in questions_order:
                    question = questions_dict[str(item['id'])]
                    question.order = item['order']
                    question.save(update_fields=['order'])
            
            return {'success': True}
        except Exception as e:
            logger.error(f"[questions] Database error reordering questions: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e), 'code': 'DATABASE_ERROR'}
    
    # Helper Methods
    
    def get_actor_info(self) -> dict:
        """Get current user info for broadcast messages."""
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': getattr(self.user, 'get_full_name', lambda: self.user.email)()
        }
    
    async def send_error_to_sender(self, txn_id: Optional[str], error: str, code: str):
        """Send error message to sender only (not broadcast)."""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'txn_id': txn_id,
            'error': error,
            'code': code,
            'timestamp': timezone.now().isoformat()
        }))
        logger.warning(f"[questions] Error sent to {self.user.email}: {code} - {error} (txn_id: {txn_id})")
    
    async def broadcast_to_room(self, message: dict):
        """Broadcast message to all clients in the room."""
        await self.channel_layer.group_send(self.group_name, {'type': 'question_event', 'data': message})
    
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
        Check if the authenticated user has permission to manage the event.
        Permissions are granted to the event creator, staff members with
        the 'manage_events' permission, and superusers.
        """
        if not self.user or not self.user.is_authenticated:
            return False

        if self.user.is_superuser or self.user.is_staff:
            return True

        # Check if the user is the event creator
        if self.event.created_by == self.user:
            return True

        # Check if the user is a staff member of the event's organisation
        # with the necessary permission.
        # is_staff_member = self.event.organisation.staff.filter(
        #     user=self.user,
        #     permissions__codename='manage_events'
        # ).exists()

        is_staff_member = self.event.is_staff(self.user)

        return is_staff_member

