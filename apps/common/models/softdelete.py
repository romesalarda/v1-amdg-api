from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.common.managers.softdelete import SoftDeleteManager, SoftDeleteQuerySet

User = get_user_model()

class SoftDeleteModel(models.Model):
    '''
    Abstract model that provides soft delete functionality.
    '''
    deleted_at = models.DateTimeField(blank=True, null=True)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='%(class)s_deleted_by'
    )
    
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        
    def soft_delete(self):
        if self.deleted_at:
            raise ValidationError("Object is already deleted.")
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at'])
        
    def restore(self):
        if not self.deleted_at:
            raise ValidationError("Cannot restore an object that is not deleted.")
        self.deleted_at = None
        self.save(update_fields=['deleted_at'])
        
    def hard_delete(self):
        super().delete()