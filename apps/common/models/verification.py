from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

from django.core.exceptions import ValidationError

User = get_user_model()

class VerificationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending' # initial state before verification
    VERIFIED = 'verified', 'Verified' # state defining successful verification either manual or automatic
    REJECTED = 'rejected', 'Rejected' # state defining rejection
    PROCESSED = 'processed', 'Processed' # final state defining no action needed either manual or automatic

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
    processed_at = models.DateTimeField(null=True, blank=True) # can be auto if done by system
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='processed_%(class)s',
        null=True,
        blank=True
    )
    auto_processed = models.BooleanField(default=False) # indicates if processing was automatic/system-driven
    
    class Meta:
        abstract = True
        
    def mark_verified(self, verifier=None):
        if self.verification_status == VerificationStatus.VERIFIED:
            return
        self.verification_status = VerificationStatus.VERIFIED
        self.verified_updated_at = timezone.now()
        self.verified_by = verifier
        self.save()
        
    def mark_rejected(self, verifier=None):
        self.verification_status = VerificationStatus.REJECTED
        self.verified_updated_at = timezone.now()
        self.verified_by = verifier
        self.save()
        
    def mark_pending(self):
        self.verification_status = VerificationStatus.PENDING
        self.verified_updated_at = None
        self.verified_by = None
        self.save()

    def mark_processed(self, processor=None):
        if not self.is_verified:
            raise ValidationError("Only verified items can be marked as processed.")

        self.verification_status = VerificationStatus.PROCESSED
        self.processed_at = timezone.now()
        if processor:
            self.processed_by = processor
        else:
            self.auto_processed = True
        self.save()
        
    @property
    def is_verified(self) -> bool:
        # Processed implies the object passed verification first.
        return self.verification_status in {VerificationStatus.VERIFIED, VerificationStatus.PROCESSED}
    
    @property
    def is_rejected(self) -> bool:
        return self.verification_status == VerificationStatus.REJECTED
    
    @property
    def is_pending(self) -> bool:
        return self.verification_status == VerificationStatus.PENDING
    
    @property
    def is_processed(self) -> bool:
        return self.verification_status == VerificationStatus.PROCESSED