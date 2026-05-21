"""
WebSocket URL routing for events application.
"""
from django.urls import re_path
from .consumers import EventQuestionConsumer, CheckInConsumer

# This regex is designed to match either a standard UUID or a URL-friendly slug.
# - UUIDs are matched by their typical 32-hex-character-with-hyphens format.
# - Slugs are matched by a sequence of word characters (alphanumeric + underscore) and hyphens.
# This allows for flexible event identification in WebSocket URLs.
websocket_urlpatterns = [
    re_path(
        r'^ws/events/(?P<event_identifier>([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[\w-]+))/questions/$',
        EventQuestionConsumer.as_asgi()
    ),
    re_path(
        r'^ws/events/(?P<event_identifier>([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[\w-]+))/checkin/$',
        CheckInConsumer.as_asgi()
    ),
]
