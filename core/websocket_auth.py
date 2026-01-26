"""
WebSocket JWT Authentication Middleware for Django Channels.

This module provides secure JWT-based authentication for WebSocket connections.
Tokens are validated using djangorestframework-simplejwt and must be obtained
from the HTTP token exchange endpoint.
"""
import logging
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from jwt import decode as jwt_decode
from django.conf import settings

User = get_user_model()
logger = logging.getLogger(__name__)


class JWTWebSocketMiddleware(BaseMiddleware):
    """
    Middleware for authenticating WebSocket connections using JWT tokens.
    
    Extracts and validates JWT tokens from query parameters or headers.
    Sets scope['user'] and scope['event_id'] from validated token claims.
    
    Token must include:
    - type: "websocket" (to distinguish from HTTP tokens)
    - user_id: The authenticated user's ID
    - event_id: The event ID this WebSocket connection is for
    - exp: Expiration timestamp (5 minutes from issuance)
    
    Security Features:
    - Short-lived tokens (5 minutes)
    - Type-based token segregation
    - Comprehensive logging for security monitoring
    - Graceful error handling with appropriate close codes
    """
    
    async def __call__(self, scope, receive, send):
        """
        Process the WebSocket connection and authenticate the user.
        
        Args:
            scope: The connection scope dictionary
            receive: The receive channel
            send: The send channel
            
        Returns:
            The inner application call with authenticated scope
        """
        # Extract token from query parameters (primary method)
        query_string = scope.get('query_string', b'').decode('utf-8')
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        
        # Fallback: Try to extract from headers (if provided)
        if not token:
            headers = dict(scope.get('headers', []))
            auth_header = headers.get(b'authorization', b'').decode('utf-8')
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
        
        if not token:
            # No token in URL - allow connection, consumer will handle authentication via message
            logger.info(
                f"WebSocket connection without URL token from {scope.get('client', ['unknown'])[0]} - will authenticate via message"
            )
            scope['user'] = AnonymousUser()
            scope['event_id'] = scope.get('url_route', {}).get('kwargs', {}).get('event_id')
            return await super().__call__(scope, receive, send)
        
        try:
            # Validate token using simplejwt
            UntypedToken(token)
            
            # Decode token to extract claims
            decoded_data = jwt_decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"]
            )
            
            # Validate token type
            token_type = decoded_data.get('type') or decoded_data.get('token_type')
            if token_type != 'websocket':
                logger.warning(
                    f"Invalid token type '{token_type}' for WebSocket connection"
                )
                await self.close_connection(send, code=4003, reason="Invalid token type")
                return
            
            # Extract user_id and event_id
            user_id = decoded_data.get('user_id')
            event_id = decoded_data.get('event_id')
            
            if not user_id or not event_id:
                logger.warning(
                    f"Token missing required claims: user_id={user_id}, event_id={event_id}"
                )
                await self.close_connection(send, code=4003, reason="Invalid token claims")
                return
            
            # Fetch user from database
            user = await self.get_user(user_id)
            if not user or not user.is_active:
                logger.warning(
                    f"WebSocket authentication failed: user {user_id} not found or inactive"
                )
                await self.close_connection(send, code=4003, reason="User not found")
                return
            
            # Set authenticated user and event_id in scope
            scope['user'] = user
            scope['event_id'] = event_id
            
            logger.info(
                f"WebSocket authenticated: user={user.email}, event_id={event_id}"
            )
            
        except TokenError as e:
            # Token is invalid or expired
            logger.warning(
                f"WebSocket token validation failed: {str(e)}"
            )
            if 'expired' in str(e).lower():
                await self.close_connection(send, code=4001, reason="Token expired")
            else:
                await self.close_connection(send, code=4003, reason="Invalid token")
            return
            
        except Exception as e:
            # Unexpected error
            logger.error(
                f"WebSocket authentication error: {str(e)}",
                exc_info=True
            )
            await self.close_connection(send, code=4003, reason="Authentication error")
            return
        
        # Continue to the application with authenticated scope
        return await super().__call__(scope, receive, send)
    
    @database_sync_to_async
    def get_user(self, user_id):
        """
        Fetch user from database asynchronously.
        
        Args:
            user_id: The user's ID
            
        Returns:
            User object or None if not found
        """
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
    
    async def close_connection(self, send, code=4003, reason="Authentication failed"):
        """
        Close the WebSocket connection with an appropriate error code.
        
        Args:
            send: The send channel
            code: WebSocket close code (4001=expired, 4003=forbidden)
            reason: Human-readable reason for closure
        """
        await send({
            'type': 'websocket.close',
            'code': code,
            'reason': reason,
        })
