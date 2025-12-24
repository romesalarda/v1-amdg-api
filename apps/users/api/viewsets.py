"""
ViewSets for the users app.

These viewsets handle user authentication, registration, and profile management.
"""
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings

from .serializers import (
    UserSerializer,
    UserRegistrationSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
)

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for user management.
    
    Provides CRUD operations for users with proper authentication.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        """Return appropriate serializer class based on action."""
        if self.action == 'create':
            return UserRegistrationSerializer
        elif self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserSerializer
    
    def get_permissions(self):
        """Allow anyone to create a user (registration)."""
        if self.action == 'create':
            return [permissions.AllowAny()]
        return super().get_permissions()
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        """Get current user's profile."""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['patch'], permission_classes=[permissions.IsAuthenticated])
    def update_profile(self, request):
        """Update current user's profile."""
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def change_password(self, request):
        """Change current user's password."""
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        
        # Check old password
        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {'old_password': 'Wrong password.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Set new password
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        return Response({'detail': 'Password updated successfully.'})
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def register(self, request):
        """Register a new user."""
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        response = Response({
            'user': UserSerializer(user).data,
            'message': 'User registered successfully.'
        }, status=status.HTTP_201_CREATED)
        
        # Set HTTP-only cookies for tokens
        response.set_cookie(
            key='refresh',
            value=str(refresh),
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            max_age=60 * 60 * 24 * 7  # 7 days
        )
        response.set_cookie(
            key='access',
            value=str(refresh.access_token),
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            max_age=60 * 15  # 15 minutes
        )
        
        return response


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom JWT token view that sets HTTP-only cookies."""
    serializer_class = CustomTokenObtainPairSerializer
    
    def post(self, request, *args, **kwargs):
        """Override to set HTTP-only cookies."""
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            # Set HTTP-only cookies
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


class CustomTokenRefreshView(TokenRefreshView):
    """Custom token refresh view that uses HTTP-only cookies."""
    
    def post(self, request, *args, **kwargs):
        """Override to use refresh token from cookie."""
        refresh_token = request.COOKIES.get('refresh')
        
        if not refresh_token:
            return Response(
                {'detail': 'Refresh token not found.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
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


@action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
def logout(request):
    """Logout user by clearing cookies."""
    response = Response({'message': 'Logout successful.'})
    response.delete_cookie('access')
    response.delete_cookie('refresh')
    return response
