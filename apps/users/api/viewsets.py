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
from typing import Any, Dict, Optional

from rest_framework import viewsets, status, permissions, filters
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action, api_view, permission_classes as permission_classes_decorator
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db import transaction
from apps.users.tasks import (
    send_password_reset_email,
    send_welcome_email,
    send_email_verification_email,
    send_password_changed_email,
    send_password_reset_confirmation_email,
)
from apps.users.services.tokens import email_verification_token

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiExample
)
from drf_spectacular.types import OpenApiTypes
import requests

from .serializers import (
    UnrestrictedProfileSerializer,
    UserSerializer,
    UserDetailSerializer,
    UserRegistrationSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    EmailVerificationSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    CustomTokenObtainPairSerializer,
    GoogleOAuthSerializer,
    GoogleOAuthCallbackSerializer,
    ProfileSerializer,
)
from .filtersets import ProfileFilterSet, UserFilterSet
from apps.users.models import Profile

User = get_user_model()

import logging
logger = logging.getLogger(__name__)


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

    def has_permission(self, request, view):
        """Allow access if user is authenticated."""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        """Check if user owns the object or is staff."""
        # Staff can access any object
        if request.user and request.user.is_staff:
            return True
        
        # if retrieve of list, allow, but CUD operations require ownership

        if view.action in ['retrieve', 'list']:
            return True
        
        # Check if obj is a User or has a user attribute (like Profile)
        if isinstance(obj, User):
            return obj == request.user
        elif hasattr(obj, 'user'):
            return obj.user == request.user
        
        return False


