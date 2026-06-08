"""
WebSocket consumer for real-time event form collaboration and response feed.

Provides two channel groups per event:
  - event_{event_id}_forms          : form/question mutation broadcasts (staff collaboration)
  - event_{event_id}_form_responses : live feed of response submissions (staff monitoring)

Only event staff, the event creator, and site admins can connect.
The consumer is read-only from the client's perspective; mutations happen via the REST API.
"""
import json
import logging
from typing import Dict, Any

from channels.db import database_sync_to_async
from django.utils import timezone

from .base import BaseRealtimeConsumer

logger = logging.getLogger(__name__)


class EventFormConsumer(BaseRealtimeConsumer):
    """
    WebSocket consumer for real-time event form collaboration.

    Clients connect to: ws://host/ws/events/{event_identifier}/forms/

    On successful authentication the consumer joins two channel-layer groups:
      1. event_{event_id}_forms          – relays form/question mutations
      2. event_{event_id}_form_responses – relays new/updated response submissions

    Message Types Sent (Server → Client):
      - form.created / form.updated / form.deleted / form.published / form.closed
      - form.questions_bulk_created / form.questions_reordered
      - question.created / question.updated / question.deleted
      - response.created / response.updated
      - authenticated, error, pong, presence.list, user.joined, user.left  (inherited)

    No client-initiated mutations are accepted (read-only consumer).
    """

    resource_name = "forms"

    async def connect(self):
        self.event_identifier = self.scope['url_route']['kwargs']['event_identifier']
        self.event = await self.get_event()

        if not self.event:
            logger.warning(f"[forms] Event not found for identifier: {self.event_identifier}")
            await self.close()
            return

        self.event_id = self.event.event_id
        self.responses_group_name = f"event_{self.event_id}_form_responses"

        await super().connect()

    async def receive(self, text_data: str):
        """
        Extend base receive to join the form_responses group immediately
        after a successful authentication handshake.
        """
        import json as _json
        was_authenticated = getattr(self, 'authenticated', False)
        await super().receive(text_data)
        # If we just became authenticated, join the second group
        if not was_authenticated and getattr(self, 'authenticated', False):
            await self.channel_layer.group_add(self.responses_group_name, self.channel_name)
            logger.debug(
                f"[forms] Joined responses group {self.responses_group_name} for user {self.user.email}"
            )

    async def disconnect(self, code):
        """Leave both groups on disconnect."""
        if hasattr(self, 'responses_group_name') and self.channel_layer:
            try:
                await self.channel_layer.group_discard(self.responses_group_name, self.channel_name)
            except Exception:
                pass
        await super().disconnect(code)

    # ── Required abstract method implementations ───────────────────────────

    async def get_room_name(self) -> str:
        return f"event_{self.event_id}_forms"

    async def get_presence_room_name(self) -> str:
        return f"event_{self.event_id}_forms_presence"

    async def get_presence_key(self) -> str:
        return f"event_forms_presence:{self.event_id}"

    async def check_permission(self) -> bool:
        if not self.event:
            return False
        return await self.check_event_permission()

    async def get_user_context(self) -> Dict[str, Any]:
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': getattr(self.user, 'get_full_name', lambda: self.user.email)() or self.user.email,
            'event_id': str(self.event_id),
        }

    async def handle_authenticated_message(self, message_type: str, data: dict):
        """
        This consumer is read-only; no client-initiated mutations are accepted.
        Log unknown message types for debugging.
        """
        logger.debug(f"[forms] Received unhandled message type '{message_type}' from {self.user.email}")

    # ── Channel layer event handlers ───────────────────────────────────────

    async def form_event(self, event: Dict[str, Any]):
        """
        Forward form mutation broadcasts (create/update/delete/publish/close/reorder)
        to the connected WebSocket client.

        Triggered by channel_layer.group_send(..., {'type': 'form_event', 'data': {...}})
        """
        try:
            data = event.get('data', {})
            await self.send(text_data=json.dumps(data))
            logger.debug(f"[forms] Forwarded form_event '{data.get('type')}' to {self.user.email}")
        except Exception as exc:
            logger.error(f"[forms] Error forwarding form_event: {exc}", exc_info=True)

    async def form_response_event(self, event: Dict[str, Any]):
        """
        Forward response submission events to the connected WebSocket client.

        Triggered by channel_layer.group_send(..., {'type': 'form_response_event', 'data': {...}})
        """
        try:
            data = event.get('data', {})
            await self.send(text_data=json.dumps(data))
            logger.debug(f"[forms] Forwarded form_response_event '{data.get('type')}' to {self.user.email}")
        except Exception as exc:
            logger.error(f"[forms] Error forwarding form_response_event: {exc}", exc_info=True)

    # ── Database helpers ───────────────────────────────────────────────────

    @database_sync_to_async
    def get_event(self):
        """Resolve event_identifier to an Event object (UUID or url_safe_title)."""
        from uuid import UUID
        from apps.events.models import Event

        try:
            event_uuid = UUID(self.event_identifier)
            return Event.objects.get(event_id=event_uuid)
        except (ValueError, Event.DoesNotExist):
            try:
                return Event.objects.get(url_safe_title=self.event_identifier)
            except Event.DoesNotExist:
                return None

    @database_sync_to_async
    def check_event_permission(self) -> bool:
        """Grant access to event creators, event staff members, and site admins."""
        if not self.user or not self.user.is_authenticated:
            return False
        if self.user.is_superuser or self.user.is_staff:
            return True
        if self.event.created_by == self.user:
            return True
        return self.event.is_staff(self.user)
