"""
Production-grade serializers for the users app.

This module provides comprehensive serializers for user management, authentication,
and profile operations with HATEOAS support, extensive validation, and Google OAuth integration.

Serializers:
    - UserSerializer: Main user representation with hypermedia links
    - ProfileSerializer: User profile with nested relationships
    - UserDetailSerializer: Comprehensive user details with profile
    - UserRegistrationSerializer: User registration with validation
    - UserUpdateSerializer: User profile updates
    - ChangePasswordSerializer: Secure password change
    - EmailVerificationSerializer: Email verification handling
    - CustomTokenObtainPairSerializer: JWT token generation with user data
    - GoogleOAuthSerializer: Google OAuth authentication
    - GoogleOAuthCallbackSerializer: Google OAuth callback handling

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
import requests
from typing import Dict, Any, Optional, TYPE_CHECKING

from apps.users.models import Profile
from apps.locations.models import AreaLocation

if TYPE_CHECKING:
    from apps.users.models import CommunityUser

User = get_user_model()


class ProfileSerializer(serializers.HyperlinkedModelSerializer):
    """
    Comprehensive serializer for user Profile model.
    
    Provides full profile management with HATEOAS links and nested relationships.
    Supports profile picture uploads, location management, and timezone settings.
    
    Fields:
        - url: HATEOAS link to profile detail
        - user: Hyperlinked user reference
        - preferred_name: User's preferred display name
        - profile_picture: Image upload field
        - area_from: Nested area location details
        - contact_phone: Validated phone number
        - preferred_language: Language preference
        - timezone: User's timezone setting
        - full_name: Computed full name (read-only)
        - created_at: Profile creation timestamp
        - updated_at: Last update timestamp
    
    Example:
        ```python
        serializer = ProfileSerializer(profile, context={'request': request})
        data = serializer.data
        # Returns profile with hypermedia links
        ```
    """
    user = serializers.HyperlinkedRelatedField(
        view_name='users:user-detail',
        read_only=True
    )
    area_from = serializers.PrimaryKeyRelatedField(
        queryset=AreaLocation.objects.all(),
        required=False,
        allow_null=True,
        help_text="The area location where the user is from"
    )
    area_from_details = serializers.SerializerMethodField(
        help_text="Detailed information about the user's area"
    )
    full_name = serializers.CharField(
        read_only=True,
        help_text="User's full name derived from first and last name"
    )
    profile_picture_url = serializers.SerializerMethodField(
        help_text="Absolute URL to the profile picture"
    )
    timezone = serializers.CharField(
        help_text="User's timezone (e.g., 'Europe/London', 'America/New_York')"
    )
    
    class Meta:
        model = Profile
        fields = (
            'url', 'user', 'preferred_name', 'profile_picture', 'profile_picture_url',
            'profile_picture_uploaded_at', 'area_from', 'area_from_details',
            'contact_phone', 'preferred_language', 'timezone', 'full_name',
            'created_at', 'updated_at'
        )
        read_only_fields = (
            'url', 'user', 'full_name', 'profile_picture_uploaded_at',
            'created_at', 'updated_at'
        )
        extra_kwargs = {
            'url': {'view_name': 'users:profile-detail', 'lookup_field': 'pk'},
            'profile_picture': {
                'help_text': 'Profile picture image (max 5MB, formats: JPEG, PNG, GIF)',
                'required': False
            },
            'preferred_name': {
                'help_text': 'Preferred display name (will be title-cased)',
                'max_length': 100
            },
            'contact_phone': {
                'help_text': 'Contact phone number with country code'
            },
            'created_at': {'default': None},
            'updated_at': {'default': None},
            'profile_picture_uploaded_at': {'default': None},
            'timezone': {'source': '*'},  # Prevent auto-generation from TimeZoneField
        }
    
    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_area_from_details(self, obj: Profile) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about the user's area location.
        
        Args:
            obj: Profile instance
            
        Returns:
            Dictionary with area details or None if not set
        """
        if obj.area_from:
            return {
                'id': obj.area_from.id,
                'name': obj.area_from.name if hasattr(obj.area_from, 'name') else str(obj.area_from),
            }
        return None
    
    @extend_schema_field(OpenApiTypes.URI)
    def get_profile_picture_url(self, obj: Profile) -> Optional[str]:
        """
        Get absolute URL for profile picture.
        
        Args:
            obj: Profile instance
            
        Returns:
            Absolute URL to profile picture or None
        """
        if obj.profile_picture:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None
    
    def validate_profile_picture(self, value):
        """
        Validate profile picture upload.
        
        Checks file size (max 5MB) and format (JPEG, PNG, GIF).
        
        Args:
            value: Uploaded file
            
        Returns:
            Validated file
            
        Raises:
            serializers.ValidationError: If validation fails
        """
        if value:
            # Check file size (5MB max)
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError(
                    "Profile picture size must not exceed 5MB."
                )
            
            # Check file format
            allowed_formats = ['image/jpeg', 'image/png', 'image/gif']
            if value.content_type not in allowed_formats:
                raise serializers.ValidationError(
                    "Profile picture must be in JPEG, PNG, or GIF format."
                )
        
        return value
    
    def validate_contact_phone(self, value: str) -> str:
        """
        Validate phone number format.
        
        Args:
            value: Phone number string
            
        Returns:
            Validated phone number
            
        Raises:
            serializers.ValidationError: If phone number is invalid
        """
        if value and not value.strip():
            raise serializers.ValidationError("Phone number cannot be empty.")
        return value


