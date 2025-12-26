from django.db import models
from django.contrib.auth import get_user_model
from timezone_field import TimeZoneField

User = get_user_model()


class Profile(models.Model):
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_name = models.CharField(max_length=100, blank=True)
    profile_picture = models.ImageField(upload_to='profile-pictures/', blank=True, null=True)
    profile_picture_uploaded_at = models.DateTimeField(auto_now_add=True)
    # area_from
    contact_phone = models.CharField(max_length=20, blank=True)
    
    preferred_language = models.CharField(max_length=50, blank=True)
    timezone = TimeZoneField(default='Europe/London')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"

