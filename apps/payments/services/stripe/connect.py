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
from django.db import transaction
from typing import Optional, Tuple

from apps.payments.models import StripeConnectedAccount
from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.exceptions import StripeServiceError, map_stripe_error

logger = logging.getLogger(__name__)


def _get_disabled_reason(requirements) -> str:
    if not requirements:
        return ''

    if isinstance(requirements, dict):
        return requirements.get('disabled_reason', '') or ''

    return getattr(requirements, 'disabled_reason', '') or ''

def get_disabled_reason(requirements) -> str:
    return _get_disabled_reason(requirements)

def get_user_account(user) -> Optional[StripeConnectedAccount]:
    '''
    Retrieve the active Stripe connected account for the given user, preferring primary accounts.
    '''
    if not user or not getattr(user, 'is_authenticated', False):
        return None

    return (
        StripeConnectedAccount.objects
        .filter(user=user, is_active=True)
        .order_by('-is_primary', '-created_at')
        .first()
        or StripeConnectedAccount.objects
        .filter(user=user)
        .order_by('-is_primary', '-created_at')
        .first()
    )

def set_primary(account: StripeConnectedAccount) -> StripeConnectedAccount:
    '''
    Set the given Stripe connected account as the primary account for the user, unsetting all others.
    '''
    if not account or not account.user_id:
        raise StripeServiceError(
            message='Invalid Stripe connected account for primary assignment.',
            user_message='Unable to set primary account.',
        )

    with transaction.atomic():
        StripeConnectedAccount.objects.filter(user_id=account.user_id).exclude(pk=account.pk).update(is_primary=False)
        account.is_primary = True
        account.save(update_fields=['is_primary', 'updated_at'])

    return account

def resolve_payment_method_stripe_account_id(payment_method) -> Optional[str]:
    '''
    Resolve the Stripe account ID associated with the given payment method.
    Returns None if no Stripe account ID is found or if the platform account is used.
    '''
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

def get_payment_method_account(payment_method) -> Optional[StripeConnectedAccount]:
    stripe_account_id = resolve_payment_method_stripe_account_id(payment_method)
    if not stripe_account_id:
        return None
    return StripeConnectedAccount.objects.filter(stripe_account_id=stripe_account_id).first()

def create_or_refresh_account(user, country: Optional[str] = None, force_new: bool = False) -> Tuple[StripeConnectedAccount, stripe.Account]:
    """
    Ensure the user has a Stripe connected account and return the refreshed account.
    
    Args:
        user: The user to create/refresh account for
        country: Optional country code for the account
        force_new: If True, create a new account even if one exists. If False, return existing account.
    Returns:
        Tuple[StripeConnectedAccount, stripe.Account]: The local account record and the Stripe account object.
    Raises:
        StripeServiceError: If account creation or synchronization fails.
    """
    StripeClient.initialize()
    
    if not force_new:
        existing_account = get_user_account(user)
        if existing_account:
            stripe_account = retrieve_account(existing_account.stripe_account_id)
            account_record = sync_from_stripe(existing_account, stripe_account)
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
        
        # Determine if this should be the primary account
        # It's primary only if no other accounts exist
        existing_count = StripeConnectedAccount.objects.filter(user=user).count()
        is_primary = existing_count == 0
        
        # Generate a display name if this is a secondary account
        display_name = f"Account {existing_count + 1}" if existing_count > 0 else "Main account"
        
        account_record = StripeConnectedAccount.objects.create(
            user=user,
            stripe_account_id=stripe_account.id,
            display_name=display_name,
            is_primary=is_primary,
            is_active=True,
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
        logger.info("Created Stripe Connect account %s for user %s (is_primary=%s)", stripe_account.id, user.id, is_primary)
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

def retrieve_account(stripe_account_id: str) -> stripe.Account:
    '''
    Retrieve a Stripe connected account by its ID.

    Raises:
        StripeServiceError: If the retrieval fails due to a Stripe error.
    '''
    StripeClient.initialize()
    try:
        return stripe.Account.retrieve(stripe_account_id)
    except stripe.StripeError as e:
        logger.error("Failed to retrieve Stripe Connect account %s: %s", stripe_account_id, str(e))
        raise map_stripe_error(e)

def create_account_link(account_id: str, refresh_url: str, return_url: str) -> stripe.AccountLink:
    '''
    Create a Stripe account link for onboarding or account management.

    Raises:
        StripeServiceError: If the creation of the account link fails due to a Stripe error.
    '''
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

def sync_from_stripe(account_record: StripeConnectedAccount, stripe_account: stripe.Account) -> StripeConnectedAccount:
    '''
    Synchronize the local StripeConnectedAccount record with the latest data from the Stripe account.

    Args:
        account_record (StripeConnectedAccount): The local account record to update.
        stripe_account (stripe.Account): The Stripe account object containing the latest data.

    Returns:
        StripeConnectedAccount: The updated local account record.
    '''
    
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

def refresh_user_account(user) -> Optional[StripeConnectedAccount]:
    '''
    Refresh the Stripe connected account for a user by retrieving the latest data from Stripe and synchronizing it with the local record.

    Args:
        user: The user whose Stripe connected account should be refreshed.

    Returns:
        Optional[StripeConnectedAccount]: The updated local account record, or None if no account exists for the user.

    Raises:
        StripeServiceError: If the retrieval or synchronization with Stripe fails.
    '''
    account_record = get_user_account(user)
    if not account_record:
        return None

    stripe_account = retrieve_account(account_record.stripe_account_id)
    return sync_from_stripe(account_record, stripe_account)

def get_user_accounts(user):
    """
    Get all Stripe connected accounts for a user, ordered by primary then creation date.

    Args:
        user: The user whose Stripe connected accounts should be retrieved.

    Returns:
        QuerySet[StripeConnectedAccount]: A queryset of the user's Stripe connected accounts, ordered by primary status and creation date.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return StripeConnectedAccount.objects.none()

    return StripeConnectedAccount.objects.filter(user=user).order_by('-is_primary', '-created_at')
