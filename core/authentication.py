"""
Custom authentication classes for cookie-based JWT authentication.

This module provides a custom JWT authentication class that reads tokens
from HTTP-only cookies instead of the Authorization header.
"""
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed
from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class JWTCookieAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that reads the access token from HTTP-only cookies.
    
    This extends the default JWTAuthentication to support cookie-based authentication
    for enhanced security with HTTP-only cookies that cannot be accessed by JavaScript.
    
    The token is read from the 'access' cookie as configured in settings.SIMPLE_JWT['AUTH_COOKIE'].
    Falls back to header-based authentication if no cookie is present.
    """
    
    def authenticate(self, request):
        """
        Authenticate the request using JWT token from cookies or headers.
        
        First attempts to read the access token from the HTTP-only cookie.
        If not found, falls back to the default header-based authentication.
        
        Args:
            request: The HTTP request object
            
        Returns:
            Tuple of (user, validated_token) if authentication succeeds
            None if no authentication credentials are provided
            
        Raises:
            InvalidToken: If the token is invalid or expired
            AuthenticationFailed: If authentication fails
        """
        # Get cookie name from settings
        cookie_name = getattr(settings, 'SIMPLE_JWT', {}).get('AUTH_COOKIE', 'access')
        
        # Try to get token from cookie
        raw_token = request.COOKIES.get(cookie_name)
        
        if raw_token is None:
            # Fall back to header-based authentication
            return super().authenticate(request)
        
        # Validate the token
        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except InvalidToken as e:
            raise InvalidToken(f"Token from cookie is invalid: {e}")


class JWTCookieAuthenticationScheme(OpenApiAuthenticationExtension):
    """
    OpenAPI schema extension for JWTCookieAuthentication.
    
    This registers the JWTCookieAuthentication class with drf-spectacular
    to properly document the authentication mechanism in the OpenAPI schema.
    """
    target_class = 'core.authentication.JWTCookieAuthentication'
    name = 'jwtCookieAuth'
    
    def get_security_definition(self, auto_schema):
        """
        Define the security scheme for OpenAPI documentation.
        
        Documents both cookie-based and header-based JWT authentication methods.
        """
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': (
                'JWT authentication using HTTP-only cookies or Authorization header. '
                'The access token can be provided in two ways:\n\n'
                '1. **Cookie (Recommended)**: HTTP-only cookie named "access" (automatically handled by browser)\n'
                '2. **Header**: Authorization header with format: `Bearer <token>`\n\n'
                'Cookie-based authentication is more secure as it cannot be accessed by JavaScript.'
            )
        }
