from django.db import models
from django.contrib.auth import get_user_model
from timezone_field import TimeZoneField

from django.utils.translation import gettext_lazy as _

from core.utils.validators import PhoneNumberValidator
User = get_user_model()


class Profile(models.Model):
    '''
    Model representing a user's profile.
    '''
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_name = models.CharField(max_length=100, blank=True)
    profile_picture = models.ImageField(upload_to='profile-pictures/', blank=True, null=True)
    profile_picture_uploaded_at = models.DateTimeField(auto_now_add=True)
    area_from = models.ForeignKey(
        "locations.AreaLocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='residents',
        verbose_name=_("Area From"),
        help_text=_("The area where the user is from.")
    )
    contact_phone = models.CharField(max_length=20, blank=True, validators=[PhoneNumberValidator()])
    
    preferred_language = models.CharField(max_length=50, blank=True)
    timezone = TimeZoneField(default='Europe/London')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"

    def __repr__(self):
        return f"<Profile(user={self.user.username}, preferred_name={self.preferred_name})>"
    
    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"
        ordering = ['-created_at']

    @property
    def full_name(self):
        return f"{self.user.first_name} {self.user.last_name}".strip()
    
    def save(self, *args, **kwargs):
        self.full_clean()
        self.preferred_name = self.preferred_name.title()
        super().save(*args, **kwargs)

