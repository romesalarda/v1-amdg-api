"""
WebSocket URL routing for events application.
"""
from django.urls import path
from .consumers import EventQuestionConsumer

websocket_urlpatterns = [
    path('ws/events/<uuid:event_id>/questions/', EventQuestionConsumer.as_asgi()),
]
