"""
Tests for the users app.

This test suite covers:
1. CommunityUser model creation and authentication
2. Profile model creation and management
3. User signup workflow
4. Email verification
5. OAuth integration fields
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status

from apps.users.models import Profile
from apps.locations.models import (
    AreaLocation, CountryLocation, ClusterLocation, 
    ChapterLocation, GeneralSectorType, SpecificSectorType
)

User = get_user_model()


class CommunityUserModelTest(TestCase):
    """Test cases for the CommunityUser model."""
    
    def test_create_user_with_email(self):
        """Test creating a user with email is successful."""
        email = 'test@example.com'
        password = 'testpass123'
        user = User.objects.create_user(
            email=email,
            password=password
        )
        
        self.assertEqual(user.email, email)
        self.assertTrue(user.check_password(password))
        self.assertTrue(user.username)  # Auto-generated from email
        self.assertIsNotNone(user.created_at)
        self.assertFalse(user.email_verified)
    
    def test_user_email_normalized(self):
        """Test that email is normalized to lowercase."""
        email = 'test@EXAMPLE.COM'
        user = User.objects.create_user(email=email, password='test123')
        
        self.assertEqual(user.email, email.lower())
    
    def test_username_auto_generated_from_email(self):
        """Test that username is auto-generated from email if not provided."""
        email = 'john.doe@example.com'
        user = User.objects.create_user(email=email, password='test123')
        
        self.assertEqual(user.username, 'john.doe')
    
    def test_create_user_with_custom_username(self):
        """Test creating a user with a custom username."""
        email = 'test@example.com'
        username = 'cooluser123'
        user = User.objects.create_user(
            email=email,
            password='test123',
            username=username
        )
        
        self.assertEqual(user.username, username)
    
    def test_create_user_with_full_name(self):
        """Test creating a user with first and last name."""
        user = User.objects.create_user(
            email='john@example.com',
            password='test123',
            first_name='John',
            last_name='Smith'
        )
        
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Smith')
        self.assertEqual(user.get_full_name(), 'John Smith')
    
    def test_user_str_representation(self):
        """Test string representation of user."""
        user = User.objects.create_user(
            email='test@example.com',
            password='test123'
        )
        
        self.assertEqual(str(user), 'test@example.com')
    
    def test_get_display_name_with_full_name(self):
        """Test get_display_name returns full name when available."""
        user = User.objects.create_user(
            email='john@example.com',
            password='test123',
            first_name='John',
            last_name='Doe'
        )
        
        self.assertEqual(user.get_display_name(), 'John Doe')
    
    def test_get_display_name_with_username_only(self):
        """Test get_display_name returns username when no full name."""
        user = User.objects.create_user(
            email='john@example.com',
            password='test123',
            username='johndoe'
        )
        
        self.assertEqual(user.get_display_name(), 'johndoe')
    
    def test_get_display_name_fallback_to_email(self):
        """Test get_display_name falls back to email prefix when no name or username."""
        user = User.objects.create_user(
            email='john.smith@example.com',
            password='test123'
        )
        user.username = ''
        user.first_name = ''
        user.last_name = ''
        
        self.assertEqual(user.get_display_name(), 'john.smith')
    
    def test_create_superuser(self):
        """Test creating a superuser."""
        user = User.objects.create_superuser(
            email='admin@example.com',
            password='admin123'
        )
        
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_active)
    
    def test_email_required(self):
        """Test that email is required."""
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='test123')
    
    def test_email_unique(self):
        """Test that email must be unique."""
        User.objects.create_user(email='test@example.com', password='test123')
        
        with self.assertRaises(Exception):  # IntegrityError
            User.objects.create_user(email='test@example.com', password='test456')
    
    def test_email_verification_fields(self):
        """Test email verification fields."""
        user = User.objects.create_user(
            email='verify@example.com',
            password='test123'
        )
        
        self.assertFalse(user.email_verified)
        self.assertIsNone(user.email_verified_at)
        
        # Simulate email verification
        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.save()
        
        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)
    
    def test_oauth_fields(self):
        """Test OAuth provider fields."""
        user = User.objects.create_user(
            email='oauth@example.com',
            password='test123',
            oauth_provider='google',
            oauth_id='1234567890'
        )
        
        self.assertEqual(user.oauth_provider, 'google')
        self.assertEqual(user.oauth_id, '1234567890')
    
    def test_oauth_provider_choices(self):
        """Test OAuth provider choices are valid."""
        user = User.objects.create_user(
            email='google@example.com',
            password='test123',
            oauth_provider='google'
        )
        self.assertEqual(user.oauth_provider, 'google')
        
        user2 = User.objects.create_user(
            email='github@example.com',
            password='test123',
            oauth_provider='github'
        )
        self.assertEqual(user2.oauth_provider, 'github')
    
    def test_user_timestamps(self):
        """Test that created_at and updated_at are set correctly."""
        user = User.objects.create_user(
            email='timestamp@example.com',
            password='test123'
        )
        
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)
        
        created_at = user.created_at
        
        # Update user
        user.first_name = 'Updated'
        user.save()
        
        self.assertEqual(user.created_at, created_at)  # created_at doesn't change
        self.assertGreaterEqual(user.updated_at, created_at)  # updated_at changes


class ProfileModelTest(TestCase):
    """Test cases for the Profile model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='profile@example.com',
            password='test123',
            first_name='John',
            last_name='Doe'
        )
        
        # Create location hierarchy
        self.country = CountryLocation.objects.create(
            country='UK',
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE
        )
        
        self.cluster = ClusterLocation.objects.create(
            cluster_name='Test Cluster',
            country=self.country
        )
        
        self.chapter = ChapterLocation.objects.create(
            chapter_name='Test Chapter',
            cluster=self.cluster
        )
        
        self.area = AreaLocation.objects.create(
            area_name='Test Area',
            area_code='TA',
            chapter=self.chapter
        )
    
    def test_create_profile(self):
        """Test creating a basic profile."""
        # Profile is auto-created by signal, update it
        profile = self.user.profile
        profile.preferred_name = 'Johnny'
        profile.contact_phone = '+447123456789'
        profile.save()
        
        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.preferred_name, 'Johnny')
        self.assertEqual(profile.contact_phone, '+447123456789')
        self.assertIsNotNone(profile.created_at)
    
    def test_profile_one_to_one_with_user(self):
        """Test that profile has one-to-one relationship with user."""
        # Profile is auto-created by signal
        profile = self.user.profile
        profile.preferred_name = 'John'
        profile.save()
        
        # Verify profile exists and is linked to user
        self.assertEqual(profile.user, self.user)
        
        # Try to create another profile for same user should fail
        with self.assertRaises(Exception):  # IntegrityError
            Profile.objects.create(
                user=self.user,
                preferred_name='Johnny'
            )
    
    def test_profile_str_representation(self):
        """Test string representation of profile."""
        profile = self.user.profile
        profile.preferred_name = 'Johnny'
        profile.save()
        
        self.assertIn(self.user.username, str(profile))
        self.assertIn('Profile', str(profile))
    
    def test_profile_full_name_property(self):
        """Test full_name property."""
        profile = self.user.profile
        profile.preferred_name = 'Johnny'
        profile.save()
        
        self.assertEqual(profile.full_name, 'John Doe')
    
    def test_profile_full_name_empty(self):
        """Test full_name property when user has no names."""
        user = User.objects.create_user(
            email='noname@example.com',
            password='test123'
        )
        profile = user.profile
        
        self.assertEqual(profile.full_name, '')
    
    def test_profile_with_area_from(self):
        """Test profile with area_from location."""
        profile = self.user.profile
        profile.area_from = self.area
        profile.save()
        
        self.assertEqual(profile.area_from, self.area)
        self.assertEqual(profile.area_from.area_name, 'Test Area')
    
    def test_profile_preferred_name_title_cased(self):
        """Test that preferred_name is title-cased on save."""
        profile = self.user.profile
        profile.preferred_name = 'johnny boy'
        profile.save()
        
        self.assertEqual(profile.preferred_name, 'Johnny Boy')
    
    def test_profile_preferred_language(self):
        """Test setting preferred language."""
        profile = self.user.profile
        profile.preferred_language = 'Spanish'
        profile.save()
        
        self.assertEqual(profile.preferred_language, 'Spanish')
    
    def test_profile_timezone_default(self):
        """Test default timezone."""
        profile = self.user.profile
        
        self.assertEqual(str(profile.timezone), 'Europe/London')
    
    def test_profile_timezone_custom(self):
        """Test setting custom timezone."""
        profile = self.user.profile
        profile.timezone = 'America/New_York'
        profile.save()
        
        self.assertEqual(str(profile.timezone), 'America/New_York')
    
    def test_profile_contact_phone_validation(self):
        """Test phone number validation."""
        # Valid phone number
        profile = self.user.profile
        profile.contact_phone = '+447123456789'
        profile.save()
        self.assertEqual(profile.contact_phone, '+447123456789')
    
    def test_profile_timestamps(self):
        """Test created_at and updated_at timestamps."""
        profile = self.user.profile
        profile.preferred_name = 'John'
        profile.save()
        
        created_at = profile.created_at
        self.assertIsNotNone(created_at)
        
        # Update profile
        profile.preferred_name = 'Johnny'
        profile.save()
        
        self.assertEqual(profile.created_at, created_at)
        self.assertGreaterEqual(profile.updated_at, created_at)
    
    def test_profile_picture_field(self):
        """Test profile picture field exists and is optional."""
        profile = self.user.profile
        
        self.assertFalse(profile.profile_picture)
        self.assertIsNotNone(profile.profile_picture_uploaded_at)


