"""WebSocket presence for users navigating an event dashboard."""
import json
import logging
import re
from typing import Any, Dict
from uuid import UUID

import redis.asyncio as redis
from channels.db import database_sync_to_async
from django.conf import settings
from django.utils import timezone

from apps.events.models import Event
from .base import BaseRealtimeConsumer

logger = logging.getLogger(__name__)

PRESENCE_TTL_SECONDS = 120
SECTION_PATTERN = re.compile(r"[a-z0-9-]{1,64}\Z")


def _get_presence_redis():
    redis_config = settings.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"][0]
    if isinstance(redis_config, tuple):
        return redis.Redis(
            host=redis_config[0],
            port=redis_config[1],
            decode_responses=True,
        )
    return redis.from_url(redis_config, decode_responses=True)


class DashboardPresenceConsumer(BaseRealtimeConsumer):
    """Track authenticated dashboard connections by their active sidebar section.

    Clients authenticate with ``authenticate`` and send
    ``{"type": "page.change", "section": "<sidebar-section>"}``. The server
    broadcasts ``presence.state`` messages with the active users per section.
    """

    resource_name = "dashboard-presence"

    async def connect(self):
        self.event_identifier = self.scope["url_route"]["kwargs"]["event_identifier"]
        self.event = await self.get_event()
        if not self.event:
            logger.warning(
                "[dashboard-presence] Event not found: %s",
                self.event_identifier,
            )
            await self.close()
            return

        self.event_id = self.event.event_id
        self.current_section = None
        await super().connect()

    async def get_room_name(self) -> str:
        return f"event_{self.event_id}_dashboard_presence"

    async def get_presence_room_name(self) -> str:
        return await self.get_room_name()

    async def get_presence_key(self) -> str:
        return f"event_dashboard_presence:{self.event_id}"

    async def check_permission(self) -> bool:
        return bool(self.event and await self.check_event_permission())

    async def get_user_context(self) -> Dict[str, Any]:
        name = self.user.get_full_name() or self.user.email
        return {
            "id": self.user.id,
            "email": self.user.email,
            "name": name,
            "profile_picture_url": await self.get_user_profile_picture_url(),
            "event_id": str(self.event_id),
        }

    async def handle_authentication(self, token: str | None):
        if self.authenticated:
            await self.send_error("Already authenticated")
            return
        if not token:
            await self.send_error(
                "No token provided",
                code=4003,
                close_connection=True,
            )
            return

        user = await self.authenticate_token(token)
        if not user:
            await self.send_error(
                "Invalid token",
                code=4003,
                close_connection=True,
            )
            return

        self.user = user
        if not await self.check_permission():
            await self.send_error(
                "Access denied",
                code=4003,
                close_connection=True,
            )
            return

        self.presence_group_name = await self.get_presence_room_name()
        self.presence_key = await self.get_presence_key()
        await self.channel_layer.group_add(
            self.presence_group_name,
            self.channel_name,
        )
        self.authenticated = True

        await self.send(text_data=json.dumps({
            "type": "authenticated",
            "message": "Authentication successful",
            "user": await self.get_user_context(),
            "timestamp": timezone.now().isoformat(),
        }))
        await self.send_presence_state()

    async def handle_authenticated_message(
        self,
        message_type: str,
        data: dict,
    ):
        if message_type != "page.change":
            logger.debug(
                "[dashboard-presence] Ignoring unsupported message type %r",
                message_type,
            )
            return

        section = data.get("section")
        if not isinstance(section, str) or not SECTION_PATTERN.fullmatch(section):
            await self.send_error(
                "Section must be a lowercase sidebar section identifier"
            )
            return

        self.current_section = section
        await self.store_connection()
        await self.broadcast_presence_state()

    async def send_pong(self):
        if self.current_section:
            await self.refresh_connection()
        await super().send_pong()

    async def disconnect(self, close_code: int):
        section = getattr(self, "current_section", None)
        if self.authenticated and self.presence_key:
            await self.remove_connection()
            if section:
                await self.broadcast_presence_state()

        if self.presence_group_name:
            await self.channel_layer.group_discard(
                self.presence_group_name,
                self.channel_name,
            )

        logger.info(
            "[dashboard-presence] WebSocket disconnected: user=%s code=%s",
            getattr(self.user, "email", "unknown"),
            close_code,
        )

    async def dashboard_presence_state(self, event: Dict[str, Any]):
        await self.send(text_data=json.dumps(event["data"]))

    async def store_connection(self):
        client = _get_presence_redis()
        try:
            timestamp = timezone.now().timestamp()
            connection_data = {
                "section": self.current_section,
                "user": await self.get_user_context(),
            }
            await client.zadd(self.presence_key, {self.channel_name: timestamp})
            await client.hset(
                f"{self.presence_key}:connections",
                self.channel_name,
                json.dumps(connection_data),
            )
            await client.expire(self.presence_key, PRESENCE_TTL_SECONDS)
            await client.expire(
                f"{self.presence_key}:connections",
                PRESENCE_TTL_SECONDS,
            )
        finally:
            await client.close()

    async def refresh_connection(self):
        client = _get_presence_redis()
        stale_connections = []
        try:
            cutoff = timezone.now().timestamp() - PRESENCE_TTL_SECONDS
            stale_connections = await client.zrangebyscore(
                self.presence_key,
                "-inf",
                cutoff,
            )
            if stale_connections:
                await client.zrem(self.presence_key, *stale_connections)
                await client.hdel(
                    f"{self.presence_key}:connections",
                    *stale_connections,
                )

            was_present = await client.zscore(
                self.presence_key,
                self.channel_name,
            )
            await client.zadd(
                self.presence_key,
                {self.channel_name: timezone.now().timestamp()},
            )
            await client.hset(
                f"{self.presence_key}:connections",
                self.channel_name,
                json.dumps({
                    "section": self.current_section,
                    "user": await self.get_user_context(),
                }),
            )
            await client.expire(self.presence_key, PRESENCE_TTL_SECONDS)
            await client.expire(
                f"{self.presence_key}:connections",
                PRESENCE_TTL_SECONDS,
            )
        finally:
            await client.close()
        if stale_connections or was_present is None:
            await self.broadcast_presence_state()

    async def remove_connection(self):
        client = _get_presence_redis()
        try:
            connections_key = f"{self.presence_key}:connections"
            await client.zrem(self.presence_key, self.channel_name)
            await client.hdel(connections_key, self.channel_name)
            if await client.zcard(self.presence_key) == 0:
                await client.delete(self.presence_key, connections_key)
        finally:
            await client.close()

    async def get_presence_state(self) -> Dict[str, Any]:
        client = _get_presence_redis()
        try:
            cutoff = timezone.now().timestamp() - PRESENCE_TTL_SECONDS
            stale_connections = await client.zrangebyscore(
                self.presence_key,
                "-inf",
                cutoff,
            )
            if stale_connections:
                await client.zrem(self.presence_key, *stale_connections)
                await client.hdel(
                    f"{self.presence_key}:connections",
                    *stale_connections,
                )

            active_connections = await client.zrange(
                self.presence_key,
                0,
                -1,
            )
            records = await client.hgetall(
                f"{self.presence_key}:connections"
            )
        finally:
            await client.close()

        sections: Dict[str, Dict[Any, Dict[str, Any]]] = {}
        for connection_name in active_connections:
            record = records.get(connection_name)
            if not record:
                continue
            try:
                connection_data = json.loads(record)
                user = connection_data["user"]
                section = connection_data["section"]
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning(
                    "[dashboard-presence] Ignoring malformed connection record"
                )
                continue
            sections.setdefault(section, {})[user["id"]] = user

        return {
            "type": "presence.state",
            "sections": {
                section: list(users.values())
                for section, users in sections.items()
            },
            "timestamp": timezone.now().isoformat(),
        }

    async def send_presence_state(self):
        await self.send(text_data=json.dumps(await self.get_presence_state()))

    async def broadcast_presence_state(self):
        await self.channel_layer.group_send(
            self.presence_group_name,
            {
                "type": "dashboard_presence_state",
                "data": await self.get_presence_state(),
            },
        )

    @database_sync_to_async
    def get_event(self):
        try:
            event_uuid = UUID(self.event_identifier)
            return Event.objects.get(event_id=event_uuid)
        except (ValueError, Event.DoesNotExist):
            try:
                return Event.objects.get(url_safe_title=self.event_identifier)
            except Event.DoesNotExist:
                return None

    @database_sync_to_async
    def get_user_profile_picture_url(self) -> str | None:
        return self.user.profile_picture_url()

    @database_sync_to_async
    def check_event_permission(self) -> bool:
        if not self.user or not self.user.is_authenticated:
            return False
        if self.user.is_superuser or self.user.is_staff:
            return True
        if self.event.created_by == self.user:
            return True
        return self.event.is_staff(self.user)
