from django.db import models
from django.contrib.auth import get_user_model

import uuid

class PaymentMethodTypeChoices(models.TextChoices):
    
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
    STRIPE = 'STRIPE', 'Stripe'
    CASH = 'CASH', 'Cash'

class PaymentMethod(models.Model):
    
    method_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    code = models.CharField(max_length=20, unique=True, blank=True)
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='payment_methods'
    )
    method_type = models.CharField(
        max_length=20,
        choices=PaymentMethodTypeChoices.choices
    )
    
    provided_details = models.JSONField(blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_payment_methods'
    )
    
    def save(self, *args, **kwargs):
        if not self.code:
            from core.utils.display import generate_human_readable_id
            self.code = generate_human_readable_id(20, 'PYM', str(self.event.id))
        
        if self.pk and self.__class__.objects.filter(pk=self.pk).values('code').first()['code'] != self.code:
            raise ValueError("PaymentMethod.code is immutable")
            
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.title} ({self.get_method_type_display()})"
    
    def __repr__(self):
        return f"<PaymentMethod id={self.method_id} code={self.code} type={self.method_type}>"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment Method'
        verbose_name_plural = 'Payment Methods'
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['method_type']),
            models.Index(fields=['is_active']),
        ]