class UserSignupWorkflowTest(TestCase):
    """Test the complete user signup workflow."""
    
    def setUp(self):
        """Set up test data for signup workflow."""
        # Create location for profile
        self.country = CountryLocation.objects.create(
            country='UK',
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE
        )
        
        self.cluster = ClusterLocation.objects.create(
            cluster_name='London Cluster',
            country=self.country
        )
        
        self.chapter = ChapterLocation.objects.create(
            chapter_name='Central London',
            cluster=self.cluster
        )
        
        self.area = AreaLocation.objects.create(
            area_name='Westminster',
            area_code='WM',
            chapter=self.chapter
        )
    
    def test_complete_signup_workflow_minimal(self):
        """Test minimal signup workflow: user creation only."""
        # Step 1: User signs up with email and password
        user = User.objects.create_user(
            email='newuser@example.com',
            password='securepass123'
        )
        
        # Verify user was created
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertTrue(user.check_password('securepass123'))
        self.assertFalse(user.email_verified)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertIsNotNone(user.username)
    
    def test_complete_signup_workflow_with_profile(self):
        """Test complete signup workflow: user + profile creation."""
        # Step 1: User signs up with full details
        user = User.objects.create_user(
            email='mary.johnson@example.com',
            password='securepass123',
            first_name='Mary',
            last_name='Johnson'
        )
        
        # Step 2: Profile is auto-created by signal, now update it
        profile = user.profile
        profile.preferred_name = 'Mary'
        profile.area_from = self.area
        profile.contact_phone = '+447123456789'
        profile.preferred_language = 'English'
        profile.timezone = 'Europe/London'
        profile.save()
        
        # Verify user and profile are linked
        self.assertEqual(user.profile, profile)
        self.assertEqual(profile.user, user)
        self.assertEqual(profile.area_from, self.area)
        
        # Verify user display name
        self.assertEqual(user.get_display_name(), 'Mary Johnson')
        self.assertEqual(profile.full_name, 'Mary Johnson')
    
    def test_signup_workflow_email_verification(self):
        """Test signup workflow with email verification."""
        # Step 1: User signs up
        user = User.objects.create_user(
            email='verify@example.com',
            password='test123',
            first_name='Test',
            last_name='User'
        )
        
        self.assertFalse(user.email_verified)
        self.assertIsNone(user.email_verified_at)
        
        # Step 2: Simulate email verification (normally done via token)
        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.save()
        
        # Verify email is verified
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)
    
    def test_signup_workflow_with_oauth(self):
        """Test signup workflow using OAuth (Google)."""
        # Simulate OAuth signup
        user = User.objects.create_user(
            email='googleuser@gmail.com',
            password='',  # OAuth users don't have password
            first_name='Google',
            last_name='User',
            oauth_provider='google',
            oauth_id='google_123456789',
            email_verified=True,  # OAuth providers verify emails
            email_verified_at=timezone.now()
        )
        
        # Verify OAuth fields
        self.assertEqual(user.oauth_provider, 'google')
        self.assertEqual(user.oauth_id, 'google_123456789')
        self.assertTrue(user.email_verified)
        
        # Update auto-created profile
        profile = user.profile
        profile.preferred_name = 'Google User'
        profile.timezone = 'America/New_York'
        profile.save()
        
        self.assertEqual(user.profile, profile)
        self.assertEqual(profile.preferred_name, 'Google User')
    
    def test_signup_workflow_username_generation(self):
        """Test that username is generated correctly during signup."""
        # User with simple email
        user1 = User.objects.create_user(
            email='john@example.com',
            password='test123'
        )
        self.assertEqual(user1.username, 'john')
        
        # User with complex email
        user2 = User.objects.create_user(
            email='john.doe.smith@example.com',
            password='test123'
        )
        self.assertEqual(user2.username, 'john.doe.smith')
        
        # User with custom username
        user3 = User.objects.create_user(
            email='jane@example.com',
            password='test123',
            username='janedoe123'
        )
        self.assertEqual(user3.username, 'janedoe123')
    
    def test_signup_workflow_profile_optional_fields(self):
        """Test signup with optional profile fields."""
        # Create user
        user = User.objects.create_user(
            email='optional@example.com',
            password='test123',
            first_name='Optional',
            last_name='Fields'
        )
        
        # Update auto-created profile with all optional fields
        profile = user.profile
        profile.preferred_name = 'Opt'
        profile.area_from = self.area
        profile.contact_phone = '+447987654321'
        profile.preferred_language = 'French'
        profile.timezone = 'Europe/Paris'
        profile.save()
        
        # Verify all fields
        self.assertEqual(profile.preferred_name, 'Opt')
        self.assertEqual(profile.area_from.area_name, 'Westminster')
        self.assertEqual(profile.contact_phone, '+447987654321')
        self.assertEqual(profile.preferred_language, 'French')
        self.assertEqual(str(profile.timezone), 'Europe/Paris')
    
    def test_signup_workflow_without_optional_profile_fields(self):
        """Test signup with minimal profile (only required fields)."""
        # Create user
        user = User.objects.create_user(
            email='minimal@example.com',
            password='test123'
        )
        
        # Get auto-created profile (no updates needed)
        profile = user.profile
        
        # Verify defaults
        self.assertEqual(profile.preferred_name, '')
        self.assertIsNone(profile.area_from)
        self.assertEqual(profile.contact_phone, '')
        self.assertEqual(profile.preferred_language, '')
        self.assertEqual(str(profile.timezone), 'Europe/London')  # Default
    
    def test_multiple_users_signup(self):
        """Test multiple users signing up independently."""
        # User 1
        user1 = User.objects.create_user(
            email='user1@example.com',
            password='pass1',
            first_name='User',
            last_name='One'
        )
        profile1 = user1.profile
        profile1.preferred_name = 'User 1'
        profile1.save()
        
        # User 2
        user2 = User.objects.create_user(
            email='user2@example.com',
            password='pass2',
            first_name='User',
            last_name='Two'
        )
        profile2 = user2.profile
        profile2.preferred_name = 'User 2'
        profile2.save()
        
        # User 3
        user3 = User.objects.create_user(
            email='user3@example.com',
            password='pass3',
            first_name='User',
            last_name='Three'
        )
        profile3 = user3.profile
        profile3.preferred_name = 'User 3'
        profile3.save()
        
        # Verify all users and profiles exist independently
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(Profile.objects.count(), 3)
        
        self.assertEqual(user1.profile, profile1)
        self.assertEqual(user2.profile, profile2)
        self.assertEqual(user3.profile, profile3)


class UserAPITest(APITestCase):
    """Test the user API endpoints."""
    
    def test_register_user(self):
        """Test user registration."""
        payload = {
            'email': 'test@example.com',
            'password': 'testpass123',
            'password_confirm': 'testpass123'
        }
        
        response = self.client.post('/api/users/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['email'], payload['email'])
        
        # Check user was created
        user = User.objects.get(email=payload['email'])
        self.assertTrue(user.check_password(payload['password']))
    
    def test_register_user_password_mismatch(self):
        """Test registration fails with password mismatch."""
        payload = {
            'email': 'test@example.com',
            'password': 'testpass123',
            'password_confirm': 'wrongpass'
        }
        
        response = self.client.post('/api/users/', payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = self.client.get('/api/health/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('status', response.data)

