"""Tests for event dashboard page-presence WebSocket behavior."""
from datetime import timedelta
from unittest.mock import patch

from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.events.consumers.dashboard_presence import DashboardPresenceConsumer
from apps.events.models import Event, EventStatusChoices, EventType
from apps.organisations.models import Organisation

User = get_user_model()


class InMemoryPresenceRedis:
    """Small async Redis substitute for exercising consumer presence flows."""

    def __init__(self):
        self.sorted_sets = {}
        self.hashes = {}

    async def zadd(self, key, values):
        self.sorted_sets.setdefault(key, {}).update(values)

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def expire(self, key, seconds):
        return key in self.sorted_sets or key in self.hashes

    async def zremrangebyscore(self, key, minimum, maximum):
        entries = self.sorted_sets.setdefault(key, {})
        stale = [
            member
            for member, score in entries.items()
            if score <= float(maximum)
        ]
        for member in stale:
            entries.pop(member)
        return len(stale)

    async def zrangebyscore(self, key, minimum, maximum):
        entries = self.sorted_sets.setdefault(key, {})
        return [
            member
            for member, score in entries.items()
            if score <= float(maximum)
        ]

    async def zscore(self, key, member):
        return self.sorted_sets.get(key, {}).get(member)

    async def zrange(self, key, start, stop):
        entries = self.sorted_sets.get(key, {})
        ordered = sorted(entries, key=entries.get)
        return ordered[start:] if stop == -1 else ordered[start:stop + 1]

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def zrem(self, key, *members):
        entries = self.sorted_sets.setdefault(key, {})
        for member in members:
            entries.pop(member, None)

    async def hdel(self, key, *fields):
        entries = self.hashes.setdefault(key, {})
        for field in fields:
            entries.pop(field, None)

    async def zcard(self, key):
        return len(self.sorted_sets.get(key, {}))

    async def delete(self, *keys):
        for key in keys:
            self.sorted_sets.pop(key, None)
            self.hashes.pop(key, None)

    async def close(self):
        pass


class DashboardPresenceConsumerTest(TransactionTestCase):
    def setUp(self):
        self.redis = InMemoryPresenceRedis()
        self.redis_patch = patch(
            "apps.events.consumers.dashboard_presence._get_presence_redis",
            return_value=self.redis,
        )
        self.redis_patch.start()
        self.addCleanup(self.redis_patch.stop)

        self.owner = User.objects.create_user(
            username="dashboard_owner",
            email="dashboard_owner@test.com",
            password="pass",
            is_staff=True,
        )
        self.other_user = User.objects.create_user(
            username="dashboard_other",
            email="dashboard_other@test.com",
            password="pass",
            is_staff=True,
        )
        self.attendee = User.objects.create_user(
            username="dashboard_attendee",
            email="dashboard_attendee@test.com",
            password="pass",
        )
        organisation = Organisation.objects.create(
            title="Dashboard Presence Org",
            created_by=self.owner,
        )
        event_type = EventType.objects.create(
            title="Dashboard Presence Event",
            code="DASH",
            created_by=self.owner,
        )
        self.event = Event.objects.create(
            title="Dashboard Presence Event",
            display_code="DASH",
            created_by=self.owner,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=5),
            end_datetime=timezone.now() + timedelta(days=7),
            organisation=organisation,
            status=EventStatusChoices.PUBLISHED,
        )

    def _communicator(self):
        communicator = WebsocketCommunicator(
            DashboardPresenceConsumer.as_asgi(),
            f"/ws/events/{self.event.url_safe_title}/dashboard/presence/",
        )
        communicator.scope["url_route"] = {
            "kwargs": {
                "event_identifier": str(self.event.url_safe_title),
            },
        }
        return communicator

    async def _connect_and_authenticate(self, user):
        communicator = self._communicator()
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        token = str(RefreshToken.for_user(user).access_token)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })
        authenticated = await communicator.receive_json_from(timeout=5)
        initial_state = await communicator.receive_json_from(timeout=5)
        self.assertEqual(authenticated["type"], "authenticated")
        self.assertEqual(initial_state["type"], "presence.state")
        return communicator

    async def test_authenticated_users_receive_section_presence_updates(self):
        owner_socket = await self._connect_and_authenticate(self.owner)
        other_socket = await self._connect_and_authenticate(self.other_user)

        await owner_socket.send_json_to({
            "type": "page.change",
            "section": "participants",
        })
        owner_state = await owner_socket.receive_json_from(timeout=5)
        other_state = await other_socket.receive_json_from(timeout=5)
        self.assertEqual(owner_state, other_state)
        self.assertEqual(
            [user["id"] for user in owner_state["sections"]["participants"]],
            [self.owner.id],
        )
        self.assertIsNone(
            owner_state["sections"]["participants"][0]["profile_picture_url"]
        )

        await other_socket.send_json_to({
            "type": "page.change",
            "section": "participants",
        })
        owner_state = await owner_socket.receive_json_from(timeout=5)
        other_state = await other_socket.receive_json_from(timeout=5)
        self.assertEqual(owner_state, other_state)
        self.assertEqual(
            {user["id"] for user in owner_state["sections"]["participants"]},
            {self.owner.id, self.other_user.id},
        )

        await other_socket.send_json_to({
            "type": "page.change",
            "section": "info",
        })
        owner_state = await owner_socket.receive_json_from(timeout=5)
        other_state = await other_socket.receive_json_from(timeout=5)
        self.assertEqual(owner_state, other_state)
        self.assertEqual(
            [user["id"] for user in owner_state["sections"]["participants"]],
            [self.owner.id],
        )
        self.assertEqual(
            [user["id"] for user in owner_state["sections"]["info"]],
            [self.other_user.id],
        )

        await owner_socket.disconnect()
        remaining_state = await other_socket.receive_json_from(timeout=5)
        self.assertEqual(
            [user["id"] for user in remaining_state["sections"]["info"]],
            [self.other_user.id],
        )
        await other_socket.disconnect()

    async def test_invalid_section_is_rejected(self):
        communicator = await self._connect_and_authenticate(self.owner)

        await communicator.send_json_to({
            "type": "page.change",
            "section": "participants/dashboard",
        })
        response = await communicator.receive_json_from(timeout=5)

        self.assertEqual(response["type"], "error")
        self.assertEqual(self.redis.hashes, {})
        await communicator.disconnect()

    async def test_non_staff_user_is_denied(self):
        communicator = self._communicator()
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        token = str(RefreshToken.for_user(self.attendee).access_token)

        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })
        response = await communicator.receive_json_from(timeout=5)

        self.assertEqual(response["type"], "error")
        self.assertEqual(response["message"], "Access denied")
        await communicator.disconnect()
