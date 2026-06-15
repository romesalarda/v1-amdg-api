"""
WebSocket token service for event real-time connections.

Centralises all JWT generation and validation logic for WebSocket authentication
so the viewset only concerns itself with the HTTP request/response cycle.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone


class WebSocketTokenService:
    """
    Generates short-lived WebSocket-specific JWT tokens.

    These tokens are intentionally separate from the HTTP access tokens issued
    by SimpleJWT so that a WebSocket token cannot be replayed against REST
    endpoints.

    Token payload schema
    --------------------
    ``user_id``   – integer PK of the authenticated user
    ``event_id``  – string UUID of the event being accessed
    ``type``      – always ``"websocket"`` (prevents cross-use with HTTP JWTs)
    ``exp``       – standard JWT expiry claim
    ``iat``       – issued-at timestamp
    ``jti``       – unique token ID (UUID4) enabling future revocation
    """

    TOKEN_LIFETIME_SECONDS: int = 300  # 5 minutes
    TOKEN_TYPE: str = "websocket"
    ALGORITHM: str = "HS256"

    @classmethod
    def generate(cls, user, event) -> dict:
        """
        Generate a WebSocket token for *user* accessing *event*.

        Returns a dict with:
          ``token``       – encoded JWT string
          ``expires_in``  – seconds until expiry
          ``ws_url``      – WebSocket URL template (caller must fill in the host)
        """
        now = timezone.now()
        expiration = now + timedelta(seconds=cls.TOKEN_LIFETIME_SECONDS)

        payload = {
            "user_id": user.id,
            "event_id": str(event.event_id),
            "type": cls.TOKEN_TYPE,
            "exp": expiration,
            "iat": now,
            "jti": str(uuid.uuid4()),
        }

        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=cls.ALGORITHM)
        return {
            "token": token,
            "expires_in": cls.TOKEN_LIFETIME_SECONDS,
            # Caller substitutes the correct host and protocol at runtime.
            "_ws_path_template": "/ws/events/{event_id}/questions/?token={token}",
        }

    @classmethod
    def build_ws_url(cls, request, event, token: str) -> str:
        """Return the full WebSocket URL for *event* with *token* appended."""
        protocol = "wss" if request.is_secure() else "ws"
        host = request.get_host()
        return (
            f"{protocol}://{host}/ws/events/{event.event_id}/questions/"
            f"?token={token}"
        )
