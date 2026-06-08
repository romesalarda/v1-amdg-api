"""
Unit tests for the EventFormConsumer WebSocket consumer.

Covers:
- Connection and authentication flow
- Permission denial for non-staff users
- Dual-group subscription (form_event + form_response_event broadcasts)
- Ping/pong keepalive (inherited from base)
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from channels.testing import WebsocketCommunicator

from apps.events.consumers.forms import EventFormConsumer
from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation

User = get_user_model()


def _get_token(user):
    """Generate a JWT access token for the given user."""
    from rest_framework_simplejwt.tokens import RefreshToken
    return str(RefreshToken.for_user(user).access_token)


class EventFormConsumerTestBase(TransactionTestCase):
    """
    Use TransactionTestCase so that the in-memory channel layer and async
    database operations work correctly across test methods.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username='ws_owner', email='ws_owner@test.com', password='pass', is_staff=True
        )
        self.intruder = User.objects.create_user(
            username='ws_intruder', email='ws_intruder@test.com', password='pass', is_staff=False
        )
        self.organisation = Organisation.objects.create(title='WS Org', created_by=self.owner)
        self.event_type = EventType.objects.create(title='WS Conf', code='WSCO', created_by=self.owner)
        self.event = Event.objects.create(
            title='WS Test Event',
            display_code='WSEVT',
            created_by=self.owner,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=5),
            end_datetime=timezone.now() + timedelta(days=7),
            organisation=self.organisation,
            status=EventStatusChoices.PUBLISHED,
        )

    def _communicator(self):
        """Return a configured WebsocketCommunicator for this event."""
        comm = WebsocketCommunicator(
            EventFormConsumer.as_asgi(),
            f'/ws/events/{self.event.url_safe_title}/forms/',
        )
        comm.scope['url_route'] = {'kwargs': {'event_identifier': str(self.event.url_safe_title)}}
        return comm


class EventFormConsumerAuthTest(EventFormConsumerTestBase):
    async def test_staff_user_authenticates_successfully(self):
        token = _get_token(self.owner)
        comm = self._communicator()
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        await comm.send_json_to({'type': 'authenticate', 'token': token})
        response = await comm.receive_json_from(timeout=5)

        self.assertEqual(response['type'], 'authenticated')
        self.assertEqual(response['user']['email'], self.owner.email)

        await comm.disconnect()

    async def test_non_staff_user_is_denied(self):
        token = _get_token(self.intruder)
        comm = self._communicator()
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        await comm.send_json_to({'type': 'authenticate', 'token': token})
        response = await comm.receive_json_from(timeout=5)

        self.assertEqual(response['type'], 'error')
        self.assertEqual(response['message'], 'Access denied')

        await comm.disconnect()

    async def test_missing_token_returns_error(self):
        comm = self._communicator()
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        await comm.send_json_to({'type': 'authenticate'})
        response = await comm.receive_json_from(timeout=5)

        self.assertEqual(response['type'], 'error')

        await comm.disconnect()

    async def test_invalid_token_returns_error(self):
        comm = self._communicator()
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        await comm.send_json_to({'type': 'authenticate', 'token': 'not.a.valid.jwt'})
        response = await comm.receive_json_from(timeout=5)

        self.assertEqual(response['type'], 'error')

        await comm.disconnect()


class EventFormConsumerBroadcastTest(EventFormConsumerTestBase):
    async def _connect_and_auth(self):
        """Connect, authenticate, and drain presence.list. Returns communicator."""
        token = _get_token(self.owner)
        comm = self._communicator()
        await comm.connect()
        await comm.send_json_to({'type': 'authenticate', 'token': token})
        await comm.receive_json_from(timeout=5)  # authenticated
        await comm.receive_json_from(timeout=5)  # presence.list
        return comm

    async def test_receives_form_event_broadcast(self):
        from channels.layers import get_channel_layer
        comm = await self._connect_and_auth()

        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            f"event_{self.event.event_id}_forms",
            {
                'type': 'form_event',
                'data': {
                    'type': 'form.created',
                    'payload': {'id': 'abc', 'title': 'New Form'},
                },
            },
        )

        msg = await comm.receive_json_from(timeout=5)
        self.assertEqual(msg['type'], 'form.created')
        self.assertEqual(msg['payload']['title'], 'New Form')

        await comm.disconnect()

    async def test_receives_form_response_event_broadcast(self):
        from channels.layers import get_channel_layer
        comm = await self._connect_and_auth()

        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            f"event_{self.event.event_id}_form_responses",
            {
                'type': 'form_response_event',
                'data': {
                    'type': 'response.created',
                    'payload': {'id': 'resp-001'},
                },
            },
        )

        msg = await comm.receive_json_from(timeout=5)
        self.assertEqual(msg['type'], 'response.created')

        await comm.disconnect()

    async def test_ping_returns_pong(self):
        comm = await self._connect_and_auth()

        await comm.send_json_to({'type': 'ping'})
        pong = await comm.receive_json_from(timeout=5)

        self.assertEqual(pong['type'], 'pong')

        await comm.disconnect()

    async def test_unknown_message_type_does_not_crash(self):
        """Unknown client messages are silently ignored (read-only consumer)."""
        comm = await self._connect_and_auth()

        await comm.send_json_to({'type': 'form.create', 'data': {}})
        # Should not receive any response; nothing should explode
        no_msg = await comm.receive_nothing(timeout=1)
        self.assertTrue(no_msg)

        await comm.disconnect()

