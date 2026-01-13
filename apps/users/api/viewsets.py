"""
Production-grade ViewSets for the users app.

This module provides comprehensive API endpoints for user management, authentication,
and profile operations with Google OAuth integration, HATEOAS support, and extensive
security features.

ViewSets:
    - UserViewSet: Full CRUD operations for users with custom actions
    - ProfileViewSet: Profile management endpoints
    - AuthViewSet: Authentication and OAuth endpoints

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action, api_view, permission_classes as permission_classes_decorator
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.db.models import Q, Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiExample
)
from drf_spectacular.types import OpenApiTypes
import requests
from typing import Any, Dict, Optional
import os

from .serializers import (
    UserSerializer,
    UserDetailSerializer,
    UserRegistrationSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    EmailVerificationSerializer,
    CustomTokenObtainPairSerializer,
    GoogleOAuthSerializer,
    GoogleOAuthCallbackSerializer,
    ProfileSerializer,
)
from .filtersets import ProfileFilterSet
from apps.users.models import Profile

User = get_user_model()


class UserPagination(PageNumberPagination):
    """Custom pagination with configurable page size."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object or admins to access it.
    
    Used to ensure users can only view/edit their own profile unless they're staff.
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if user owns the object or is staff."""
        # Staff can access any object
        if request.user and request.user.is_staff:
            return True
        
        # Check if obj is a User or has a user attribute (like Profile)
        if isinstance(obj, User):
            return obj == request.user
        elif hasattr(obj, 'user'):
            return obj.user == request.user
        
        return False


@extend_schema_view(
    list=extend_schema(
        summary="List all users",
        description="Retrieve a paginated list of all users. Requires authentication. "
                    "Staff users can see all users, regular users only see themselves.",
        parameters=[
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                description='Search users by email, username, first name, or last name'
            ),
            OpenApiParameter(
                name='is_active',
                type=OpenApiTypes.BOOL,
                description='Filter by active status'
            ),
            OpenApiParameter(
                name='oauth_provider',
                type=OpenApiTypes.STR,
                description='Filter by OAuth provider (google, github, etc.)'
            ),
            OpenApiParameter(
                name='ordering',
                type=OpenApiTypes.STR,
                description='Order results by field (prefix with - for descending)'
            ),
        ],
        responses={
            200: UserSerializer(many=True),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
        }
    ),
    retrieve=extend_schema(
        summary="Retrieve user details",
        description="Get detailed information about a specific user. "
                    "Regular users can only view their own profile, staff can view any user.",
        responses={
            200: UserDetailSerializer,
            401: OpenApiResponse(description="Unauthorized"),
            403: OpenApiResponse(description="Forbidden - Cannot view other users"),
            404: OpenApiResponse(description="User not found"),
        }
    ),
    create=extend_schema(
        summary="Register a new user",
        description="Create a new user account. This endpoint is public and does not require authentication. "
                    "Returns JWT tokens in HTTP-only cookies and user data in response body.",
        request=UserRegistrationSerializer,
        responses={
            201: UserDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
        examples=[
            OpenApiExample(
                'User Registration Example',
                value={
                    'email': 'newuser@example.com',
                    'password': 'SecurePass123!',
                    'password_confirm': 'SecurePass123!',
                    'first_name': 'John',
                    'last_name': 'Doe'
                }
            )
        ]
    ),
    update=extend_schema(
        summary="Update user (full)",
        description="Fully update a user's profile. Users can only update their own profile.",
        request=UserUpdateSerializer,
        responses={
            200: UserDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            403: OpenApiResponse(description="Forbidden - Cannot update other users"),
        }
    ),
    partial_update=extend_schema(
        summary="Update user (partial)",
        description="Partially update a user's profile. Users can only update their own profile.",
        request=UserUpdateSerializer,
        responses={
            200: UserDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            403: OpenApiResponse(description="Forbidden - Cannot update other users"),
        }
    ),
    destroy=extend_schema(
        summary="Delete user account",
        description="Delete a user account. Users can delete their own account, staff can delete any account.",
        responses={
            204: OpenApiResponse(description="User deleted successfully"),
            403: OpenApiResponse(description="Forbidden - Cannot delete other users"),
            404: OpenApiResponse(description="User not found"),
        }
    ),
)
class UserViewSet(viewsets.ModelViewSet):
    """User CRUD with HATEOAS, filtering, search, pagination, and custom actions (me, change-password, verify-email)."""
    queryset = User.objects.select_related('profile').prefetch_related('groups').all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = UserPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]
    search_fields = ['email', 'username', 'first_name', 'last_name']
    filterset_fields = ['is_active', 'oauth_provider', 'email_verified', 'is_staff']
    ordering_fields = ['created_at', 'updated_at', 'email', 'username', 'date_joined']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """
        Optimize queryset with select_related and filter based on permissions.
        
        Regular users only see themselves, staff see all users.
        
        Returns:
            Filtered and optimized queryset
        """
        queryset = super().get_queryset()
        
        # Non-staff users can only see themselves
        if not self.request.user.is_staff:
            queryset = queryset.filter(id=self.request.user.id)
        
        return queryset
    
    def get_serializer_class(self):
        """
        Return appropriate serializer class based on action.
        
        Returns:
            Serializer class for current action
        """
        if self.action == 'create':
            return UserRegistrationSerializer
        elif self.action in ['update', 'partial_update', 'update_profile']:
            return UserUpdateSerializer
        elif self.action in ['retrieve', 'me']:
            return UserDetailSerializer
        return UserSerializer
    
    def get_permissions(self):
        """
        Set permissions based on action.
        
        - create (registration): AllowAny
        - retrieve, update, destroy: IsOwnerOrAdmin
        - list: IsAuthenticated (filtered by get_queryset)
        
        Returns:
            List of permission instances
        """
        if self.action == 'create' or self.request.method == 'POST':
            return [permissions.AllowAny()]
        elif self.action in ['retrieve', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwnerOrAdmin()]
        return super().get_permissions()
    
    def perform_create(self, serializer):
        """
        Create user and associated profile.
        
        Args:
            serializer: Validated UserRegistrationSerializer
        """
        user = serializer.save()
        
        # Ensure profile exists (signal should handle this)
        if not hasattr(user, 'profile'):
            Profile.objects.create(user=user)
    
    def perform_update(self, serializer):
        """
        Update user with validation.
        
        Args:
            serializer: Validated UserUpdateSerializer
        """
        # Check permissions
        if not self.request.user.is_staff and serializer.instance != self.request.user:
            raise PermissionDenied("You can only update your own profile.")
        
        serializer.save()
    
    def perform_destroy(self, instance):
        """
        Soft delete user by deactivating instead of hard delete.
        
        Args:
            instance: User instance to delete
        """
        # Check permissions
        if not self.request.user.is_staff and instance != self.request.user:
            raise PermissionDenied("You can only delete your own account.")
        
        # Soft delete: deactivate instead of removing
        instance.is_active = False
        instance.save()
    
    @extend_schema(
        summary="Get current user profile",
        description="Retrieve the authenticated user's complete profile information including profile data.",
        responses={
            200: UserDetailSerializer,
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
        }
    )
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        """
        Get current authenticated user's profile.
        
        Returns:
            Response with user data including profile
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Update current user profile",
        description="Update the authenticated user's profile information.",
        request=UserUpdateSerializer,
        responses={
            200: UserDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
        }
    )
    @action(detail=False, methods=['patch'], permission_classes=[permissions.IsAuthenticated],
            url_path='me/update')
    def update_profile(self, request):
        """
        Update current authenticated user's profile.
        
        Returns:
            Response with updated user data
        """
        serializer = UserUpdateSerializer(
            request.user,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Return full user data
        return Response(
            UserDetailSerializer(
                request.user,
                context={'request': request}
            ).data
        )
    
    @extend_schema(
        summary="Change password",
        description="Change the authenticated user's password. Requires current password for verification.",
        request=ChangePasswordSerializer,
        responses={
            200: OpenApiResponse(description="Password changed successfully"),
            400: OpenApiResponse(description="Validation error or incorrect old password"),
        },
        examples=[
            OpenApiExample(
                'Change Password Example',
                value={
                    'old_password': 'CurrentPass123!',
                    'new_password': 'NewSecurePass456!',
                    'new_password_confirm': 'NewSecurePass456!'
                }
            )
        ]
    )
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated],
            url_path='change-password')
    def change_password(self, request):
        """
        Change authenticated user's password.
        
        Validates old password before setting new one.
        
        Returns:
            Response with success message
        """
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user

        self.check_permissions(request)
        
        # Verify old password
        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {'old_password': ['Wrong password.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Set new password
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        return Response(
            {'detail': 'Password updated successfully.'},
            status=status.HTTP_200_OK
        )
    
    @extend_schema(
        summary="Verify email address",
        description="Verify user's email address using verification token sent via email.",
        request=EmailVerificationSerializer,
        responses={
            200: OpenApiResponse(description="Email verified successfully"),
            400: OpenApiResponse(description="Invalid token or email"),
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny],
            url_path='verify-email')
    def verify_email(self, request):
        """
        Verify user's email address with token.
        
        TODO: Implement token generation and validation logic.
        
        Returns:
            Response with verification status
        """
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # TODO: Implement proper token validation
        # For now, this is a placeholder
        
        try:
            user = User.objects.get(email=serializer.validated_data['email'])
            
            # Mark email as verified
            user.email_verified = True
            user.email_verified_at = timezone.now()
            user.save()
            
            return Response(
                {'detail': 'Email verified successfully.'},
                status=status.HTTP_200_OK
            )
        except User.DoesNotExist:
            return Response(
                {'detail': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @extend_schema(
        summary="Get user's profile",
        description="Retrieve a user's profile information.",
        responses={
            200: ProfileSerializer,
            404: OpenApiResponse(description="Profile not found"),
        }
    )
    @action(detail=True, methods=['get'], url_path='profile')
    def profile(self, request, pk=None):
        """
        Get a user's profile.
        
        Returns:
            Response with profile data
        """
        user = self.get_object()
        
        if not hasattr(user, 'profile'):
            return Response(
                {'detail': 'Profile not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = ProfileSerializer(
            user.profile,
            context={'request': request}
        )
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="List profiles",
        description="Retrieve a paginated list of user profiles with advanced filtering.",
        parameters=[
            OpenApiParameter(
                name='preferred_name',
                type=OpenApiTypes.STR,
                description='Filter by preferred name (case-insensitive partial match)'
            ),
            OpenApiParameter(
                name='contact_phone',
                type=OpenApiTypes.STR,
                description='Filter by contact phone (partial match)'
            ),
            OpenApiParameter(
                name='timezone',
                type=OpenApiTypes.STR,
                description='Filter by timezone (exact match, e.g., Europe/London)'
            ),
            OpenApiParameter(
                name='preferred_language',
                type=OpenApiTypes.STR,
                description='Filter by preferred language (en, es, fr)'
            ),
            OpenApiParameter(
                name='has_profile_picture',
                type=OpenApiTypes.BOOL,
                description='Filter by whether profile has a picture'
            ),
            OpenApiParameter(
                name='area_from',
                type=OpenApiTypes.INT,
                description='Filter by area location ID'
            ),
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                description='Search by email, username, preferred name, or contact phone'
            ),
            OpenApiParameter(
                name='ordering',
                type=OpenApiTypes.STR,
                description='Order by field (created_at, updated_at). Use - prefix for descending'
            ),
            OpenApiParameter(
                name='page_size',
                type=OpenApiTypes.INT,
                description='Number of results per page (max 100)'
            ),
        ],
        responses={200: ProfileSerializer(many=True)}
    ),
    retrieve=extend_schema(
        summary="Get profile details",
        description="Retrieve detailed information about a specific profile.",
        responses={200: ProfileSerializer}
    ),
    update=extend_schema(
        summary="Update profile (full)",
        description="Fully update a user's profile.",
        request=ProfileSerializer,
        responses={200: ProfileSerializer}
    ),
    partial_update=extend_schema(
        summary="Update profile (partial)",
        description="Partially update a user's profile.",
        request=ProfileSerializer,
        responses={200: ProfileSerializer}
    ),
)
class ProfileViewSet(viewsets.ModelViewSet):
    """Profile CRUD with filtering, search, and owner/admin permissions."""
    queryset = Profile.objects.select_related('user', 'area_from').all()
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    pagination_class = UserPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProfileFilterSet
    search_fields = ['user__email', 'user__username', 'preferred_name', 'contact_phone']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """
        Filter profiles based on permissions.
        
        Regular users only see their own profile, staff see all.
        
        Returns:
            Filtered queryset
        """
        queryset = super().get_queryset()
        
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        
        return queryset
    
    @extend_schema(
        summary="Get current user's profile",
        description="Retrieve the authenticated user's profile.",
        responses={200: ProfileSerializer}
    )
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        """
        Get current authenticated user's profile.
        
        Returns:
            Response with profile data
        """
        profile, created = Profile.objects.get_or_create(user=request.user)
        serializer = self.get_serializer(profile)
        return Response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="Login with email and password",
        description="Authenticate user with email and password. Returns JWT tokens in HTTP-only cookies "
                    "and user data in response body.",
        request=CustomTokenObtainPairSerializer,
        responses={
            200: OpenApiResponse(
                description="Login successful",
                response=UserDetailSerializer
            ),
            401: OpenApiResponse(description="Invalid credentials"),
        },
        examples=[
            OpenApiExample(
                'Login Example',
                value={
                    'email': 'user@example.com',
                    'password': 'SecurePass123!'
                }
            )
        ]
    )
)
class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom JWT token view with HTTP-only cookies.
    
    Authenticates users and returns JWT tokens in secure HTTP-only cookies
    along with user data in the response body.
    
    Security Features:
        - HTTP-only cookies (prevents XSS attacks)
        - Secure flag in production (HTTPS only)
        - SameSite protection (CSRF mitigation)
        - Token rotation on refresh
        - Short access token lifetime (15 minutes default)
        - Long refresh token lifetime (7 days default)
    
    Response Format:
        ```json
        {
            "user": {
                "id": 1,
                "email": "user@example.com",
                "username": "user",
                ...
            },
            "message": "Login successful."
        }
        ```
    
    Cookies Set:
        - access: JWT access token (15 min)
        - refresh: JWT refresh token (7 days)
    """
    serializer_class = CustomTokenObtainPairSerializer
    
    def post(self, request, *args, **kwargs):
        """
        Authenticate user and set JWT tokens in HTTP-only cookies.
        
        Returns:
            Response with user data and success message
        """
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            # Set HTTP-only cookies for tokens
            response.set_cookie(
                key='access',
                value=response.data['access'],
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',
                max_age=60 * 15  # 15 minutes
            )
            response.set_cookie(
                key='refresh',
                value=response.data['refresh'],
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',
                max_age=60 * 60 * 24 * 7  # 7 days
            )
            
            # Remove tokens from response body for security
            # Keep user data only
            response.data = {
                'user': response.data.get('user'),
                'message': 'Login successful.'
            }
        
        return response


@extend_schema_view(
    post=extend_schema(
        summary="Refresh access token",
        description="Refresh the access token using the refresh token from HTTP-only cookie.",
        responses={
            200: OpenApiResponse(description="Token refreshed successfully"),
            401: OpenApiResponse(description="Invalid or expired refresh token"),
        }
    )
)
class CustomTokenRefreshView(TokenRefreshView):
    """
    Custom token refresh view using HTTP-only cookies.
    
    Reads refresh token from HTTP-only cookie and returns new access token
    in HTTP-only cookie.
    
    Usage:
        Simply POST to this endpoint with the refresh cookie set.
        No request body required.
    """
    
    def post(self, request, *args, **kwargs):
        """
        Refresh access token from refresh cookie.
        
        Returns:
            Response with success message
        """
        refresh_token = request.COOKIES.get('refresh')
        
        if not refresh_token:
            return Response(
                {'detail': 'Refresh token not found in cookies.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Add refresh token to request data
        request.data._mutable = True  # type: ignore
        request.data['refresh'] = refresh_token
        
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            # Update access token cookie
            response.set_cookie(
                key='access',
                value=response.data['access'],
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',
                max_age=60 * 15  # 15 minutes
            )
            
            # Remove token from response body
            response.data = {'message': 'Token refreshed successfully.'}
        
        return response


@extend_schema(
    summary="Logout user",
    description="Logout user by clearing JWT tokens from HTTP-only cookies.",
    request=None,
    responses={
        200: {
            'type': 'object',
            'properties': {
                'message': {'type': 'string', 'example': 'Logout successful.'}
            },
            'description': 'Logout successful'
        },
    },
    tags=['Authentication']
)
@api_view(['POST'])
@permission_classes_decorator([permissions.IsAuthenticated])
def logout(request):
    """
    Logout user by clearing HTTP-only cookies.
    
    Returns:
        Response with success message
    """
    response = Response(
        {'message': 'Logout successful.'},
        status=status.HTTP_200_OK
    )
    response.delete_cookie('access')
    response.delete_cookie('refresh')
    return response


class GoogleOAuthViewSet(viewsets.ViewSet):
    """
    ViewSet for Google OAuth authentication.
    
    Provides endpoints for Google OAuth flow:
    1. Initiate OAuth: Get Google authorization URL
    2. Callback: Handle OAuth callback and create/login user
    
    Endpoints:
        - POST /api/auth/google/authorize/ - Get Google auth URL
        - POST /api/auth/google/callback/ - Handle OAuth callback
    
    Environment Variables Required:
        - GOOGLE_OAUTH_CLIENT_ID: Google OAuth client ID
        - GOOGLE_OAUTH_CLIENT_SECRET: Google OAuth client secret
        
    Example Flow:
        ```python
        # 1. Get authorization URL
        POST /api/auth/google/authorize/
        {
            "redirect_uri": "http://localhost:3000/auth/callback"
        }
        
        # Response:
        {
            "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
        }
        
        # 2. User authorizes on Google
        # 3. Google redirects to redirect_uri with code
        
        # 4. Exchange code for tokens and user info
        POST /api/auth/google/callback/
        {
            "code": "4/0AX...",
            "redirect_uri": "http://localhost:3000/auth/callback"
        }
        
        # Response: JWT tokens in cookies + user data
        ```
    """
    permission_classes = [permissions.AllowAny]
    
    # Google OAuth configuration
    GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
    GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
    GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'
    GOOGLE_SCOPES = [
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile',
    ]
    
    @extend_schema(
        summary="Initiate Google OAuth",
        description="Get Google OAuth authorization URL for user authentication.",
        request=GoogleOAuthSerializer,
        responses={
            200: OpenApiResponse(
                description="Authorization URL generated",
                examples=[
                    OpenApiExample(
                        'Authorization URL Response',
                        value={
                            'authorization_url': 'https://accounts.google.com/o/oauth2/v2/auth?...'
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Validation error"),
        }
    )
    @action(detail=False, methods=['post'], url_path='authorize')
    def authorize(self, request):
        """
        Generate Google OAuth authorization URL.
        
        Returns:
            Response with authorization URL
        """
        serializer = GoogleOAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get Google OAuth credentials from environment
        client_id = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
        
        if not client_id:
            return Response(
                {'detail': 'Google OAuth is not configured.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Build authorization URL
        params = {
            'client_id': client_id,
            'redirect_uri': serializer.validated_data['redirect_uri'],
            'response_type': 'code',
            'scope': ' '.join(self.GOOGLE_SCOPES),
            'access_type': 'offline',
            'prompt': 'consent',
        }
        
        # Add state parameter if provided (CSRF protection)
        if serializer.validated_data.get('state'):
            params['state'] = serializer.validated_data['state']
        
        # Construct URL
        from urllib.parse import urlencode
        authorization_url = f"{self.GOOGLE_AUTH_URL}?{urlencode(params)}"
        
        return Response({
            'authorization_url': authorization_url
        })
    
    @extend_schema(
        summary="Handle Google OAuth callback",
        description="Exchange authorization code for user information and authenticate user. "
                    "Creates new user if doesn't exist, or logs in existing user.",
        request=GoogleOAuthCallbackSerializer,
        responses={
            200: OpenApiResponse(
                description="Authentication successful",
                response=UserDetailSerializer
            ),
            400: OpenApiResponse(description="Invalid authorization code or OAuth error"),
            500: OpenApiResponse(description="OAuth configuration error"),
        }
    )
    @action(detail=False, methods=['post'], url_path='callback')
    def callback(self, request):
        """
        Handle Google OAuth callback and authenticate user.
        
        Returns:
            Response with user data and JWT tokens in cookies
        """
        serializer = GoogleOAuthCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get Google OAuth credentials
        client_id = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            return Response(
                {'detail': 'Google OAuth is not configured.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Exchange authorization code for access token
        token_data = {
            'code': serializer.validated_data['code'],
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': serializer.validated_data['redirect_uri'],
            'grant_type': 'authorization_code',
        }
        
        try:
            # Get access token
            token_response = requests.post(
                self.GOOGLE_TOKEN_URL,
                data=token_data,
                timeout=10
            )
            token_response.raise_for_status()
            token_json = token_response.json()
            access_token = token_json.get('access_token')
            
            if not access_token:
                return Response(
                    {'detail': 'Failed to obtain access token from Google.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get user information
            userinfo_response = requests.get(
                self.GOOGLE_USERINFO_URL,
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10
            )
            userinfo_response.raise_for_status()
            google_user_info = userinfo_response.json()
            
            # Create or update user
            user = serializer.create_or_update_user(
                serializer.validated_data,
                google_user_info
            )
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            # Prepare response
            response = Response({
                'user': UserDetailSerializer(
                    user,
                    context={'request': request}
                ).data,
                'message': 'Authentication successful.'
            }, status=status.HTTP_200_OK)
            
            # Set HTTP-only cookies
            response.set_cookie(
                key='access',
                value=str(refresh.access_token),
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',
                max_age=60 * 15  # 15 minutes
            )
            response.set_cookie(
                key='refresh',
                value=str(refresh),
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',
                max_age=60 * 60 * 24 * 7  # 7 days
            )
            
            return response
            
        except requests.RequestException as e:
            return Response(
                {'detail': f'OAuth request failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'detail': f'Authentication error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
