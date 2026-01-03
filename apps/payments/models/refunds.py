from django.db import models
from django.core import validators, exceptions
from django.contrib.auth import get_user_model
from djmoney.models.fields import MoneyField

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from djmoney.money import Money

from django.conf import settings

from apps.common.models.verification import RequiresVerificationModel

from core.utils.display import try_generate_unique_code
from decimal import Decimal
import uuid

User = get_user_model()

# refund process
# 1. User requests refund -> RefundRequest created with status 'pending'
# 2. Admin reviews request -> marks as 'verified' or 'rejected'
# 3. If 'verified', admin processes refund externally -> marks as 'processed'

REFUND_TARGET_ID = 'refund_amount'  # The property/method name to get refunded amount from associated objects
class RefundRequest(RequiresVerificationModel): # inherits verification fields 
    '''
    RefundRequest model to handle refund requests for payments.

    Processing Steps:
    1. User requests a refund, creating a RefundRequest with status 'pending'.
    2. An admin reviews the request and marks it as 'verified' or 'rejected'.
    3. If marked 'verified', the admin processes the refund externally and marks it as 'processed'.

    '''

    refund_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) # Public identifier
    tracking_reference = models.CharField(max_length=100, unique=True) # e.g., participant reference or order number

    payment = models.ForeignKey(
        'payments.Payment',
        on_delete=models.CASCADE,
        related_name='refund_requests'
    )
    amount = MoneyField(max_digits=10, decimal_places=2, default_currency='GBP')
    reason = models.TextField(validators=[validators.MaxLengthValidator(1000), validators.MinLengthValidator(10)])

    requested_at = models.DateTimeField(auto_now_add=True)
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='refund_requests_made'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='refund_requests_processed'
    )

    metadata = models.JSONField(default=dict, blank=True) # contains stripe_refund_id etc.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'Refund Request'
        verbose_name_plural = 'Refund Requests'
        constraints = [
            models.UniqueConstraint(fields=['payment', 'is_active'], name='unique_active_refund_per_payment', condition=models.Q(is_active=True))
        ]

    def __str__(self):
        return f"RefundRequest({self.id}) - {self.status}"
    
    def __repr__(self):
        return f"<RefundRequest id={self.id} status={self.status} amount={self.amount}>"
    
    def save(self, *args, **kwargs):
        self.clean()
        try:
            self.tracking_reference = try_generate_unique_code(
                model_class=RefundRequest,
                length=10,
                max_attempts=settings.MAX_ID_GENERATION_ATTEMPTS,
                lookup_field='tracking_reference'
            )
        except ValueError:
            raise exceptions.ValidationError("Could not generate a unique acceptance code. Please try again.")
        if not self.amount or self.amount.amount == 0:
            self.amount = Money(self.get_refund_amount(), self.payment.amount.currency)

        super().save(*args, **kwargs)
    
    def clean(self):
        if self.amount.amount <= 0:
            raise exceptions.ValidationError("Refund amount must be greater than zero.")
        if self.amount > self.payment.base_amount:
            raise exceptions.ValidationError("Refund amount cannot exceed the original payment amount.")
        
    def associate_with(self, obj):
        '''
        Associate this refund request with another entity (e.g., order, booking).

        @param obj: The object to associate with (must be a model instance).
        @return: RefundAssociation instance linking the refund request to the object.
        '''
        if not isinstance(obj, models.Model):
            raise ValueError("Can only associate with Django model instances.")

        if self._get_refund_amount(obj) > self.payment.base_amount - self.get_refund_amount():
            raise ValueError("Cannot associate refund: refunded amount exceeds available payment amount.")        

        refund = RefundAssociation.objects.create(
            refund_request=self,
            target_object=obj,
            target_type=ContentType.objects.get_for_model(obj),
            target_id=obj.pk
        )
        return refund
    
    def _get_refund_amount(self, obj) -> 'Money':
        '''
        Helper method to get the refunded amount from an associated object.

        @param obj: The associated object.
        @return: Refunded amount as a Money object.
        '''
        if hasattr(obj, REFUND_TARGET_ID):
            if callable(getattr(obj, REFUND_TARGET_ID)):
                return getattr(obj, REFUND_TARGET_ID)()
            else:
                return getattr(obj, REFUND_TARGET_ID)
        else:
            raise NotImplementedError(f"The target object of type {type(obj)} does not implement '{REFUND_TARGET_ID}' property.")
    
    def get_refund_amount(self):
        '''
        Returns the total amount refunded across all associated entities.

        @return: Total refunded amount as a Money object.
        '''
        total = Money(0, self.payment.base_amount.currency)
        associations = self.associations.all()
        for assoc in associations:
            refunded_amount = self._get_refund_amount(assoc.target_object)
            total += refunded_amount    

        return total
    
    def absolute_amount(self) -> Money:
        '''
        Returns the absolute amount of the refund request.

        @return: Absolute amount as a Money object.
        '''
        # 2 d.p
        return Decimal(self.amount.amount).quantize(Decimal('0.01'))

    
    @property
    def is_partial(self):
        '''
        Check if the refund request is for a partial amount.

        @return: True if partial refund, False if full refund.
        '''
        return self.amount < self.payment.base_amount
    
    @property
    def is_full(self):
        '''
        Check if the refund request is for the full amount.

        @return: True if full refund, False if partial refund.
        '''
        return self.amount == self.payment.base_amount
    
    def is_refundable(self, datetime: timezone.datetime) -> bool: # TODO: Test me
        '''
        Check if the payment is eligible for a refund within the event's refund window.

        @return: True if refundable, False otherwise.
        '''
        from apps.common.models import AvailabilityTypeChoices
        from apps.payments.models.payments import PaymentStatusChoices

        if not self.payment.status == PaymentStatusChoices.COMPLETED or not self.payment.event.settings.refunds_enabled:
            return False
        
        return self.payment.event.is_within_availability_window(
            AvailabilityTypeChoices.REFUNDS, datetime,
            true_if_non_existent=True
            )
        
class RefundAssociation(models.Model):
    '''
    Model to associate refunds with various entities like orders or bookings.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    refund_request = models.ForeignKey(
        RefundRequest,
        on_delete=models.CASCADE,
        related_name='associations'
    )
    target_id = models.PositiveIntegerField()
    target_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='refund_association_targets'
    )
    target_object = GenericForeignKey('target_type', 'target_id')

    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Refund Association'
        verbose_name_plural = 'Refund Associations'
        unique_together = ('refund_request', 'target_type', 'target_id')

    def __str__(self):
        return f"RefundAssociation(refund_request={self.refund_request.id}, object={self.target_object})"
    
    def __repr__(self):
        return f"<RefundAssociation refund_request={self.refund_request.id} object={self.target_object}>"
    
    def save(self, *args, **kwargs):
        self.clean()
        if not self.description:
            self.description = f"Association of refund request {self.refund_request.id} with {self.target_object}."
        super().save(*args, **kwargs)

    