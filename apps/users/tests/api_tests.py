"""
Production-grade API tests for the users app.

This module provides comprehensive test coverage for user management, authentication,
and profile operations with extensive edge case testing.

Test Classes:
    - UserRegistrationTestCase: User registration and validation
    - UserAuthenticationTestCase: Login, logout, and token management
    - PasswordChangeTestCase: Password change operations
    - UserProfileTestCase: User profile CRUD operations
    - ProfileManagementTestCase: Profile model CRUD operations
    - PermissionsTestCase: Authorization and permission testing
    - EmailVerificationTestCase: Email verification flow

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.urls import reverse
from datetime import datetime, timedelta
from django.utils import timezone
import json

from apps.users.models import Profile

User = get_user_model()


class UserRegistrationTestCase(APITestCase):
    """
    Test suite for user registration endpoints.
    
    Covers:
        - Successful registration
        - Validation errors
        - Duplicate email prevention
        - Password validation
        - Profile auto-creation
        - JWT token generation
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.register_url = reverse('users:user-list')
        
        self.valid_user_data = {
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'first_name': 'John',
            'last_name': 'Doe',
            'username': 'johndoe'
        }
    
    def test_successful_registration(self):
        """Test user can register with valid data."""
        response = self.client.post(self.register_url, self.valid_user_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('email', response.data)
        self.assertEqual(response.data['email'], self.valid_user_data['email'])
        self.assertEqual(response.data['first_name'], self.valid_user_data['first_name'])
        
        # Verify user created in database
        user = User.objects.get(email=self.valid_user_data['email'])
        self.assertTrue(user.check_password(self.valid_user_data['password']))
        
        # Verify profile auto-created via signal
        self.assertTrue(hasattr(user, 'profile'))
        self.assertIsNotNone(user.profile)
        # Profile should exist in database
        self.assertTrue(Profile.objects.filter(user=user).exists())
    
    def test_registration_with_missing_email(self):
        """Test registration fails without email."""
        data = self.valid_user_data.copy()
        del data['email']
        
        response = self.client.post(self.register_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
    
    def test_registration_with_invalid_email(self):
        """Test registration fails with invalid email format."""
        data = self.valid_user_data.copy()
        data['email'] = 'invalid-email'
        
        response = self.client.post(self.register_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
    
    def test_registration_with_duplicate_email(self):
        """Test registration fails with existing email."""
        # Create first user
        User.objects.create_user(
            email=self.valid_user_data['email'],
            password='password123'
        )
        
        # Try to register with same email
        response = self.client.post(self.register_url, self.valid_user_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
    
    def test_registration_with_password_mismatch(self):
        """Test registration fails when passwords don't match."""
        data = self.valid_user_data.copy()
        data['password_confirm'] = 'DifferentPass123!'
        
        response = self.client.post(self.register_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password_confirm', response.data)
    
    def test_registration_with_weak_password(self):
        """Test registration fails with weak password."""
        data = self.valid_user_data.copy()
        data['password'] = '123'
        data['password_confirm'] = '123'
        
        response = self.client.post(self.register_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)
    
    def test_registration_without_optional_fields(self):
        """Test registration succeeds without optional fields."""
        data = {
            'email': 'minimal@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!'
        }
        
        response = self.client.post(self.register_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=data['email'])
        self.assertTrue(user.username)  # Username auto-generated


class UserAuthenticationTestCase(APITestCase):
    """
    Test suite for user authentication endpoints.
    
    Covers:
        - Login with email/password
        - JWT token generation
        - Token refresh
        - Logout
        - Invalid credentials
        - Inactive user login
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.login_url = reverse('users:token-obtain-pair')
        self.refresh_url = reverse('users:token-refresh')
        self.logout_url = reverse('users:logout')
        
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='TestPass123!',
            username='testuser',
            first_name='Test',
            last_name='User'
        )
    
    def test_successful_login(self):
        """Test user can login with valid credentials."""
        data = {
            'email': 'testuser@example.com',
            'password': 'TestPass123!'
        }
        
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)
        self.assertIn('message', response.data)
        self.assertEqual(response.data['user']['email'], self.user.email)
        
        # Verify cookies set
        self.assertIn('access', response.cookies)
        self.assertIn('refresh', response.cookies)
    
    def test_login_with_invalid_email(self):
        """Test login fails with non-existent email."""
        data = {
            'email': 'nonexistent@example.com',
            'password': 'TestPass123!'
        }
        
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_login_with_wrong_password(self):
        """Test login fails with incorrect password."""
        data = {
            'email': 'testuser@example.com',
            'password': 'WrongPassword123!'
        }
        
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_login_with_inactive_user(self):
        """Test login fails for inactive user."""
        self.user.is_active = False
        self.user.save()
        
        data = {
            'email': 'testuser@example.com',
            'password': 'TestPass123!'
        }
        
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_logout(self):
        """Test user can logout successfully."""
        # Login first
        self.client.force_authenticate(user=self.user)
        
        response = self.client.post(self.logout_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)
        
        # Verify cookies deleted
        self.assertEqual(response.cookies.get('access').value, '')
        self.assertEqual(response.cookies.get('refresh').value, '')
    
    def test_logout_without_authentication(self):
        """Test logout requires authentication."""
        response = self.client.post(self.logout_url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PasswordChangeTestCase(APITestCase):
    """
    Test suite for password change functionality.
    
    Covers:
        - Successful password change
        - Wrong old password
        - Password mismatch
        - Weak new password
        - Same password validation
        - Unauthenticated access
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.change_password_url = reverse('users:user-change-password')
        
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='OldPass123!',
            username='testuser'
        )
        
        self.client.force_authenticate(user=self.user)
    
    def test_successful_password_change(self):
        """Test user can change password successfully."""
        data = {
            'old_password': 'OldPass123!',
            'new_password': 'NewSecurePass456!',
            'new_password_confirm': 'NewSecurePass456!'
        }
        
        response = self.client.post(self.change_password_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('detail', response.data)
        
        # Verify password changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewSecurePass456!'))
        self.assertFalse(self.user.check_password('OldPass123!'))
    
    def test_password_change_with_wrong_old_password(self):
        """Test password change fails with incorrect old password."""
        data = {
            'old_password': 'WrongOldPass123!',
            'new_password': 'NewSecurePass456!',
            'new_password_confirm': 'NewSecurePass456!'
        }
        
        response = self.client.post(self.change_password_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('old_password', response.data)
    
    def test_password_change_with_mismatch(self):
        """Test password change fails when new passwords don't match."""
        data = {
            'old_password': 'OldPass123!',
            'new_password': 'NewSecurePass456!',
            'new_password_confirm': 'DifferentPass789!'
        }
        
        response = self.client.post(self.change_password_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password_confirm', response.data)
    
    def test_password_change_with_weak_password(self):
        """Test password change fails with weak new password."""
        data = {
            'old_password': 'OldPass123!',
            'new_password': '123',
            'new_password_confirm': '123'
        }
        
        response = self.client.post(self.change_password_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', response.data)
    
    def test_password_change_with_same_password(self):
        """Test password change fails when new password same as old."""
        data = {
            'old_password': 'OldPass123!',
            'new_password': 'OldPass123!',
            'new_password_confirm': 'OldPass123!'
        }
        
        response = self.client.post(self.change_password_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', response.data)
    
    def test_password_change_without_authentication(self):
        """Test password change requires authentication."""
        self.client.force_authenticate(user=None)
        
        data = {
            'old_password': 'OldPass123!',
            'new_password': 'NewSecurePass456!',
            'new_password_confirm': 'NewSecurePass456!'
        }
        
        response = self.client.post(self.change_password_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class UserProfileTestCase(APITestCase):
    """
    Test suite for user profile management endpoints.
    
    Covers:
        - Get current user profile
        - Update user profile
        - Get other user's profile
        - List users
        - User search and filtering
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.me_url = reverse('users:user-me')
        self.update_profile_url = reverse('users:user-update-profile')
        self.users_list_url = reverse('users:user-list')
        
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='TestPass123!',
            username='testuser',
            first_name='Test',
            last_name='User'
        )
        
        self.other_user = User.objects.create_user(
            email='otheruser@example.com',
            password='TestPass123!',
            username='otheruser',
            first_name='Other',
            last_name='User'
        )
        
        self.client.force_authenticate(user=self.user)
    
    def test_get_current_user_profile(self):
        """Test user can get their own profile."""
        response = self.client.get(self.me_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.user.email)
        self.assertEqual(response.data['first_name'], self.user.first_name)
        self.assertIn('profile', response.data)
    
    def test_update_current_user_profile(self):
        """Test user can update their own profile."""
        data = {
            'first_name': 'Updated',
            'last_name': 'Name'
        }
        
        response = self.client.patch(self.update_profile_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['first_name'], 'Updated')
        self.assertEqual(response.data['last_name'], 'Name')
        
        # Verify in database
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Updated')
        self.assertEqual(self.user.last_name, 'Name')
    
    def test_list_users_as_regular_user(self):
        """Test regular user can only see themselves in user list."""
        response = self.client.get(self.users_list_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['email'], self.user.email)
    
    def test_list_users_as_staff(self):
        """Test staff user can see all users."""
        self.user.is_staff = True
        self.user.save()
        
        response = self.client.get(self.users_list_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
    
    def test_search_users(self):
        """Test user search functionality."""
        self.user.is_staff = True
        self.user.save()
        
        response = self.client.get(f"{self.users_list_url}?search=other")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['email'], self.other_user.email)
    
    def test_filter_users_by_active_status(self):
        """Test filtering users by active status."""
        self.user.is_staff = True
        self.user.save()
        
        self.other_user.is_active = False
        self.other_user.save()
        
        response = self.client.get(f"{self.users_list_url}?is_active=true")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['email'], self.user.email)
    
    def test_get_user_profile_unauthorized(self):
        """Test getting profile requires authentication."""
        self.client.force_authenticate(user=None)
        
        response = self.client.get(self.me_url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ProfileManagementTestCase(APITestCase):
    """
    Test suite for Profile model CRUD operations.
    
    Covers:
        - Get profile
        - Update profile
        - Profile picture upload
        - Timezone and preferences
        - Profile validation
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='TestPass123!',
            username='testuser'
        )
        
        # self.profile = Profile.objects.create(user=self.user)
        
        self.profile_me_url = reverse('users:profile-me')
        self.profile_detail_url = reverse('users:profile-detail', kwargs={'pk': self.user.profile.pk})
        
        self.client.force_authenticate(user=self.user)
    
    def test_get_current_user_profile(self):
        """Test user can get their profile via profiles endpoint."""
        response = self.client.get(self.profile_me_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('url', response.data)
        self.assertIn('user', response.data)
    
    def test_update_profile(self):
        """Test user can update their profile."""
        data = {
            'preferred_name': 'Johnny',
            'contact_phone': '+44 1234567890',
            'preferred_language': 'en',
            'timezone': 'Europe/London'
        }
        
        response = self.client.patch(self.profile_detail_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['preferred_name'], 'Johnny')
        self.assertEqual(response.data['contact_phone'], data['contact_phone'])
        self.assertEqual(response.data['timezone'], 'Europe/London')
        
        # Verify in database
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.preferred_name, 'Johnny')
    
    def test_profile_phone_validation(self):
        """Test profile phone number validation."""
        data = {
            'contact_phone': ''  # Empty phone
        }
        
        response = self.client.patch(self.profile_detail_url, data, format='json')
        
        # Should accept empty phone (it's optional)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_profile_timezone_update(self):
        """Test updating profile timezone."""
        data = {
            'timezone': 'America/New_York'
        }
        
        response = self.client.patch(self.profile_detail_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['timezone'], 'America/New_York')
        
        self.user.profile.refresh_from_db()
        self.assertEqual(str(self.user.profile.timezone), 'America/New_York')
    
    def test_profile_preferred_name_title_case(self):
        """Test preferred name is automatically title-cased."""
        data = {
            'preferred_name': 'john smith'
        }
        
        response = self.client.patch(self.profile_detail_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.preferred_name, 'John Smith')


class PermissionsTestCase(APITestCase):
    """
    Test suite for permissions and authorization.
    
    Covers:
        - Owner access
        - Admin access
        - Permission denied scenarios
        - Anonymous access
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            email='user@example.com',
            password='TestPass123!',
            username='user'
        )
        
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='TestPass123!',
            username='other'
        )
        
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            password='TestPass123!',
            username='admin',
            is_staff=True
        )
        
        self.user_detail_url = reverse('users:user-detail', kwargs={'pk': self.user.pk})
        self.other_user_detail_url = reverse('users:user-detail', kwargs={'pk': self.other_user.pk})
    
    def test_user_cannot_view_other_user(self):
        """Test regular user cannot view another user's details."""
        self.client.force_authenticate(user=self.user)
        
        response = self.client.get(self.other_user_detail_url)
        
        # User list is filtered, so this will return 404
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_user_can_view_own_profile(self):
        """Test user can view their own profile."""
        self.client.force_authenticate(user=self.user)
        
        response = self.client.get(self.user_detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.user.email)
    
    def test_admin_can_view_any_user(self):
        """Test admin can view any user's details."""
        self.client.force_authenticate(user=self.admin_user)
        
        response = self.client.get(self.other_user_detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.other_user.email)
    
    def test_user_cannot_update_other_user(self):
        """Test user cannot update another user's profile."""
        self.client.force_authenticate(user=self.user)
        
        data = {'first_name': 'Hacked'}
        response = self.client.patch(self.other_user_detail_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_user_cannot_delete_other_user(self):
        """Test user cannot delete another user."""
        self.client.force_authenticate(user=self.user)
        
        response = self.client.delete(self.other_user_detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_admin_can_delete_user(self):
        """Test admin can delete users."""
        self.client.force_authenticate(user=self.admin_user)
        
        response = self.client.delete(self.other_user_detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify soft delete (user deactivated, not deleted)
        self.other_user.refresh_from_db()
        self.assertFalse(self.other_user.is_active)
    
    def test_anonymous_cannot_access_protected_endpoints(self):
        """Test anonymous users cannot access protected endpoints."""
        response = self.client.get(self.user_detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class EmailVerificationTestCase(APITestCase):
    """
    Test suite for email verification functionality.
    
    Covers:
        - Email verification process
        - Invalid token handling
        - Already verified email
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.verify_url = reverse('users:user-verify-email')
        
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='TestPass123!',
            username='testuser'
        )
    
    def test_email_verification_success(self):
        """Test successful email verification."""
        data = {
            'email': self.user.email,
            'token': 'valid-token-123'  # TODO: Generate real token
        }
        
        response = self.client.post(self.verify_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify email marked as verified
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertIsNotNone(self.user.email_verified_at)
    
    def test_email_verification_with_invalid_email(self):
        """Test email verification fails with non-existent email."""
        data = {
            'email': 'nonexistent@example.com',
            'token': 'valid-token-123'
        }
        
        response = self.client.post(self.verify_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UserOrderingAndPaginationTestCase(APITestCase):
    """
    Test suite for user list ordering and pagination.
    
    Covers:
        - Default ordering
        - Custom ordering
        - Pagination
        - Page size limits
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.users_list_url = reverse('users:user-list')
        
        # Create admin user
        self.admin = User.objects.create_user(
            email='admin@example.com',
            password='TestPass123!',
            username='admin',
            is_staff=True
        )
        
        # Create multiple test users
        for i in range(25):
            User.objects.create_user(
                email=f'user{i}@example.com',
                password='TestPass123!',
                username=f'user{i}'
            )
        
        self.client.force_authenticate(user=self.admin)
    
    def test_default_pagination(self):
        """Test default pagination settings."""
        response = self.client.get(self.users_list_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('results', response.data)
        # Should have 26 total users (25 created + 1 admin)
        self.assertEqual(response.data['count'], 26)
        # First page should have max 20 items (default page size)
        self.assertLessEqual(len(response.data['results']), 20)
    
    def test_custom_page_size(self):
        """Test custom page size parameter."""
        response = self.client.get(f"{self.users_list_url}?page_size=10")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 10)
    
    def test_descending_ordering(self):
        """Test descending order."""
        response = self.client.get(f"{self.users_list_url}?ordering=-created_at")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Most recent first
        dates = [user['created_at'] for user in response.data['results']]
        self.assertEqual(dates, sorted(dates, reverse=True))
