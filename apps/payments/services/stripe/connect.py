"""
Stripe Connect service helpers.

Encapsulates connected-account creation, onboarding link generation, and
account status synchronization.
"""
from __future__ import annotations

from typing import Optional, Tuple

import logging
import stripe
from django.conf import settings

from apps.payments.models import StripeConnectedAccount, StripeConnectedAccountStatusChoices
from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.exceptions import StripeServiceError, map_stripe_error

logger = logging.getLogger(__name__)


def _get_disabled_reason(requirements) -> str:
    if not requirements:
        return ''

    if isinstance(requirements, dict):
        return requirements.get('disabled_reason', '') or ''

    return getattr(requirements, 'disabled_reason', '') or ''


class StripeConnectService:
    """Helpers for managing Stripe Connect accounts."""

    @staticmethod
    def get_user_account(user) -> Optional[StripeConnectedAccount]:
        if not user or not getattr(user, 'is_authenticated', False):
            return None

        return StripeConnectedAccount.objects.filter(user=user).first()

    @staticmethod
    def resolve_payment_method_stripe_account_id(payment_method) -> Optional[str]:
        if not payment_method:
            return None

        helper = getattr(payment_method, 'get_stripe_account_id', None)
        if callable(helper):
            return helper()

        details = getattr(payment_method, 'provided_details', None) or {}
        if details.get('use_platform_account'):
            return None
        stripe_account_id = details.get('stripe_account_id')
        return str(stripe_account_id) if stripe_account_id else None

    @staticmethod
    def get_payment_method_account(payment_method) -> Optional[StripeConnectedAccount]:
        stripe_account_id = StripeConnectService.resolve_payment_method_stripe_account_id(payment_method)
        if not stripe_account_id:
            return None
        return StripeConnectedAccount.objects.filter(stripe_account_id=stripe_account_id).first()

    @staticmethod
    def create_or_refresh_account(user, country: Optional[str] = None) -> Tuple[StripeConnectedAccount, stripe.Account]:
        """
        Ensure the user has a Stripe connected account and return the refreshed account.
        """
        StripeClient.initialize()
        existing_account = StripeConnectService.get_user_account(user)
        if existing_account:
            stripe_account = StripeConnectService.retrieve_account(existing_account.stripe_account_id)
            account_record = StripeConnectService.sync_from_stripe(existing_account, stripe_account)
            return account_record, stripe_account

        try:
            stripe_account = stripe.Account.create(
                type='express',
                country=(country or getattr(settings, 'STRIPE_CONNECT_DEFAULT_COUNTRY', 'GB')).upper(),
                email=user.email,
                business_type='individual',
                capabilities={
                    'card_payments': {'requested': True},
                    'transfers': {'requested': True},
                },
            )
            account_record = StripeConnectedAccount.objects.create(
                user=user,
                stripe_account_id=stripe_account.id,
                account_type=getattr(stripe_account, 'type', 'express'),
                country=getattr(stripe_account, 'country', '') or '',
                email=getattr(stripe_account, 'email', '') or user.email,
                business_type=getattr(stripe_account, 'business_type', '') or 'individual',
                charges_enabled=bool(getattr(stripe_account, 'charges_enabled', False)),
                payouts_enabled=bool(getattr(stripe_account, 'payouts_enabled', False)),
                details_submitted=bool(getattr(stripe_account, 'details_submitted', False)),
                disabled_reason=_get_disabled_reason(getattr(stripe_account, 'requirements', None)),
                capabilities=getattr(stripe_account, 'capabilities', {}) or {},
                requirements=getattr(stripe_account, 'requirements', {}) or {},
                metadata=getattr(stripe_account, 'metadata', {}) or {},
            )
            logger.info("Created Stripe Connect account %s for user %s", stripe_account.id, user.id)
            return account_record, stripe_account
        except stripe.StripeError as e:
            logger.error("Failed to create Stripe Connect account for user %s: %s", user.id, str(e))
            raise map_stripe_error(e)
        except Exception as e:
            logger.exception("Unexpected error creating Stripe Connect account for user %s: %s", user.id, str(e))
            raise StripeServiceError(
                message=f"Unexpected error creating Stripe Connect account: {str(e)}",
                user_message="Unable to create Stripe Connect account. Please try again."
            )

    @staticmethod
    def retrieve_account(stripe_account_id: str) -> stripe.Account:
        StripeClient.initialize()
        try:
            return stripe.Account.retrieve(stripe_account_id)
        except stripe.StripeError as e:
            logger.error("Failed to retrieve Stripe Connect account %s: %s", stripe_account_id, str(e))
            raise map_stripe_error(e)

    @staticmethod
    def create_account_link(account_id: str, refresh_url: str, return_url: str) -> stripe.AccountLink:
        StripeClient.initialize()
        try:
            return stripe.AccountLink.create(
                account=account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type='account_onboarding',
            )
        except stripe.StripeError as e:
            logger.error("Failed to create Stripe account link for %s: %s", account_id, str(e))
            raise map_stripe_error(e)

    @staticmethod
    def sync_from_stripe(account_record: StripeConnectedAccount, stripe_account: stripe.Account) -> StripeConnectedAccount:
        account_record.account_type = getattr(stripe_account, 'type', account_record.account_type) or account_record.account_type
        account_record.country = getattr(stripe_account, 'country', account_record.country) or account_record.country
        account_record.email = getattr(stripe_account, 'email', account_record.email) or account_record.email
        account_record.business_type = getattr(stripe_account, 'business_type', account_record.business_type) or account_record.business_type
        account_record.charges_enabled = bool(getattr(stripe_account, 'charges_enabled', account_record.charges_enabled))
        account_record.payouts_enabled = bool(getattr(stripe_account, 'payouts_enabled', account_record.payouts_enabled))
        account_record.details_submitted = bool(getattr(stripe_account, 'details_submitted', account_record.details_submitted))

        requirements = getattr(stripe_account, 'requirements', {}) or {}
        account_record.disabled_reason = _get_disabled_reason(requirements)
        account_record.capabilities = getattr(stripe_account, 'capabilities', {}) or {}
        account_record.requirements = requirements
        account_record.metadata = getattr(stripe_account, 'metadata', {}) or {}
        account_record.save()
        return account_record

    @staticmethod
    def refresh_user_account(user) -> Optional[StripeConnectedAccount]:
        account_record = StripeConnectService.get_user_account(user)
        if not account_record:
            return None

        stripe_account = StripeConnectService.retrieve_account(account_record.stripe_account_id)
        return StripeConnectService.sync_from_stripe(account_record, stripe_account)