class UserSerializer(serializers.HyperlinkedModelSerializer):
    """
    Production-grade serializer for CommunityUser model with HATEOAS support.
    
    Provides comprehensive user representation with hypermedia links, nested profile data,
    and computed fields. Follows REST best practices and includes extensive documentation.
    
    Features:
        - HATEOAS links for API discoverability
        - Nested profile data
        - OAuth provider information
        - Email verification status
        - Computed display name
        - ISO 8601 timestamps
    
    Fields:
        - url: HATEOAS link to user detail endpoint
        - id: Unique user identifier (UUID or int)
        - email: User's email address (unique, used for authentication)
        - username: Display username (auto-generated from email if not provided)
        - first_name: User's first name
        - last_name: User's last name
        - display_name: Best available display name (computed)
        - profile: Nested profile data (read-only)
        - profile_url: HATEOAS link to profile endpoint
        - email_verified: Email verification status
        - email_verified_at: Timestamp of email verification
        - oauth_provider: OAuth provider used (google, github, or none)
        - is_active: Account active status
        - is_staff: Staff status (admin access)
        - date_joined: Account creation timestamp
        - last_login: Last login timestamp
        - created_at: User creation timestamp
        - updated_at: Last update timestamp
    
    Related Endpoints:
        - GET /api/users/{id}/: Retrieve user details
        - GET /api/users/{id}/profile/: Retrieve user profile
        - PATCH /api/users/{id}/: Update user details
        
    Example:
        ```python
        # Serialize a user with HATEOAS links
        serializer = UserSerializer(user, context={'request': request})
        data = serializer.data
        
        # Response includes:
        # {
        #     "url": "http://api.example.com/api/users/1/",
        #     "id": 1,
        #     "email": "user@example.com",
        #     "profile_url": "http://api.example.com/api/users/1/profile/",
        #     ...
        # }
        ```
    """
    profile = ProfileSerializer(read_only=True, help_text="User's profile information")
    profile_url = serializers.HyperlinkedIdentityField(
        view_name='users:user-profile',
        lookup_field='pk',
        help_text="HATEOAS link to user's profile endpoint"
    )
    display_name = serializers.CharField(
        source='get_display_name',
        read_only=True,
        help_text="Best available display name for the user"
    )
    
    class Meta:
        model = User
        fields = (
            'url', 'id', 'email', 'username', 'first_name', 'last_name',
            'display_name', 'profile', 'profile_url',
            'email_verified', 'email_verified_at', 'oauth_provider',
            'is_active', 'is_staff', 'date_joined', 'last_login',
            'created_at', 'updated_at'
        )
        read_only_fields = (
            'url', 'id', 'email', 'display_name', 'profile', 'profile_url',
            'email_verified', 'email_verified_at', 'oauth_provider',
            'is_active', 'is_staff', 'date_joined', 'last_login',
            'created_at', 'updated_at'
        )
        extra_kwargs = {
            'url': {'view_name': 'users:user-detail', 'lookup_field': 'pk'},
            'username': {
                'help_text': 'Display username (auto-generated from email if not provided)',
                'required': False
            },
            'first_name': {
                'help_text': "User's first name",
                'required': False
            },
            'last_name': {
                'help_text': "User's last name",
                'required': False
            },
            'created_at': {'default': None},
            'updated_at': {'default': None},
            'date_joined': {'default': None},
            'last_login': {'default': None},
            'email_verified_at': {'default': None},
        }


