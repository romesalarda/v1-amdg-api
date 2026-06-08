from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from imagekit.models import ImageSpecField
from apps.common.services.image_specs import ThumbnailSpec, MediumSpec, LargeSpec
from PIL import Image as PilImage

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
    EXCLUDE_TAGS = ['QUESTION_UPLOAD']  # Tags that should be excluded from certain queries, e.g., when fetching resources for frontend display.
    TYPE_CHOICES = ResourceTypeChoices

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    # db fields for generic relation
    tag = models.CharField(max_length=50, blank=True, 
                           null=True, help_text=_("Tag for categorizing the resource, e.g., LANDING_PHOTO, SCHEDULE_PDF, SPEAKER_BIO, etc. Database only.")
                           ) # LANDING_PHOTO, SCHEDULE_PDF, SPEAKER_BIO, etc. db only
    target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_id = models.CharField(max_length=255)
    target = GenericForeignKey('target_type', 'target_id')
    
    public = models.BooleanField(default=True)
    
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceTypeChoices.choices,
        default=ResourceTypeChoices.DOCUMENT
    )
    
    file = models.FileField(upload_to='resources/files/', blank=True, null=True, max_length=500)
    link = models.URLField(blank=True, null=True, max_length=500)
    image = models.ImageField(upload_to='resources/images/', blank=True, null=True, max_length=500)

    # Image dimensions — populated automatically on save via Pillow.
    # Null for non-image resources or pre-existing records not yet backfilled.
    image_width = models.PositiveIntegerField(blank=True, null=True)
    image_height = models.PositiveIntegerField(blank=True, null=True)

    # Lazy image variants — virtual fields (no DB columns).
    # Generated on first .url access and cached in storage.
    # Only valid when resource_type == IMAGE and image is set.
    image_thumbnail = ImageSpecField(source='image', spec=ThumbnailSpec)
    image_medium = ImageSpecField(source='image', spec=MediumSpec)
    image_large = ImageSpecField(source='image', spec=LargeSpec)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='resources_added')
    
    expires_at = models.DateTimeField(blank=True, null=True, help_text=_("Optional expiration date for the resource. If set, the resource will be considered expired after this date."))
    protected = models.BooleanField(default=False, help_text=_("If true, the resource cannot be deleted automatically.  "))
    
    class Meta:
        indexes = [
            models.Index(fields=['target_type', 'target_id']),
            models.Index(fields=['resource_type']),
            models.Index(fields=['tag'])
        ]
        ordering = ['name']
    
    def save(self, *args, **kwargs):
        """Auto-populate image_width and image_height when an image is uploaded."""
        if self.image and self.resource_type == ResourceTypeChoices.IMAGE:
            try:
                # image.file may already be open; seek to start to be safe
                self.image.seek(0)
                with PilImage.open(self.image) as img:
                    self.image_width, self.image_height = img.size
            except Exception:
                # Never block a save because of metadata extraction failure
                pass
        elif not self.image:
            # Clear stale dimensions if the image was removed
            self.image_width = None
            self.image_height = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<Resource {self.name} (ID: {self.id})>"

    def clean(self):
        if self.resource_type == ResourceTypeChoices.DOCUMENT or self.resource_type == ResourceTypeChoices.OTHER:
            if not self.file:
                raise ValidationError("File must be provided for DOCUMENT or OTHER resource types.")
        elif self.resource_type == ResourceTypeChoices.LINK:
            if not self.link:
                raise ValidationError("Link must be provided for LINK resource type.")
        elif self.resource_type == ResourceTypeChoices.IMAGE:
            if not self.image:
                raise ValidationError("Image must be provided for IMAGE resource type.")
        if self.tag:
            self.tag = slugify(self.tag).upper()
    
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
        
    @property
    def is_expired(self):
        if self.expires_at:
            return self.expires_at < timezone.now()
        return False    
    
    @property
    def is_image(self):
        return self.resource_type == ResourceTypeChoices.IMAGE
    
    @property
    def is_document(self):
        return self.resource_type == ResourceTypeChoices.DOCUMENT
    
    @property
    def is_link(self):
        return self.resource_type == ResourceTypeChoices.LINK
    
    @property
    def is_audio(self):
        return self.resource_type == ResourceTypeChoices.AUDIO
    
    @property
    def is_video(self):
        return self.resource_type == ResourceTypeChoices.VIDEO  
    
    @property
    def resource_url(self):
        '''
        Returns the URL of the resource based on its type.
        '''
        if self.resource_type == ResourceTypeChoices.DOCUMENT or self.resource_type == ResourceTypeChoices.OTHER:
            if self.file:
                return self.file.url
        elif self.resource_type == ResourceTypeChoices.LINK:
            return self.link
        elif self.resource_type == ResourceTypeChoices.IMAGE:
            if self.image:
                return self.image.url
        return None

# TODO create new resource display model that can be used for frontend display, with fields like thumbnail, preview_url, etc. 
# # that can be generated based on the resource type and content. This will allow for more flexible and rich display of resources in the frontend without needing to add too many fields to the base Resource model.