
from django.db import models
from apps.common.models.verification import RequiresVerificationModel
import uuid

class BankTransferEvidence(RequiresVerificationModel):
    '''
    Model to store evidence of bank transfers for payments. This includes a unique transfer ID, an uploaded file as evidence, and a reference to the associated payment. 
    The model inherits from RequiresVerificationModel to ensure that the evidence can be verified before being accepted.
    '''
    bank_transfer_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    transfer_id = models.CharField(max_length=255, unique=True)
    evidence_file = models.FileField(upload_to='bank_transfer_evidence/')

    uploaded_at = models.DateTimeField(auto_now_add=True)
    payment = models.ForeignKey('payments.Payment', on_delete=models.CASCADE, related_name='bank_transfer_evidence', null=True, blank=True)

    def __str__(self):
        return f"Evidence for Transfer ID: {self.transfer_id}"