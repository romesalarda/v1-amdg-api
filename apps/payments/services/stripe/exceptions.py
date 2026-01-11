"""
Custom Stripe exception classes and error message mapping.

Provides user-friendly error messages for common Stripe errors while
preserving technical details for logging and debugging.
"""
import stripe
from typing import Dict, Optional


class StripeServiceError(Exception):
    """Base exception for Stripe service layer errors."""
    
    def __init__(self, message: str, stripe_error: Optional[Exception] = None, user_message: Optional[str] = None):
        self.message = message
        self.stripe_error = stripe_error
        self.user_message = user_message or message
        super().__init__(self.message)
    
    def to_dict(self) -> Dict:
        """Return error details as dictionary."""
        return {
            'error': self.__class__.__name__,
            'message': self.message,
            'user_message': self.user_message,
            'stripe_error_type': type(self.stripe_error).__name__ if self.stripe_error else None,
        }


class StripePaymentError(StripeServiceError):
    """Payment creation or processing failed."""
    pass


class StripeRefundError(StripeServiceError):
    """Refund creation or processing failed."""
    pass


class StripeWebhookError(StripeServiceError):
    """Webhook processing failed."""
    pass


class StripeValidationError(StripeServiceError):
    """Validation error before making Stripe API call."""
    pass


# User-friendly error message mapping
STRIPE_ERROR_MESSAGES = {
    # Card errors
    'card_declined': 'Your card was declined. Please try a different payment method.',
    'expired_card': 'Your card has expired. Please use a different card.',
    'incorrect_cvc': 'The security code (CVC) is incorrect. Please check and try again.',
    'insufficient_funds': 'Your card has insufficient funds. Please try a different payment method.',
    'invalid_expiry_month': 'The expiration month is invalid. Please check your card details.',
    'invalid_expiry_year': 'The expiration year is invalid. Please check your card details.',
    'invalid_number': 'The card number is invalid. Please check and try again.',
    'processing_error': 'An error occurred while processing your card. Please try again.',
    
    # Generic errors
    'api_error': 'A payment processing error occurred. Please try again or contact support.',
    'authentication_error': 'Authentication with payment processor failed. Please contact support.',
    'invalid_request_error': 'Invalid payment request. Please contact support.',
    'rate_limit_error': 'Too many requests. Please wait a moment and try again.',
    
    # Refund errors
    'charge_already_refunded': 'This payment has already been refunded.',
    'refund_amount_exceeds_charge': 'The refund amount exceeds the original payment amount.',
}


def map_stripe_error(error: Exception) -> StripeServiceError:
    """
    Map Stripe API exceptions to custom service exceptions with user-friendly messages.
    
    Args:
        error: The Stripe exception to map
        
    Returns:
        StripeServiceError: Mapped exception with user-friendly message
    """
    if isinstance(error, stripe.CardError):
        # Card was declined
        code = error.code if hasattr(error, 'code') else 'card_declined'
        user_message = STRIPE_ERROR_MESSAGES.get(code, STRIPE_ERROR_MESSAGES['card_declined'])
        return StripePaymentError(
            message=f"Card error: {str(error)}",
            stripe_error=error,
            user_message=user_message
        )
    
    elif isinstance(error, stripe.RateLimitError):
        return StripePaymentError(
            message=f"Rate limit error: {str(error)}",
            stripe_error=error,
            user_message=STRIPE_ERROR_MESSAGES['rate_limit_error']
        )
    
    elif isinstance(error, stripe.InvalidRequestError):
        return StripePaymentError(
            message=f"Invalid request: {str(error)}",
            stripe_error=error,
            user_message=STRIPE_ERROR_MESSAGES['invalid_request_error']
        )
    
    elif isinstance(error, stripe.AuthenticationError):
        return StripePaymentError(
            message=f"Authentication error: {str(error)}",
            stripe_error=error,
            user_message=STRIPE_ERROR_MESSAGES['authentication_error']
        )
    
    elif isinstance(error, stripe.APIConnectionError):
        return StripePaymentError(
            message=f"Network error: {str(error)}",
            stripe_error=error,
            user_message="Network error while processing payment. Please try again."
        )
    
    elif isinstance(error, stripe.StripeError):
        return StripePaymentError(
            message=f"Stripe error: {str(error)}",
            stripe_error=error,
            user_message=STRIPE_ERROR_MESSAGES['api_error']
        )
    
    else:
        return StripeServiceError(
            message=f"Unexpected error: {str(error)}",
            stripe_error=error if isinstance(error, Exception) else None,
            user_message="An unexpected error occurred. Please try again or contact support."
        )
