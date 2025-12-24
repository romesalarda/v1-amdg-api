"""
Tests for the users app.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

User = get_user_model()


class CommunityUserModelTest(TestCase):
    """Test the custom user model."""
    
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
    
    def test_user_email_normalized(self):
        """Test that email is normalized."""
        email = 'test@EXAMPLE.COM'
        user = User.objects.create_user(email=email, password='test123')
        
        self.assertEqual(user.email, email.lower())
    
    def test_create_superuser(self):
        """Test creating a superuser."""
        user = User.objects.create_superuser(
            email='admin@example.com',
            password='admin123'
        )
        
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
    
    def test_email_required(self):
        """Test that email is required."""
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='test123')


class UserAPITest(APITestCase):
    """Test the user API endpoints."""
    
    def test_register_user(self):
        """Test user registration."""
        payload = {
            'email': 'test@example.com',
            'password': 'testpass123',
            'password_confirm': 'testpass123'
        }
        
        response = self.client.post('/api/auth/register/', payload)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['email'], payload['email'])
        
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
        
        response = self.client.post('/api/auth/register/', payload)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = self.client.get('/api/health/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('status', response.data)