class UserDetailSerializer(UserSerializer):
    """
    Extended user serializer with comprehensive details for authenticated requests.
    
    Includes all fields from UserSerializer plus additional sensitive information
    only available to the user themselves or administrators.
    
    Additional Fields:
        - groups: User's permission groups
        - permissions: User's specific permissions
        
    Use Cases:
        - /api/users/me/ endpoint
        - Admin user management
        - User profile settings page
    """
    groups = serializers.StringRelatedField(many=True, read_only=True)
    
    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ('groups',)


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for new user registration with comprehensive validation.
    
    Handles user creation with password validation, duplicate checking,
    and optional OAuth provider information. Automatically creates
    associated Profile object.
    
    Fields:
        - email: User's email (required, unique)
        - password: User's password (required, validated against Django's password validators)
        - password_confirm: Password confirmation (required, must match password)
        - username: Display username (optional, auto-generated if not provided)
        - first_name: User's first name (optional)
        - last_name: User's last name (optional)
        
    Validation:
        - Email format and uniqueness
        - Password strength (Django validators)
        - Password confirmation match
        - Username format (if provided)
        
    Example:
        ```python
        data = {
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'first_name': 'John',
            'last_name': 'Doe'
        }
        serializer = UserRegistrationSerializer(data=data)
        if serializer.is_valid():
            user = serializer.save()
        ```
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'},
        help_text="Password (min 8 characters, must include letters and numbers)"
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="Password confirmation (must match password)"
    )
    
    class Meta:
        model = User
        fields = (
            'email', 'password', 'password_confirm',
            'username', 'first_name', 'last_name'
        )
        extra_kwargs = {
            'email': {
                'required': True,
                'help_text': 'Valid email address (used for login)'
            },
            'username': {
                'required': False,
                'help_text': 'Display username (auto-generated from email if not provided)'
            },
            'first_name': {
                'required': False,
                'help_text': "User's first name"
            },
            'last_name': {
                'required': False,
                'help_text': "User's last name"
            },
        }
    
    def validate_email(self, value: str) -> str:
        """
        Validate email address format and uniqueness.
        
        Args:
            value: Email address
            
        Returns:
            Validated and normalized email
            
        Raises:
            serializers.ValidationError: If email is invalid or already exists
        """
        # Normalize email
        value = value.lower().strip()
        
        # Check if email already exists
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "A user with this email address already exists."
            )
        
        return value
    
    def validate_username(self, value: Optional[str]) -> Optional[str]:
        """
        Validate username format.
        
        Args:
            value: Username
            
        Returns:
            Validated username
            
        Raises:
            serializers.ValidationError: If username format is invalid
        """
        if value:
            value = value.strip()
            # Check for valid characters (alphanumeric, underscore, hyphen)
            if not value.replace('_', '').replace('-', '').isalnum():
                raise serializers.ValidationError(
                    "Username can only contain letters, numbers, underscores, and hyphens."
                )
        return value
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate that passwords match and perform cross-field validation.
        
        Args:
            attrs: Validated attribute dictionary
            
        Returns:
            Validated attributes
            
        Raises:
            serializers.ValidationError: If validation fails
        """
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Password fields didn't match."
            })
        
        return attrs
    
    def create(self, validated_data: Dict[str, Any]) -> 'CommunityUser':
        """
        Create a new user with encrypted password and associated profile.
        
        Args:
            validated_data: Validated user data
            
        Returns:
            Created User instance
        """
        # Remove password confirmation
        validated_data.pop('password_confirm')
        
        # Create user with hashed password
        user = User.objects.create_user(**validated_data)
        
        # Create associated profile (if signal doesn't handle it)
        if not hasattr(user, 'profile'):
            Profile.objects.create(user=user)
        
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating user profile information.
    
    Allows authenticated users to update their basic profile fields.
    Does not permit email changes (requires separate verification flow).
    
    Updateable Fields:
        - username: Display username
        - first_name: User's first name
        - last_name: User's last name
        
    Example:
        ```python
        data = {'first_name': 'Jane', 'last_name': 'Smith'}
        serializer = UserUpdateSerializer(user, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
        ```
    """
    
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name')
        extra_kwargs = {
            'username': {
                'help_text': 'Display username',
                'required': False
            },
            'first_name': {
                'help_text': "User's first name",
                'required': False
            },
            'last_name': {
                'help_text': "User's last name",
                'required': False
            },
        }
    
    def validate_username(self, value: str) -> str:
        """
        Validate username format.
        
        Args:
            value: Username
            
        Returns:
            Validated username
            
        Raises:
            serializers.ValidationError: If username format is invalid
        """
        if value:
            value = value.strip()
            if not value.replace('_', '').replace('-', '').isalnum():
                raise serializers.ValidationError(
                    "Username can only contain letters, numbers, underscores, and hyphens."
                )
        return value


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for secure password change endpoint.
    
    Requires current password verification before allowing password change.
    Validates new password against Django's password validators.
    
    Fields:
        - old_password: Current password (required for verification)
        - new_password: New password (must pass validation)
        - new_password_confirm: New password confirmation (must match)
        
    Example:
        ```python
        data = {
            'old_password': 'CurrentPass123!',
            'new_password': 'NewSecurePass456!',
            'new_password_confirm': 'NewSecurePass456!'
        }
        serializer = ChangePasswordSerializer(data=data)
        if serializer.is_valid():
            user.set_password(serializer.validated_data['new_password'])
            user.save()
        ```
    """
    old_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        help_text="Current password for verification"
    )
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'},
        help_text="New password (min 8 characters, must include letters and numbers)"
    )
    new_password_confirm = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        help_text="New password confirmation (must match new_password)"
    )
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate that new passwords match.
        
        Args:
            attrs: Validated attribute dictionary
            
        Returns:
            Validated attributes
            
        Raises:
            serializers.ValidationError: If passwords don't match
        """
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                "new_password_confirm": "New password fields didn't match."
            })
        
        if attrs['old_password'] == attrs['new_password']:
            raise serializers.ValidationError({
                "new_password": "New password must be different from the old password."
            })
        
        return attrs


