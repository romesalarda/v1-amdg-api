"""
Production-grade URL Configuration for users app.

This module configures all API endpoints for user management, authentication,
and Google OAuth with proper routing, HATEOAS support, and comprehensive documentation.

Endpoints Structure:
    Authentication:
        - POST /api/auth/login/ - Login with email/password
        - POST /api/auth/refresh/ - Refresh access token
        - POST /api/auth/logout/ - Logout and clear cookies
        - POST /api/auth/google/authorize/ - Get Google OAuth URL
        - POST /api/auth/google/callback/ - Handle Google OAuth callback
    
    Users:
        - GET /api/users/ - List users (paginated, filtered)
        - POST /api/users/ - Register new user
        - GET /api/users/{id}/ - Get user details
        - PUT /api/users/{id}/ - Update user (full)
        - PATCH /api/users/{id}/ - Update user (partial)
        - DELETE /api/users/{id}/ - Delete user
        - GET /api/users/me/ - Get current user
        - PATCH /api/users/me/update/ - Update current user
        - POST /api/users/change-password/ - Change password
        - POST /api/users/verify-email/ - Verify email
        - GET /api/users/{id}/profile/ - Get user's profile
    
    Profiles:
        - GET /api/profiles/ - List profiles
        - GET /api/profiles/{id}/ - Get profile details
        - PUT /api/profiles/{id}/ - Update profile (full)
        - PATCH /api/profiles/{id}/ - Update profile (partial)
        - GET /api/profiles/me/ - Get current user's profile
    
    Health Check:
        - GET /api/health/ - Health check endpoint

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from .api.viewsets import (
    UserViewSet,
    ProfileViewSet,
    GoogleOAuthViewSet,
    CustomTokenObtainPairView,
    CustomTokenRefreshView,
    logout,
)
from .api.views import health_check

# Initialize DRF router for automatic URL routing
router = DefaultRouter()

# Register viewsets with the router
# This automatically generates URLs for:
# - list: GET /users/
# - create: POST /users/
# - retrieve: GET /users/{id}/
# - update: PUT /users/{id}/
# - partial_update: PATCH /users/{id}/
# - destroy: DELETE /users/{id}/
# Plus any @action decorated methods
router.register(r'users', UserViewSet, basename='user')
router.register(r'profiles', ProfileViewSet, basename='profile')
router.register(r'auth/google', GoogleOAuthViewSet, basename='google-oauth')

# App name for namespace (used in reverse URL lookups)
app_name = 'users'

urlpatterns = [
    # =============================================================================
    # HEALTH CHECK
    # =============================================================================
    path('health/', health_check, name='health-check'),
    
    # =============================================================================
    # AUTHENTICATION ENDPOINTS
    # =============================================================================
    # JWT Authentication with HTTP-only cookies
    path(
        'auth/login/',
        CustomTokenObtainPairView.as_view(),
        name='token-obtain-pair'
    ),
    path(
        'auth/refresh/',
        CustomTokenRefreshView.as_view(),
        name='token-refresh'
    ),
    path(
        'auth/logout/',
        logout,
        name='logout'
    ),
    
    # =============================================================================
    # API DOCUMENTATION ENDPOINTS (DRF Spectacular)
    # =============================================================================
    # OpenAPI schema
    path(
        'schema/',
        SpectacularAPIView.as_view(),
        name='schema'
    ),
    # Swagger UI documentation
    path(
        'docs/',
        SpectacularSwaggerView.as_view(url_name='users:schema'),
        name='swagger-ui'
    ),
    # ReDoc documentation
    path(
        'redoc/',
        SpectacularRedocView.as_view(url_name='users:schema'),
        name='redoc'
    ),
    
    # =============================================================================
    # ROUTER URLS (Users, Profiles, Google OAuth)
    # =============================================================================
    # Include all router-generated URLs
    # This includes:
    # - /users/ (UserViewSet endpoints)
    # - /profiles/ (ProfileViewSet endpoints)
    # - /auth/google/ (GoogleOAuthViewSet endpoints)
    path('', include(router.urls)),
]
