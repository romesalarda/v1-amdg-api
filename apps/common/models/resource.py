from django.db import models
from django.contrib.auth import get_user_model

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

User = get_user_model()

class ResourceTypeChoices(models.TextChoices):
    DOCUMENT = 'DOCUMENT', 'Document'
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'
    AUDIO = 'AUDIO', 'Audio'
    LINK = 'LINK', 'Link'
    OTHER = 'OTHER', 'Other'

class Resource(models.Model):
    '''
    Abstract base model for resources.
    '''
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_id = models.PositiveIntegerField()
    target = GenericForeignKey('target_type', 'target_id')
    
    public = models.BooleanField(default=True)
    
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceTypeChoices.choices,
        default=ResourceTypeChoices.DOCUMENT
    )
    
    file = models.FileField(upload_to='resources/files/', blank=True, null=True)
    link = models.URLField(blank=True, null=True)
    image = models.ImageField(upload_to='resources/images/', blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='resources_added')
    
    class Meta:
        indexes = [
            models.Index(fields=['target_type', 'target_id']),
            models.Index(fields=['resource_type']),
        ]
    
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<Resource {self.name} (ID: {self.id})>"
    
    def get_resource(self):
        '''
        Returns the actual resource (file, link, image) based on resource_type.
        '''
        if self.resource_type == ResourceTypeChoices.DOCUMENT or self.resource_type == ResourceTypeChoices.OTHER:
            return self.file
        elif self.resource_type == ResourceTypeChoices.LINK:
            return self.link
        elif self.resource_type == ResourceTypeChoices.IMAGE:
            return self.image
        else:
            return None