class EmailVerificationSerializer(serializers.Serializer):
    """
    Serializer for email verification process.

    Accepts the ``uid`` (base-64 encoded user pk) and ``token`` produced by
    ``EmailVerificationTokenGenerator``, matching the shape of the password-
    reset confirm flow so the frontend can use a consistent pattern.

    Fields:
        - uid:   Base-64 encoded user primary key.
        - token: Single-use verification token.

    Example:
        ```python
        data = {'uid': 'Mw', 'token': 'abc-xyz123'}
        serializer = EmailVerificationSerializer(data=data)
        if serializer.is_valid():
            # Decode uid, validate token, mark user verified
        ```
    """
    uid = serializers.CharField(
        required=True,
        help_text="Base-64 encoded user primary key"
    )
    token = serializers.CharField(
        required=True,
        help_text="Single-use email verification token"
    )


class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Serializer for initiating a password reset.

    Accepts an email address and returns it normalised.  The view is
    responsible for looking up the user and queuing the reset email.
    The response is always 200 regardless of whether the email is found
    (anti-enumeration).
    """
    email = serializers.EmailField(
        required=True,
        help_text="Email address associated with the account"
    )

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Serializer for confirming a password reset.

    Validates the uid/token pair produced by Django's built-in
    PasswordResetTokenGenerator and ensures the two password fields match
    and satisfy Django's password validators.
    """
    uid = serializers.CharField(required=True, help_text="Base-64 encoded user ID")
    token = serializers.CharField(required=True, help_text="Password reset token")
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        help_text="New password"
    )
    new_password_confirm = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        help_text="New password confirmation"
    )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {"new_password_confirm": "Password fields did not match."}
            )
        try:
            from django.contrib.auth.password_validation import validate_password as _vp
            _vp(attrs['new_password'])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})
        return attrs


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT token serializer with enhanced user data and claims.
    
    Extends SimpleJWT's TokenObtainPairSerializer to include additional
    user information in token claims and response payload.
    
    Additional Claims:
        - email: User's email address
        - username: User's username
        - email_verified: Email verification status
        - oauth_provider: OAuth provider (if applicable)
        
    Response Format:
        ```json
        {
            "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
            "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
            "user": {
                "id": 1,
                "email": "user@example.com",
                "username": "user",
                ...
            }
        }
        ```
    """
    
    @classmethod
    def get_token(cls, user: 'CommunityUser'):
        """
        Generate JWT token with custom claims.
        
        Args:
            user: User instance
            
        Returns:
            JWT token with custom claims
        """
        token = super().get_token(user)
        
        # Add custom claims
        token['email'] = user.email
        token['username'] = user.username
        token['email_verified'] = user.email_verified
        
        if user.oauth_provider:
            token['oauth_provider'] = user.oauth_provider
        
        return token
    
    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate credentials and return token with user data.
        
        Args:
            attrs: Credential attributes
            
        Returns:
            Token data with user information
        """
        data = super().validate(attrs)
        
        # Add user data to response using HATEOAS serializer
        request = self.context.get('request')
        data['user'] = UserSerializer(
            self.user,
            context={'request': request}
        ).data
        
        return data


