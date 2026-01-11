"""
Stripe Refund management.

Handles creation and retrieval of Stripe Refunds.
Supports full and partial refunds with reason tracking.
"""
import stripe
from typing import Dict, Optional
from decimal import Decimal
from djmoney.money import Money
import logging

from apps.payments.services.stripe.client import StripeClient
from apps.payments.services.stripe.exceptions import (
    StripeRefundError,
    StripeValidationError,
    map_stripe_error
)

logger = logging.getLogger(__name__)


class RefundService:
    """Service for managing Stripe Refunds."""
    
    # Stripe refund reasons
    REASON_DUPLICATE = 'duplicate'
    REASON_FRAUDULENT = 'fraudulent'
    REASON_REQUESTED_BY_CUSTOMER = 'requested_by_customer'
    
    @staticmethod
    def create(
        payment_intent_id: str,
        amount: Optional[Money] = None,
        reason: str = REASON_REQUESTED_BY_CUSTOMER,
        metadata: Optional[Dict] = None,
        refund_reference: Optional[str] = None
    ) -> stripe.Refund:
        """
        Create a Stripe Refund.
        
        Args:
            payment_intent_id: Stripe PaymentIntent ID to refund
            amount: Refund amount. If None, refunds full amount
            reason: Refund reason (duplicate, fraudulent, requested_by_customer)
            metadata: Additional data to attach to refund
            refund_reference: Unique refund reference for idempotency
            
        Returns:
            stripe.Refund: Created Refund object
            
        Raises:
            StripeValidationError: If validation fails
            StripeRefundError: If Stripe API call fails
        """
        StripeClient.initialize()
        
        # Validate amount if provided
        if amount is not None and amount.amount <= 0:
            raise StripeValidationError(
                message=f"Invalid refund amount: {amount}. Must be greater than zero.",
                user_message="Invalid refund amount."
            )
        
        # Prepare request parameters
        params = {
            'payment_intent': payment_intent_id,
            'reason': reason,
        }
        
        if amount is not None:
            # Convert to smallest currency unit (cents/pence)
            amount_in_cents = int(amount.amount * 100)
            params['amount'] = amount_in_cents
        
        if metadata:
            # Validate metadata size (Stripe limits)
            if len(metadata) > 50:
                logger.warning(f"Metadata has {len(metadata)} keys. Stripe limit is 50. Truncating.")
                metadata = dict(list(metadata.items())[:50])
            params['metadata'] = metadata
        
        try:
            # Use refund_reference as idempotency key if provided
            kwargs = {}
            if refund_reference:
                kwargs['idempotency_key'] = refund_reference
            
            refund = stripe.Refund.create(**params, **kwargs)
            
            refund_amount = amount or "full amount"
            logger.info(
                f"Created Refund {refund.id} for PaymentIntent {payment_intent_id} "
                f"({refund_amount})"
            )
            
            return refund
            
        except stripe.StripeError as e:
            logger.error(f"Failed to create Refund for {payment_intent_id}: {str(e)}")
            
            # Check for specific refund errors
            error_code = getattr(e, 'code', None)
            if error_code == 'charge_already_refunded':
                raise StripeRefundError(
                    message=f"Charge already refunded: {str(e)}",
                    stripe_error=e,
                    user_message="This payment has already been refunded."
                )
            
            raise map_stripe_error(e)
        
        except Exception as e:
            logger.exception(f"Unexpected error creating Refund: {str(e)}")
            raise StripeRefundError(
                message=f"Unexpected error: {str(e)}",
                user_message="Refund processing error. Please try again."
            )
    
    @staticmethod
    def retrieve(refund_id: str) -> stripe.Refund:
        """
        Retrieve a Refund by ID.
        
        Args:
            refund_id: Stripe Refund ID (starts with 're_')
            
        Returns:
            stripe.Refund: Retrieved Refund object
            
        Raises:
            StripeRefundError: If retrieval fails
        """
        StripeClient.initialize()
        
        try:
            refund = stripe.Refund.retrieve(refund_id)
            return refund
            
        except stripe.StripeError as e:
            logger.error(f"Failed to retrieve Refund {refund_id}: {str(e)}")
            raise map_stripe_error(e)
    
    @staticmethod
    def list_for_payment_intent(
        payment_intent_id: str,
        limit: int = 100
    ) -> stripe.ListObject:
        """
        List all refunds for a PaymentIntent.
        
        Args:
            payment_intent_id: Stripe PaymentIntent ID
            limit: Maximum number of refunds to return
            
        Returns:
            stripe.ListObject: List of Refund objects
            
        Raises:
            StripeRefundError: If listing fails
        """
        StripeClient.initialize()
        
        try:
            refunds = stripe.Refund.list(
                payment_intent=payment_intent_id,
                limit=limit
            )
            
            return refunds
            
        except stripe.StripeError as e:
            logger.error(f"Failed to list Refunds for {payment_intent_id}: {str(e)}")
            raise map_stripe_error(e)
    
    @staticmethod
    def cancel(refund_id: str) -> stripe.Refund:
        """
        Cancel a pending Refund.
        
        Can only cancel refunds that are in 'pending' status.
        Once a refund succeeds or fails, it cannot be cancelled.
        
        Args:
            refund_id: Stripe Refund ID
            
        Returns:
            stripe.Refund: Cancelled Refund object
            
        Raises:
            StripeRefundError: If cancellation fails
        """
        StripeClient.initialize()
        
        try:
            refund = stripe.Refund.cancel(refund_id)
            
            logger.info(f"Cancelled Refund {refund_id}")
            return refund
            
        except stripe.StripeError as e:
            logger.error(f"Failed to cancel Refund {refund_id}: {str(e)}")
            raise map_stripe_error(e)
