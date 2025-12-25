from django.db import models
from django.contrib.auth import get_user_model

from apps.common.models.verification import RequiresVerificationModel

class BasePersonalInfoModel(RequiresVerificationModel):
    """
    Abstract base model for personal information related models.
    """
    
    code = models.CharField(max_length=5, unique=True)
    label = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    
    active = models.BooleanField(default=True)
        
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, related_name='added_%(class)s', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True
        
class BaseAttendeePersonalInfoModel(RequiresVerificationModel):
    """
    Abstract base model for attendee personal information through models.
    """
    
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='%(class)s')
    
    details = models.TextField(null=True, blank=True)  # additional details if any
    added_at = models.DateTimeField(auto_now_add=True) # time when this requirement was added
    added_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, related_name='added_attendee_%(class)s', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True