class GoogleOAuthSerializer(serializers.Serializer):
    """
    Serializer for Google OAuth authentication initiation.
    
    Handles Google OAuth flow initiation by validating required parameters
    for the authorization request.
    
    Fields:
        - redirect_uri: OAuth callback URI (must match Google Console configuration)
        - state: CSRF protection state parameter (optional but recommended)
        
    Example:
        ```python
        data = {
            'redirect_uri': 'http://localhost:3000/auth/callback',
            'state': 'random_state_string_123'
        }
        serializer = GoogleOAuthSerializer(data=data)
        if serializer.is_valid():
            # Generate authorization URL
            auth_url = generate_google_auth_url(
                serializer.validated_data['redirect_uri']
            )
        ```
    """
    redirect_uri = serializers.URLField(
        required=True,
        help_text="OAuth callback URI (must match Google Console configuration)"
    )
    state = serializers.CharField(
        required=False,
        help_text="CSRF protection state parameter"
    )
    
    def validate_redirect_uri(self, value: str) -> str:
        """
        Validate redirect URI format and security.
        
        Args:
            value: Redirect URI
            
        Returns:
            Validated redirect URI
            
        Raises:
            serializers.ValidationError: If URI is invalid or insecure
        """
        # Ensure HTTPS in production
        if not value.startswith(('http://localhost', 'http://127.0.0.1', 'https://')):
            raise serializers.ValidationError(
                "Redirect URI must use HTTPS or be localhost for development."
            )
        
        return value


class GoogleOAuthCallbackSerializer(serializers.Serializer):
    """
    Serializer for Google OAuth callback handling.
    
    Processes the authorization code returned by Google and exchanges it
    for user information. Creates or updates user account with OAuth data.
    
    Fields:
        - code: Authorization code from Google
        - redirect_uri: OAuth callback URI (must match authorization request)
        - state: CSRF state parameter (must match authorization request)
        
    Process:
        1. Exchange authorization code for access token
        2. Fetch user information from Google
        3. Create or update user account
        4. Generate JWT tokens
        
    Example:
        ```python
        data = {
            'code': 'google_auth_code_123',
            'redirect_uri': 'http://localhost:3000/auth/callback',
            'state': 'random_state_string_123'
        }
        serializer = GoogleOAuthCallbackSerializer(data=data)
        if serializer.is_valid():
            user = serializer.create_or_update_user(serializer.validated_data)
        ```
    """
    code = serializers.CharField(
        required=True,
        help_text="Authorization code from Google OAuth callback"
    )
    redirect_uri = serializers.URLField(
        required=True,
        help_text="OAuth callback URI (must match authorization request)"
    )
    state = serializers.CharField(
        required=False,
        help_text="CSRF state parameter (must match authorization request)"
    )
    
    def validate_code(self, value: str) -> str:
        """
        Validate authorization code format.
        
        Args:
            value: Authorization code
            
        Returns:
            Validated code
            
        Raises:
            serializers.ValidationError: If code format is invalid
        """
        if not value or not value.strip():
            raise serializers.ValidationError(
                "Authorization code cannot be empty."
            )
        return value.strip()
    
    def create_or_update_user(
        self,
        validated_data: Dict[str, Any],
        google_user_info: Dict[str, Any]
    ) -> 'CommunityUser':
        """
        Create or update user from Google OAuth data.
        
        Args:
            validated_data: Validated callback data
            google_user_info: User information from Google
            
        Returns:
            User instance (created or updated)
            
        Raises:
            serializers.ValidationError: If user creation/update fails
        """
        email = google_user_info.get('email')
        google_id = google_user_info.get('sub') or google_user_info.get('id')  # Google's unique user ID
        
        if not email or not google_id:
            raise serializers.ValidationError(
                "Invalid Google user information: missing email or ID."
            )
        
        # Check if user exists with this email
        try:
            user = User.objects.get(email=email)
            
            # Update OAuth information if not set
            if not user.oauth_provider:
                user.oauth_provider = 'google'
                user.oauth_id = google_id
                user.email_verified = google_user_info.get('email_verified', False)
                user.email_verified_at = timezone.now() if user.email_verified else None
                user.save()
            
        except User.DoesNotExist:
            # Create new user from Google data
            user = User.objects.create_user(
                email=email,
                username=google_user_info.get('name', email.split('@')[0]),
                first_name=google_user_info.get('given_name', ''),
                last_name=google_user_info.get('family_name', ''),
                oauth_provider='google',
                oauth_id=google_id,
                email_verified=google_user_info.get('email_verified', False),
                email_verified_at=timezone.now() if google_user_info.get('email_verified') else None,
            )
            
            # Create profile with Google picture if available
            profile, created = Profile.objects.get_or_create(user=user)
            # Note: You might want to download and save the Google profile picture
            # picture_url = google_user_info.get('picture')
        
        return user
