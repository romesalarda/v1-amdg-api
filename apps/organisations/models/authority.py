from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

User = get_user_model()

class Leader(models.Model):
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='authorities_led')
    
    target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_id = models.PositiveIntegerField()
    authority_object = GenericForeignKey('target_type', 'target_id')
    
    notes = models.TextField(blank=True)
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='leaders_added')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('user', 'target_type', 'target_id')
    
    def __str__(self):
        return f"{self.user.username} leads {self.authority_object}"