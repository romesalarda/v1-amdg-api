"""
Custom User Model for AMDG Platform

This model uses email as the primary authentication field while keeping username
as a display field. Compatible with future Google OAuth integration.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class CommunityUserManager(BaseUserManager):
    """Custom user manager where email is the unique identifier for authentication."""

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular user with the given email and password."""
        if not email:
            raise ValueError(_('The Email field must be set'))
        email = self.normalize_email(email)
        
        # Generate a username from email if not provided
        if 'username' not in extra_fields or not extra_fields['username']:
            extra_fields['username'] = email.split('@')[0]
        
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser with the given email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self.create_user(email, password, **extra_fields)


class CommunityUser(AbstractUser):
    """
    Custom User Model with email-based authentication.
    
    - Email is the primary authentication field (LOGIN)
    - Username is kept for display purposes
    - Compatible with Google OAuth (can store OAuth provider info)
    """
    
    # Override email to make it unique and required
    email = models.EmailField(
        _('email address'),
        unique=True,
        error_messages={
            'unique': _("A user with that email already exists."),
        },
    )
    
    # Username is optional display field (not used for login)
    username = models.CharField(
        _('username'),
        max_length=150,
        unique=False,  # Not unique since we use email for login
        blank=True,
        help_text=_('Display name. Can be changed by the user.'),
    )
        
    # OAuth fields (for future Google OAuth integration)
    oauth_provider = models.CharField(
        _('OAuth provider'),
        max_length=50,
        blank=True,
        choices=[
            ('google', 'Google'),
            ('github', 'GitHub'),
            ('', 'None'),
        ],
        help_text=_('OAuth provider used for authentication (if any)'),
    )
    oauth_id = models.CharField(
        _('OAuth ID'),
        max_length=255,
        blank=True,
        help_text=_('Unique ID from OAuth provider'),
    )
    
    # Timestamps
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    
    # Email verification
    email_verified = models.BooleanField(_('email verified'), default=False)
    email_verified_at = models.DateTimeField(_('email verified at'), null=True, blank=True)
    
    objects = CommunityUserManager()
    
    # Use email for authentication instead of username
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # Email is already required, no need to add it here
    
    class Meta:
        verbose_name = _('community user')
        verbose_name_plural = _('community users')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['oauth_provider', 'oauth_id']),
        ]
    
    def __str__(self):
        return self.email
    
    def get_display_name(self):
        """Return the best display name for the user."""
        if self.get_full_name():
            return self.get_full_name()
        elif self.username:
            return self.username
        return self.email.split('@')[0]
    
    def save(self, *args, **kwargs):
        """Override save to generate username from email if not provided."""
        if not self.username:
            self.username = self.email.split('@')[0]
        super().save(*args, **kwargs)

    def profile_picture_url(self):
        """Return the URL of the user's profile picture if available."""
        # Placeholder for future profile picture URL logic
        return self.profile.profile_picture.url if hasattr(self, 'profile') and self.profile.profile_picture else None
    
    @property
    def is_verified(self):
        """Check if the user's email is verified."""
        return self.email_verified
    
    @property
    def is_oauth_user(self):
        """Check if the user logged in via OAuth."""
        return bool(self.oauth_provider and self.oauth_id)