@extend_schema_view(
    list=extend_schema(
        summary="List Users",
        description=(
            "Retrieve a paginated list of all users with advanced filtering and search capabilities. "
            "Staff users can view all users with complete information, while regular users can only view their own profile. "
            "Supports searching by email, username, name, and filtering by active status and OAuth provider."
        ),
        tags=['Users'],
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
                name='organisation',
                type=OpenApiTypes.STR,
                description='Filter by organisation name (case-insensitive partial match)'
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
        summary="Get User Details",
        description=(
            "Retrieve comprehensive information about a specific user including profile data, account status, and timestamps. "
            "Regular users can only view their own profile, while staff members can view any user. "
            "Includes HATEOAS links for related resources."
        ),
        tags=['Users'],
        responses={
            200: UserDetailSerializer,
            401: OpenApiResponse(description="Unauthorized"),
            403: OpenApiResponse(description="Forbidden - Cannot view other users"),
            404: OpenApiResponse(description="User not found"),
        }
    ),
    create=extend_schema(
        summary="Register New User",
        description=(
            "Create a new user account with email and password authentication. "
            "This endpoint is public and does not require authentication. "
            "Automatically creates associated profile and returns JWT tokens in HTTP-only cookies. "
            "Email verification may be required based on system configuration."
        ),
        tags=['Users'],
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
        summary="Update User (Full)",
        description=(
            "Fully update a user's account information including personal details and preferences. "
            "Requires complete payload with all fields. Users can only update their own profile unless they are staff. "
            "Use PATCH for partial updates."
        ),
        tags=['Users'],
        request=UserUpdateSerializer,
        responses={
            200: UserDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            403: OpenApiResponse(description="Forbidden - Cannot update other users"),
        }
    ),
    partial_update=extend_schema(
        summary="Update User (Partial)",
        description=(
            "Partially update a user's account information without providing complete payload. "
            "Allows updating individual fields like first name, last name, or other profile attributes. "
            "Users can only update their own profile unless they are staff."
        ),
        tags=['Users'],
        request=UserUpdateSerializer,
        responses={
            200: UserDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            403: OpenApiResponse(description="Forbidden - Cannot update other users"),
        }
    ),
    destroy=extend_schema(
        summary="Delete User Account",
        description=(
            "Soft delete a user account by deactivating it instead of permanent removal. "
            "Users can delete their own account, and staff members can delete any account. "
            "Deactivated accounts retain data for compliance but cannot log in. "
            "This is a soft delete operation - the account is marked inactive rather than removed from the database."
        ),
        tags=['Users'],
        responses={
            204: OpenApiResponse(description="User deleted successfully"),
            403: OpenApiResponse(description="Forbidden - Cannot delete other users"),
            404: OpenApiResponse(description="User not found"),
        }
    ),
)
class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for comprehensive user management with CRUD operations and custom actions.
    
    Provides full user lifecycle management including:
    - User registration and authentication
    - Profile viewing and editing
    - Password management
    - Email verification
    - Account deactivation (soft delete)
    - Advanced filtering and search
    - HATEOAS links for API discoverability
    
    Custom Actions:
        - me: Get current authenticated user's profile
        - update_profile: Update current user's profile
        - change_password: Change password with verification
        - verify_email: Verify email address with token
        - profile: Get a specific user's profile
    """
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
    filterset_class = UserFilterSet
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

        # Non-staff users can only see themselves.
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

    @extend_schema(
        summary="List Event Attendee Users",
        description=(
            "Retrieve users who belong to a specific event context. "
            "Membership includes users attached to attendee records, EventStaff assignments, "
            "or EventRoleAssignment entries for the selected event. "
            "Supports optional search by email, username, and name fields."
        ),
        tags=['Users'],
        parameters=[
            OpenApiParameter(
                name='event_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=True,
                description='Event UUID to scope the user list.'
            ),
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Optional search across email, username, first name, and last name.'
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Page number for paginated results.'
            ),
            OpenApiParameter(
                name='page_size',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Page size (max 100).'
            ),
        ],
        responses={
            200: UserSerializer(many=True),
            400: OpenApiResponse(description='Missing or invalid event_id query parameter.'),
            401: OpenApiResponse(description='Unauthorized - Authentication required'),
        },
    )
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated], url_path='event-attendees')
    def event_attendees(self, request: Request) -> Response:
        """List users scoped to an event's attendee/service-team membership."""
        event_id = request.query_params.get('event_id')
        if not event_id:
            return Response(
                {'detail': "'event_id' query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = User.objects.select_related('profile').prefetch_related('groups').filter(
            is_active=True
        ).filter(
            Q(attendees__event__url_safe_title=event_id, attendees__deleted_at__isnull=True) |
            Q(event_staff__event__url_safe_title=event_id, event_staff__user__isnull=False) |
            Q(event_roles__event__url_safe_title=event_id)
        ).distinct()

        search_value = request.query_params.get('search')
        if search_value:
            queryset = queryset.filter(
                Q(email__icontains=search_value) |
                Q(username__icontains=search_value) |
                Q(first_name__icontains=search_value) |
                Q(last_name__icontains=search_value)
            )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def perform_create(self, serializer):
        """
        Create user and associated profile, then queue welcome and
        email verification emails via transaction.on_commit so they
        only fire after the user record has committed to the database.

        Args:
            serializer: Validated UserRegistrationSerializer
        """
        user = serializer.save()

        # Ensure profile exists (signal should handle this)
        if not hasattr(user, 'profile'):
            Profile.objects.create(user=user)

        # Build verification URL now while we still have the user object.
        _user_pk = user.pk
        _uid = urlsafe_base64_encode(force_bytes(user.pk))
        _token = email_verification_token.make_token(user)
        _verification_url = (
            f"{settings.FRONTEND_URL}/verify-email"
            f"?uid={_uid}&token={_token}"
        )

        transaction.on_commit(lambda: send_welcome_email.delay(_user_pk))
        transaction.on_commit(
            lambda: send_email_verification_email.delay(_user_pk, _verification_url)
        )
    
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
        summary="Get Current User Profile",
        description=(
            "Retrieve the authenticated user's complete profile information including all personal details, "
            "profile data, account status, and timestamps. This is a convenience endpoint equivalent to "
            "GET /users/{id}/ with the current user's ID."
        ),
        tags=['Users'],
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
        summary="Update Current User Profile",
        description=(
            "Update the authenticated user's profile information using a partial update. "
            "Allows modifying personal details like name, contact information, and preferences "
            "without providing all fields."
        ),
        tags=['Users'],
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
        summary="Change Password",
        description=(
            "Change the authenticated user's password with verification. "
            "Requires the current password for security validation before setting the new password. "
            "New password must meet security requirements (minimum length, complexity)."
        ),
        tags=['Users'],
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

        if user.is_anonymous:
            return Response(
                {'detail': 'Authentication credentials were not provided.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Verify old password
        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {'old_password': ['Wrong password.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Set new password
        user.set_password(serializer.validated_data['new_password'])
        user.save()

        _user_pk = user.pk
        transaction.on_commit(lambda: send_password_changed_email.delay(_user_pk))

        return Response(
            {'detail': 'Password updated successfully.'},
            status=status.HTTP_200_OK
        )
    
    @extend_schema(
        summary="Verify Email Address",
        description=(
            "Verify a user's email address using the verification token sent via email. "
            "Email verification ensures that users have access to the email address they registered with. "
            "May be required for certain features or event registrations."
        ),
        tags=['Users'],
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
        Verify a user's email address using the uid + token pair from the
        verification email link.

        The token is produced by EmailVerificationTokenGenerator and is
        single-use: it invalidates automatically once ``email_verified``
        flips to True, preventing replay attacks.

        Returns:
            200 on success, 400 on invalid / expired token.
        """
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str

        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']

        INVALID_RESPONSE = Response(
            {'detail': 'Invalid or expired verification link.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

        try:
            user_pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_pk)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return INVALID_RESPONSE

        if user.email_verified:
            return Response(
                {'detail': 'Email address is already verified.'},
                status=status.HTTP_200_OK,
            )

        if not email_verification_token.check_token(user, token):
            return INVALID_RESPONSE

        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.save(update_fields=['email_verified', 'email_verified_at'])

        return Response(
            {'detail': 'Email verified successfully.'},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Resend Email Verification",
        description=(
            "Re-generate and resend the email verification link for the currently "
            "authenticated user.  Always returns 200 to avoid leaking whether the "
            "account is already verified.  If the account is already verified the "
            "request is silently ignored."
        ),
        tags=['Users'],
        responses={
            200: OpenApiResponse(description="Verification email queued if not already verified"),
            401: OpenApiResponse(description="Unauthorized"),
        },
    )
    @action(
        detail=False,
        methods=['post'],
        permission_classes=[permissions.IsAuthenticated],
        url_path='resend-verification',
    )
    def resend_verification(self, request):
        """
        Resend the email verification link to the current user.

        Silently ignores already-verified accounts so the response never leaks
        verification state to potential attackers.
        """
        user = request.user

        if not user.email_verified:
            _user_pk = user.pk
            _uid = urlsafe_base64_encode(force_bytes(user.pk))
            _token = email_verification_token.make_token(user)
            _verification_url = (
                f"{settings.FRONTEND_URL}/verify-email"
                f"?uid={_uid}&token={_token}"
            )
            transaction.on_commit(
                lambda: send_email_verification_email.delay(_user_pk, _verification_url)
            )
            logger.info("resend_verification: queued for user_pk=%s", user.pk)

        return Response(
            {'detail': 'If your email is not yet verified, a new verification link has been sent.'},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Request Password Reset",
        description=(
            "Send a password reset link to the provided email address. "
            "Always returns 200 regardless of whether the email exists to prevent account enumeration."
        ),
        tags=['Users'],
        request=PasswordResetRequestSerializer,
        responses={
            200: OpenApiResponse(description="Reset link sent if account exists"),
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny],
            url_path='forgot-password')
    def forgot_password(self, request):
        """
        Initiate password reset by email.

        Generates a Django PasswordResetTokenGenerator uid+token pair, builds a
        link pointing at the frontend reset page, and dispatches the email via
        Celery.  The response is always 200 to avoid leaking whether an account
        exists for a given email address.
        """

        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        NEUTRAL_RESPONSE = Response(
            {'detail': 'If an account exists with this email, a password reset link has been sent.'},
            status=status.HTTP_200_OK
        )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return NEUTRAL_RESPONSE
        if not user.is_active:
            return NEUTRAL_RESPONSE

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = PasswordResetTokenGenerator().make_token(user)
        reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

        send_password_reset_email.delay(user.id, reset_url)

        return NEUTRAL_RESPONSE

    @extend_schema(
        summary="Confirm Password Reset",
        description=(
            "Set a new password using the uid and token received via the reset email. "
            "The token is single-use and expires after the configured timeout."
        ),
        tags=['Users'],
        request=PasswordResetConfirmSerializer,
        responses={
            200: OpenApiResponse(description="Password reset successfully"),
            400: OpenApiResponse(description="Invalid or expired reset link"),
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny],
            url_path='reset-password')
    def reset_password(self, request):
        """
        Complete password reset with uid, token, and new password.
        """
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str
        from django.contrib.auth.tokens import PasswordResetTokenGenerator

        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        INVALID_RESPONSE = Response(
            {'detail': 'Invalid or expired reset link.'},
            status=status.HTTP_400_BAD_REQUEST
        )

        try:
            user_pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_pk)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return INVALID_RESPONSE

        if not PasswordResetTokenGenerator().check_token(user, token):
            return INVALID_RESPONSE

        user.set_password(new_password)
        user.save()

        _user_pk = user.pk
        transaction.on_commit(
            lambda: send_password_reset_confirmation_email.delay(_user_pk)
        )

        return Response(
            {'detail': 'Password has been reset successfully.'},
            status=status.HTTP_200_OK
        )

    @extend_schema(
        summary="Get User's Profile",
        description=(
            "Retrieve a specific user's profile information including extended profile data. "
            "Access is restricted based on permissions - users can view their own profile, "
            "staff can view any profile."
        ),
        tags=['Users'],
        responses={
            200: ProfileSerializer,
            404: OpenApiResponse(description="Profile not found"),
        }
    )
    @action(detail=True, methods=['get'], url_path='profile')
    def profile(self, request: Request, pk=None) -> Response:
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
        summary="List Profiles",
        description=(
            "Retrieve a paginated list of user profiles with comprehensive filtering and search capabilities. "
            "Profiles contain extended user information including preferences, contact details, timezone, and language settings. "
            "Staff users can view all profiles, while regular users can only view their own. "
            "Supports filtering by location, language, timezone, and custom search."
        ),
        tags=['Profiles'],
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
        summary="Get Profile Details",
        description=(
            "Retrieve comprehensive information about a specific user profile including "
            "personal preferences, contact information, timezone, language settings, profile picture, "
            "and associated location data."
        ),
        tags=['Profiles'],
        responses={200: ProfileSerializer}
    ),
    update=extend_schema(
        summary="Update Profile (Full)",
        description=(
            "Fully update a user's profile with complete payload. "
            "Updates extended user information including preferences, contact details, timezone, and location. "
            "Users can only update their own profile unless they are staff."
        ),
        tags=['Profiles'],
        request=ProfileSerializer,
        responses={200: ProfileSerializer}
    ),
    partial_update=extend_schema(
        summary="Update Profile (Partial)",
        description=(
            "Partially update a user's profile without providing complete payload. "
            "Ideal for updating individual profile attributes like preferred name, contact phone, "
            "timezone, or language settings. Users can only update their own profile unless they are staff."
        ),
        tags=['Profiles'],
        request=ProfileSerializer,
        responses={200: ProfileSerializer}
    ),
    destroy=extend_schema(
        summary="Delete Profile",
        description=(
            "Delete a user profile. This removes extended profile data but does not delete the user account. "
            "Use with caution as this operation cannot be easily undone."
        ),
        tags=['Profiles'],
        responses={
            204: OpenApiResponse(description="Profile deleted successfully"),
            403: OpenApiResponse(description="Forbidden - Cannot delete other profiles"),
        }
    ),
)
class ProfileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for user profile management with CRUD operations.
    
    Handles extended user information beyond basic authentication including:
    - Personal preferences and display settings
    - Contact information and communication preferences
    - Timezone and language settings
    - Profile picture management
    - Location associations
    - Custom profile fields
    
    Access Control:
        - Regular users can only view and edit their own profile
        - Staff users can view and edit all profiles
        - Supports advanced filtering and search
    """
    queryset = Profile.objects.select_related('user', 'area_from').all()
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    pagination_class = UserPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProfileFilterSet
    search_fields = ['user__email', 'user__username', 'preferred_name', 'contact_phone']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        restricted_views = ["retrieve", "update", "partial_update"]
        if self.action in restricted_views and self.request.user == self.get_object().user:
            return UnrestrictedProfileSerializer
        return ProfileSerializer

    
    @extend_schema(
        summary="Get Current User's Profile",
        description=(
            "Retrieve the authenticated user's profile with all extended information. "
            "This is a convenience endpoint that returns the profile for the currently logged-in user. "
            "Automatically creates a profile if one doesn't exist."
        ),
        tags=['Profiles'],
        responses={200: ProfileSerializer}
    )
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request: Request) -> Response:
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
        summary="Login with Email and Password",
        description=(
            "Authenticate a user with email and password credentials. "
            "Returns JWT access and refresh tokens in secure HTTP-only cookies for enhanced security. "
            "Access tokens are short-lived (15 minutes) while refresh tokens last longer (7 days). "
            "User profile data is returned in the response body. "
            "Tokens are automatically included in cookies for subsequent requests."
        ),
        tags=['Authentication'],
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
    
    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Authenticate user and set JWT tokens in HTTP-only cookies.
        
        Returns:
            Response with user data and success message
        """
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            # Get user from serializer for logging
            user_email = self.user.email if hasattr(self, 'user') and self.user else 'unknown'
            
            # Set HTTP-only cookies for tokens
            _samesite = 'None' if not settings.DEBUG else 'Lax'
            access_token = response.data['access']
            response.set_cookie(
                key='access',
                value=access_token,
                httponly=True,
                secure=not settings.DEBUG,
                samesite=_samesite,
                domain=None,  # Allow localhost in dev
                max_age=60 * 15  # 15 minutes
            )
            response.set_cookie(
                key='refresh',
                value=response.data['refresh'],
                httponly=True,
                secure=not settings.DEBUG,
                samesite=_samesite,
                domain=None,  # Allow localhost in dev
                max_age=60 * 60 * 24 * 7  # 7 days
            )
            
            # Return access token in body so SPAs can use Bearer header auth
            # (cross-origin cookie sending is unreliable; Bearer token is not)
            # Keep user data only
            response.data = {
                'user': response.data.get('user'),
                'access': access_token,
                'message': 'Login successful.'
            }
        
        return response


@extend_schema_view(
    post=extend_schema(
        summary="Refresh Access Token",
        description=(
            "Refresh the access token using the refresh token stored in HTTP-only cookies. "
            "Access tokens expire after 15 minutes for security, while refresh tokens last 7 days. "
            "This endpoint reads the refresh token from cookies automatically and returns a new access token. "
            "No request body is required - the refresh token is read from cookies. "
            "Use this endpoint before access token expiration to maintain authenticated sessions."
        ),
        tags=['Authentication'],
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
    
    def post(self, request: Request, *args, **kwargs) -> Response:
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
        # request.data._mutable = True  # type: ignore
        request.data['refresh'] = refresh_token
        
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            _samesite = 'None' if not settings.DEBUG else 'Lax'
            access_token = response.data['access']
            # Update access token cookie
            response.set_cookie(
                key='access',
                value=access_token,
                httponly=True,
                secure=not settings.DEBUG,
                samesite=_samesite,
                max_age=60 * 15  # 15 minutes
            )

            # Update refresh cookie — required because ROTATE_REFRESH_TOKENS=True
            # issues a new refresh token each cycle and blacklists the old one.
            # Without this the browser keeps the stale (blacklisted) refresh cookie.
            if 'refresh' in response.data:
                response.set_cookie(
                    key='refresh',
                    value=response.data['refresh'],
                    httponly=True,
                    secure=not settings.DEBUG,
                    samesite=_samesite,
                    max_age=60 * 60 * 24 * 7  # 7 days
                )

            # Return new access token in body for Bearer header auth
            response.data = {'access': access_token, 'message': 'Token refreshed successfully.'}
        
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
    
    # Delete cookies with same parameters as when they were set
    # This is critical - cookies must be deleted with matching domain, path, and samesite
    response.delete_cookie(
        key='access',
        path='/',
        domain=None,
        samesite='Lax'
    )
    response.delete_cookie(
        key='refresh',
        path='/',
        domain=None,
        samesite='Lax'
    )
    
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
    authentication_classes = []  # No session auth — avoids spurious CSRF enforcement on public OAuth endpoints
    GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
    GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
    GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'
    GOOGLE_SCOPES = [
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile',
    ]
    
    @extend_schema(
        summary="Initiate Google OAuth",
        description=(
            "Generate Google OAuth authorization URL for user authentication. "
            "Returns a URL that redirects users to Google's authorization page where they can grant permissions. "
            "After authorization, Google redirects back to the specified redirect_uri with an authorization code."
        ),
        tags=['Authentication'],
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
    def authorize(self, request: Request) -> Response:
        """
        Generate Google OAuth authorization URL.
        
        Returns:
            Response with authorization URL
        """
        serializer = GoogleOAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get Google OAuth credentials from environment
        client_id = settings.GOOGLE_OAUTH_CLIENT_ID
        
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
        summary="Handle Google OAuth Callback",
        description=(
            "Exchange Google OAuth authorization code for user information and authenticate the user. "
            "Creates a new user account if the Google email doesn't exist in the system, or logs in existing user. "
            "Returns JWT tokens in secure HTTP-only cookies and user profile data in response body. "
            "Automatically associates the Google account with the user for future OAuth logins."
        ),
        tags=['Authentication'],
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
    def callback(self, request: Request) -> Response:
        """
        Handle Google OAuth callback and authenticate user.
        
        Returns:
            Response with user data and JWT tokens in cookies
        """
        serializer = GoogleOAuthCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get Google OAuth credentials
        client_id = settings.GOOGLE_OAUTH_CLIENT_ID
        client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET
        
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
            logger.info(f'User info response: {userinfo_response.json()}')
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
            _samesite = 'None' if not settings.DEBUG else 'Lax'
            response.set_cookie(
                key='access',
                value=str(refresh.access_token),
                httponly=True,
                secure=not settings.DEBUG,
                samesite=_samesite,
                domain=None,  # Allow localhost in dev
                max_age=60 * 15  # 15 minutes
            )
            response.set_cookie(
                key='refresh',
                value=str(refresh),
                httponly=True,
                secure=not settings.DEBUG,
                samesite=_samesite,
                domain=None,  # Allow localhost in dev
                max_age=60 * 60 * 24 * 7  # 7 days
            )
            
            return response
            
        except requests.RequestException as e:
            return Response(
                {'detail': f'OAuth request failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f'Authentication error: {str(e)}')
            return Response(
                {'detail': f'Authentication error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
