from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

from django.core.exceptions import ValidationError

User = get_user_model()

class VerificationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending' # initial state before verification
    VERIFIED = 'verified', 'Verified' # state defining successful verification
    REJECTED = 'rejected', 'Rejected' # state defining rejection
    PROCESSED = 'processed', 'Processed' # final state defining no action needed

class RequiresVerificationModel(models.Model):
    """
    Abstract model to indicate that an entity requires verification.
    """
    
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING
    )
    verified_updated_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='verified_%(class)s',
        null=True,
        blank=True
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='processed_%(class)s',
        null=True,
        blank=True
    )
    
    class Meta:
        abstract = True
        
    def mark_verified(self, verifier):
        self.verification_status = VerificationStatus.VERIFIED
        self.verified_updated_at = timezone.now()
        self.verified_by = verifier
        self.save()
        
    def mark_rejected(self, verifier):
        self.verification_status = VerificationStatus.REJECTED
        self.verified_updated_at = timezone.now()
        self.verified_by = verifier
        self.save()
        
    def mark_pending(self):
        self.verification_status = VerificationStatus.PENDING
        self.verified_updated_at = None
        self.verified_by = None
        self.save()

    def mark_processed(self, processor):
        if not self.is_verified:
            raise ValidationError("Only verified items can be marked as processed.")

        self.verification_status = VerificationStatus.PROCESSED
        self.processed_at = timezone.now()
        self.processed_by = processor
        self.save()
        
    @property
    def is_verified(self):
        return self.verification_status == VerificationStatus.VERIFIED
    
    @property
    def is_rejected(self):
        return self.verification_status == VerificationStatus.REJECTED
    
    @property
    def is_pending(self):
        return self.verification_status == VerificationStatus.PENDING
    
    @property
    def is_processed(self):
        return self.verification_status == VerificationStatus.PROCESSED