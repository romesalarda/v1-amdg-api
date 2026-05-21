"""
WebSocket consumer for real-time check-in events.

Clients connect to: ws://host/ws/events/{event_identifier}/checkin/

Read-only consumer — no mutations over WS.  All check-ins are created via
HTTP POST → broadcast here.  Clients can:
  - Set per-connection priority filters (checkin.filter.set)
  - Request paginated history (checkin.history)

The consumer injects `matches_priority_filter` into every forwarded
checkin.occurred broadcast so clients can highlight priority items.
"""
import json
import logging
from typing import Dict, Any, Optional

from channels.db import database_sync_to_async
from django.utils import timezone

from .base import BaseRealtimeConsumer
from apps.attendee.api.serializers import (
    CheckInBroadcastSerializer,
    CheckInFilterSerializer,
    CheckInHistoryRequestSerializer,
)
from apps.events.models import Event
import uuid as uuid_module

logger = logging.getLogger(__name__)


class CheckInConsumer(BaseRealtimeConsumer):
    """
    WebSocket consumer for real-time check-in broadcasts.

    Extends BaseRealtimeConsumer with check-in–specific logic.

    Message Types Received (Client → Server):
    - checkin.filter.set  : Store per-connection priority filters
    - checkin.history     : Return paginated check-in history to this client

    Message Types Sent (Server → Client):
    - checkin.occurred    : A check-in was recorded (broadcast to all, enriched with
                            matches_priority_filter per connection)
    - checkin.history.response : Paginated history items (sender only)
    - error               : Validation / permission error (inherited)
    - authenticated       : Connection established (inherited)
    - pong                : Keepalive response (inherited)
    - user.joined/user.left / presence.list : Presence (inherited)

    Connection Flow (additional to base):
    - Client may include `filters` dict in the authenticate message payload.
      Those are captured before forwarding to base.handle_authentication().
    """

    resource_name = "checkin"

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def connect(self):
        # Initialise state that disconnect() guards against before any early exit.
        self.authenticated = False
        self.user = None
        self.group_name = None
        self.presence_group_name = None
        self.presence_key = None

        self.event_identifier = self.scope['url_route']['kwargs']['event_identifier']
        self.event = await self.get_event()

        if not self.event:
            logger.warning(
                f"[checkin] Event not found for identifier: {self.event_identifier}"
            )
            await self.close()
            return

        self.event_id = self.event.event_id

        # Initialise per-connection filter state (may be populated in receive
        # when intercepting the authenticate message).
        self.priority_filters: dict = {}

        await super().connect()

    # ── Capture filters from authenticate message before forwarding ────────

    async def receive(self, text_data: str):
        """
        Intercept the raw message to capture optional `filters` from the
        authenticate payload before delegating to the base handler.
        """
        try:
            data = json.loads(text_data)
            if data.get('type') == 'authenticate' and 'filters' in data:
                filter_serializer = CheckInFilterSerializer(
                    data=data['filters'] or {}
                )
                if filter_serializer.is_valid():
                    self.priority_filters = filter_serializer.validated_data
                else:
                    # Invalid filters at connect — start with no filters,
                    # client can correct with checkin.filter.set later.
                    logger.debug(
                        f"[checkin] Invalid initial filters from "
                        f"channel {self.channel_name}: "
                        f"{filter_serializer.errors}"
                    )
        except (json.JSONDecodeError, AttributeError):
            pass

        await super().receive(text_data)

    # ── Abstract method implementations ───────────────────────────────────

    async def get_room_name(self) -> str:
        return f"event_{self.event_id}_checkin"

    async def get_presence_room_name(self) -> str:
        return f"event_{self.event_id}_checkin_presence"

    async def get_presence_key(self) -> str:
        return f"event_checkin_presence:{self.event_id}"

    async def check_permission(self) -> bool:
        if not self.event:
            return False
        return await self.check_event_permission()

    async def get_user_context(self) -> Dict[str, Any]:
        return {
            'id': self.user.id,
            'email': self.user.email,
            'name': getattr(self.user, 'get_full_name', lambda: self.user.email)(),
            'event_id': str(self.event_id),
        }

    async def handle_authenticated_message(self, message_type: str, data: dict):
        if message_type == 'checkin.filter.set':
            await self.handle_filter_set(data)
        elif message_type == 'checkin.history':
            await self.handle_history_request(data)
        else:
            logger.debug(
                f"[checkin] Unhandled message type: {message_type} "
                f"from user {self.user.email}"
            )

    # ── Message handlers ──────────────────────────────────────────────────

    async def handle_filter_set(self, data: dict):
        """Validate and store per-connection priority filters."""
        filter_data = data.get('filters', {})
        serializer = CheckInFilterSerializer(data=filter_data)

        if not serializer.is_valid():
            await self.send_error(
                f"Invalid filter data: {serializer.errors}"
            )
            return

        self.priority_filters = serializer.validated_data
        await self.send(text_data=json.dumps({
            'type': 'checkin.filter.accepted',
            'filters': self.priority_filters,
            'timestamp': timezone.now().isoformat(),
        }))
        logger.debug(
            f"[checkin] Filters updated for user {self.user.email}: "
            f"{self.priority_filters}"
        )

    async def handle_history_request(self, data: dict):
        """Return paginated check-in history to this client only."""
        request_data = {
            'cursor': data.get('cursor', 0),
            'page_size': data.get('page_size', 20),
        }
        serializer = CheckInHistoryRequestSerializer(data=request_data)

        if not serializer.is_valid():
            await self.send_error(
                f"Invalid history request: {serializer.errors}"
            )
            return

        validated = serializer.validated_data
        records = await self.fetch_history(
            cursor=validated['cursor'],
            page_size=validated['page_size'],
        )

        await self.send(text_data=json.dumps({
            'type': 'checkin.history.response',
            'records': records,
            'cursor': validated['cursor'],
            'page_size': validated['page_size'],
            'timestamp': timezone.now().isoformat(),
        }))

    # ── Channel-layer event handler ────────────────────────────────────────

    async def checkin_event(self, event: Dict[str, Any]):
        """
        Handle checkin.occurred messages from the channel layer.

        Injected by the HTTP view after creating an AttendeeCheckIn record.
        Enriches the payload with matches_priority_filter before forwarding.
        """
        try:
            payload = dict(event.get('data', {}))
            payload['matches_priority_filter'] = self._evaluate_priority_filter(payload)

            await self.send(text_data=json.dumps(payload))
        except Exception as e:
            logger.error(
                f"[checkin] Error broadcasting checkin event: {str(e)}",
                exc_info=True,
            )

    async def checkin_bulk_event(self, event: Dict[str, Any]):
        """
        Handle checkin_bulk_event messages from the channel layer.

        Pushed by CheckInViewSet.bulk_status_update after a mass check-in/out.
        Notifies clients that a bulk operation completed so they can refresh.
        """
        from django.utils import timezone

        payload = event.get('data', {})
        await self.send(text_data=json.dumps({
            'type': 'bulk.checkin.completed',
            'action': payload.get('action'),
            'count': payload.get('count'),
            'timestamp': timezone.now().isoformat(),
        }))

    # ── Helpers ───────────────────────────────────────────────────────────

    def _evaluate_priority_filter(self, payload: dict) -> bool:
        """
        Return True if the broadcast payload matches all active priority filters.

        An empty filter dict means everything matches.
        """
        filters = self.priority_filters
        if not filters:
            return True

        # has_outstanding_payments filter
        if 'has_outstanding_payments' in filters and filters['has_outstanding_payments'] is not None:
            if payload.get('has_outstanding_payments') != filters['has_outstanding_payments']:
                return False

        # attendee_status filter
        if filters.get('attendee_status'):
            if payload.get('attendee_status') != filters['attendee_status']:
                return False

        # ticket_type filter (matches ticket_type_code in payload)
        if filters.get('ticket_type'):
            if payload.get('ticket_type_code') != filters['ticket_type']:
                return False

        # area_from filter
        if filters.get('area_from'):
            if payload.get('area_from') != filters['area_from']:
                return False

        return True

    @database_sync_to_async
    def get_event(self):
        """Resolve event from identifier (UUID or slug)."""

        try:
            # uuid_module.UUID(str(self.event_identifier))
            return Event.objects.filter(url_safe_title=self.event_identifier).first()
        except ValueError:
            return Event.objects.filter(
                display_code__iexact=self.event_identifier
            ).first()

    @database_sync_to_async
    def check_event_permission(self) -> bool:
        """Staff / creator / superuser check (mirrors EventQuestionConsumer)."""
        if not self.user or not self.user.is_authenticated:
            return False
        if self.user.is_superuser or self.user.is_staff:
            return True
        if self.event.created_by == self.user:
            return True
        return self.event.is_staff(self.user)

    @database_sync_to_async
    def fetch_history(self, cursor: int, page_size: int) -> list:
        """Fetch paginated check-in records for this event."""
        from apps.attendee.models import AttendeeCheckIn

        records = AttendeeCheckIn.objects.select_related(
            'attendee', 'attendee__area_from',
            'ticket', 'ticket__ticket_type',
            'venue', 'venue_room',
            'performed_by',
        ).filter(
            attendee__event=self.event
        ).order_by('-performed_at')[cursor: cursor + page_size]

        return CheckInBroadcastSerializer(records, many=True).data
