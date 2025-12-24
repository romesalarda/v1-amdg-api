from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import EmailValidator

from core.utils.validators import PhoneNumberValidator

User = get_user_model()

class Organisation(models.Model):
    
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    landing_image = models.ImageField(upload_to='organisation/landing-images/', blank=True, null=True)
    landing_image_uploaded_at = models.DateTimeField(auto_now_add=True)
    
    logo = models.ImageField(upload_to='organisation/logos/', blank=True, null=True)
    logo_uploaded_at = models.DateTimeField(auto_now_add=True)
    
    external_website = models.URLField(blank=True, null=True)
    
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='organisations_created')

    def __str__(self):
        return self.title
    
class OrganisationContact(models.Model):
    
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=255)
    email = models.EmailField(validators=[EmailValidator()])
    phone = models.CharField(max_length=20, blank=True, validators=[PhoneNumberValidator()])
    label = models.CharField(max_length=100, blank=True)
    
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.organisation.title})"

class OrganisationControl(models.Model):
    
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='controllers')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organisations_controlled')
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='organisation_controls_added')
    
    class Meta:
        unique_together = ('organisation', 'user')
    
    def __str__(self):
        return f"{self.user.username} controls {self.organisation.title}"

    
