"""
Stripe PaymentIntent management.

Handles creation, confirmation, cancellation, and retrieval of Stripe PaymentIntents.
Uses idempotency keys to prevent duplicate charges on retry.
"""
import stripe
from typing import Dict, Optional
from decimal import Decimal
from djmoney.money import Money
import logging

from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.exceptions import (
    StripePaymentError,
    StripeValidationError,
    map_stripe_error
)

logger = logging.getLogger(__name__)


class PaymentIntentService:
    """Service for managing Stripe PaymentIntents."""
    
    @staticmethod
    def create(
        amount: Money,
        currency: str,
        payment_reference: str,
        metadata: Dict,
        customer_email: Optional[str] = None,
        customer_id: Optional[str] = None,
        description: Optional[str] = None,
        stripe_account_id: Optional[str] = None,
    ) -> stripe.PaymentIntent:
        """
        Create a Stripe PaymentIntent.
        
        Args:
            amount: Payment amount (Money object with currency)
            currency: Currency code (e.g., 'gbp', 'usd')
            payment_reference: Unique payment reference for idempotency
            metadata: Additional data to attach to PaymentIntent (max 50 keys, 500 chars per value)
            customer_email: Customer email for receipt
            customer_id: Existing Stripe customer ID
            description: Payment description
            
        Returns:
            stripe.PaymentIntent: Created PaymentIntent object
            
        Raises:
            StripeValidationError: If validation fails
            StripePaymentError: If Stripe API call fails
        """
        StripeClient.initialize()
        
        # Validate amount
        if amount.amount <= 0:
            raise StripeValidationError(
                message=f"Invalid amount: {amount}. Must be greater than zero.",
                user_message="Invalid payment amount."
            )
        
        # Convert amount to smallest currency unit (e.g., pence for GBP)
        # Stripe expects integer amounts in cents/pence
        amount_in_cents = int(amount.amount * 100)
        
        # Validate metadata size (Stripe limits)
        if len(metadata) > 50:
            logger.warning(f"Metadata has {len(metadata)} keys. Stripe limit is 50. Truncating.")
            metadata = dict(list(metadata.items())[:50])
        
        # Prepare request parameters
        params = {
            'amount': amount_in_cents,
            'currency': currency.lower(),
            'metadata': metadata,
            'automatic_payment_methods': {
                'enabled': True,
            },
        }
        
        if description:
            params['description'] = description[:1000]  # Stripe limit

        if customer_id:
            params['customer'] = customer_id
        elif customer_email:
            params['receipt_email'] = customer_email

        request_options = {}
        if stripe_account_id:
            request_options['stripe_account'] = stripe_account_id
        else:
            raise StripeValidationError(
                message="Stripe account ID is required for PaymentIntent creation.",
                user_message="Payment processing error. Please try again."
            )
                
        try:
            # Use payment_reference as idempotency key to prevent duplicate charges
            payment_intent = stripe.PaymentIntent.create(
                **params,
                idempotency_key=payment_reference,
                **request_options,
            )
            
            logger.info(
                f"Created PaymentIntent {payment_intent.id} for {amount} "
                f"(reference: {payment_reference})"
            )
            
            return payment_intent
            
        except stripe.StripeError as e:
            logger.error(f"Failed to create PaymentIntent: {str(e)}")
            raise map_stripe_error(e)
        except Exception as e:
            logger.exception(f"Unexpected error creating PaymentIntent: {str(e)}")
            raise StripePaymentError(
                message=f"Unexpected error: {str(e)}",
                user_message="Payment processing error. Please try again."
            )
    
    @staticmethod
    def retrieve(payment_intent_id: str, stripe_account_id: Optional[str] = None) -> stripe.PaymentIntent:
        """
        Retrieve a PaymentIntent by ID.
        
        Args:
            payment_intent_id: Stripe PaymentIntent ID (starts with 'pi_')
            
        Returns:
            stripe.PaymentIntent: Retrieved PaymentIntent object
            
        Raises:
            StripePaymentError: If retrieval fails
        """
        StripeClient.initialize()

        if not payment_intent_id:
            raise StripeValidationError(
                message="PaymentIntent ID is required for retrieval.",
                user_message="Payment retrieval error. Please try again."
            )
        
        try:
            kwargs = {}
            if stripe_account_id:
                kwargs['stripe_account'] = stripe_account_id
            else:
                raise StripeValidationError(
                    message="Stripe account ID is required for PaymentIntent retrieval.",
                    user_message="Payment retrieval error. Please try again."
                )

            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id, **kwargs)
            return payment_intent
            
        except stripe.StripeError as e:
            logger.error(f"Failed to retrieve PaymentIntent {payment_intent_id}: {str(e)}")
            raise map_stripe_error(e)
    
    @staticmethod
    def confirm(
        payment_intent_id: str,
        payment_method: Optional[str] = None,
        stripe_account_id: Optional[str] = None,
    ) -> stripe.PaymentIntent:
        """
        Manually confirm a PaymentIntent.
        
        Typically not needed as PaymentIntents auto-confirm when customer submits
        payment in frontend. Use this for server-side confirmation scenarios.
        
        Args:
            payment_intent_id: Stripe PaymentIntent ID
            payment_method: Optional payment method ID if not already attached
            
        Returns:
            stripe.PaymentIntent: Confirmed PaymentIntent object
            
        Raises:
            StripePaymentError: If confirmation fails
        """
        StripeClient.initialize()
        if not stripe_account_id:
            raise StripeValidationError(
                message="Stripe account ID is required for PaymentIntent confirmation.",
                user_message="Payment processing error. Please try again."
            )

        try:
            params = {}
            if payment_method:
                params['payment_method'] = payment_method

            request_options = {'stripe_account': stripe_account_id}

            payment_intent = stripe.PaymentIntent.confirm(
                payment_intent_id,
                **params,
                **request_options,
            )

            logger.info(f"Confirmed PaymentIntent {payment_intent_id}")
            return payment_intent

        except stripe.StripeError as e:
            logger.error(f"Failed to confirm PaymentIntent {payment_intent_id}: {str(e)}")
            raise map_stripe_error(e)
    
    @staticmethod
    def cancel(
        payment_intent_id: str,
        cancellation_reason: Optional[str] = None,
        stripe_account_id: Optional[str] = None,
    ) -> stripe.PaymentIntent:
        """
        Cancel a PaymentIntent.
        
        Can only cancel PaymentIntents in certain statuses (requires_payment_method,
        requires_capture, requires_confirmation, requires_action).
        
        Args:
            payment_intent_id: Stripe PaymentIntent ID
            cancellation_reason: Optional reason for cancellation
            
        Returns:
            stripe.PaymentIntent: Cancelled PaymentIntent object
            
        Raises:
            StripePaymentError: If cancellation fails
        """
        StripeClient.initialize()
        if not stripe_account_id:
            raise StripeValidationError(
                message="Stripe account ID is required for PaymentIntent cancellation.",
                user_message="Payment processing error. Please try again."
            )

        try:
            params = {}
            if cancellation_reason:
                params['cancellation_reason'] = cancellation_reason[:500]

            request_options = {'stripe_account': stripe_account_id}

            payment_intent = stripe.PaymentIntent.cancel(
                payment_intent_id,
                **params,
                **request_options,
            )

            logger.info(f"Cancelled PaymentIntent {payment_intent_id}")
            return payment_intent

        except stripe.StripeError as e:
            logger.error(f"Failed to cancel PaymentIntent {payment_intent_id}: {str(e)}")
            raise map_stripe_error(e)
    
    @staticmethod
    def update_metadata(
        payment_intent_id: str,
        metadata: Dict,
        stripe_account_id: Optional[str] = None,
    ) -> stripe.PaymentIntent:
        """
        Update metadata on an existing PaymentIntent.
        
        Args:
            payment_intent_id: Stripe PaymentIntent ID
            metadata: New metadata to merge with existing
            
        Returns:
            stripe.PaymentIntent: Updated PaymentIntent object
            
        Raises:
            StripePaymentError: If update fails
        """
        StripeClient.initialize()
        
        try:
            kwargs = {}
            if stripe_account_id:
                kwargs['stripe_account'] = stripe_account_id

            payment_intent = stripe.PaymentIntent.modify(
                payment_intent_id,
                metadata=metadata,
                **kwargs,
            )
            
            logger.info(f"Updated metadata for PaymentIntent {payment_intent_id}")
            return payment_intent
            
        except stripe.StripeError as e:
            logger.error(f"Failed to update PaymentIntent {payment_intent_id}: {str(e)}")
            raise map_stripe_error(e)
