"""
Stripe Connect account model.

Stores the platform-side record of a user's connected Stripe account and
mirrors the onboarding / readiness state returned by Stripe.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db import transaction


class StripeConnectedAccountStatusChoices(models.TextChoices):
    NOT_CREATED = 'NOT_CREATED', 'Not Created'
    ONBOARDING = 'ONBOARDING', 'Onboarding'
    ACTIVE = 'ACTIVE', 'Active'
    RESTRICTED = 'RESTRICTED', 'Restricted'
    DISABLED = 'DISABLED', 'Disabled'


class StripeConnectedAccount(models.Model):
    """A Stripe Connect account owned by a platform user."""

    connected_account_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stripe_accounts',
    )
    stripe_account_id = models.CharField(max_length=255, db_index=True)
    display_name = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    account_type = models.CharField(max_length=30, default='express')
    country = models.CharField(max_length=2, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    business_type = models.CharField(max_length=50, blank=True, default='')
    charges_enabled = models.BooleanField(default=False)
    payouts_enabled = models.BooleanField(default=False)
    details_submitted = models.BooleanField(default=False)
    disabled_reason = models.CharField(max_length=255, blank=True, default='')
    capabilities = models.JSONField(blank=True, default=dict)
    requirements = models.JSONField(blank=True, default=dict)
    metadata = models.JSONField(blank=True, default=dict)
    synced_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Stripe Connected Account'
        verbose_name_plural = 'Stripe Connected Accounts'
        indexes = [
            models.Index(fields=['stripe_account_id']),
            models.Index(fields=['charges_enabled', 'payouts_enabled']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['user', 'stripe_account_id'], name='unique_user_stripe_account'),
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self._state.adding and self.user_id:
                has_existing_accounts = StripeConnectedAccount.objects.filter(user_id=self.user_id).exists()
                if not has_existing_accounts:
                    self.is_primary = True

            super().save(*args, **kwargs)

            if self.is_primary and self.user_id:
                StripeConnectedAccount.objects.filter(user_id=self.user_id).exclude(pk=self.pk).update(is_primary=False)

    def __str__(self) -> str:
        label = self.display_name or self.stripe_account_id
        return f"{self.user} - {label}"

    @property
    def status(self) -> str:
        if self.disabled_reason:
            return StripeConnectedAccountStatusChoices.DISABLED
        if self.charges_enabled and self.payouts_enabled and self.details_submitted:
            return StripeConnectedAccountStatusChoices.ACTIVE
        if self.charges_enabled or self.payouts_enabled or self.details_submitted:
            return StripeConnectedAccountStatusChoices.RESTRICTED
        return StripeConnectedAccountStatusChoices.ONBOARDING

    @property
    def is_ready_for_payments(self) -> bool:
        return self.charges_enabled and self.details_submitted and not self.disabled_reason