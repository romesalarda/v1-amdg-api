"""
URL Configuration for users app.

Includes authentication endpoints with HTTP-only cookie support.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api.viewsets import (
    UserViewSet,
    CustomTokenObtainPairView,
    CustomTokenRefreshView,
    logout,
)
from .api.views import health_check

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    # Health check (no auth required)
    path('health/', health_check, name='health_check'),
    
    # Authentication endpoints
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', logout, name='logout'),
    path('auth/register/', UserViewSet.as_view({'post': 'register'}), name='register'),
    
    # User management endpoints
    path('', include(router.urls)),
]

