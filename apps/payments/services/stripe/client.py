"""
Stripe API client wrapper with test/live mode handling.

Provides a centralized configuration and initialization for the Stripe SDK.
Reads configuration from Django settings and initializes the Stripe library.
"""
import stripe
from django.conf import settings
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class StripeClient:
    """
    Wrapper for Stripe API client configuration.
    
    Handles initialization of Stripe SDK with appropriate API keys based on
    test/live mode. All Stripe service modules should use this client for
    consistent configuration.
    """
    
    _initialized = False
    _test_mode = None
    
    @classmethod
    def initialize(cls) -> None:
        """
        Initialize Stripe SDK with API keys from Django settings.
        
        Sets stripe.api_key and caches test mode status. Safe to call multiple
        times - will only initialize once.
        """
        if cls._initialized:
            return
        
        # Get configuration from settings
        cls._test_mode = getattr(settings, 'STRIPE_TEST_MODE', True)
        api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        
        if not api_key:
            logger.warning(
                "Stripe API key not configured. Payment processing will fail. "
                "Set STRIPE_SECRET_KEY_TEST or STRIPE_SECRET_KEY_LIVE in environment."
            )
        
        stripe.api_key = api_key
        cls._initialized = True
        
        logger.info(f"Stripe initialized in {'TEST' if cls._test_mode else 'LIVE'} mode")
    
    @classmethod
    def is_test_mode(cls) -> bool:
        """
        Check if Stripe is in test mode.
        
        Returns:
            bool: True if using test keys, False if using live keys
        """
        if not cls._initialized:
            cls.initialize()
        return cls._test_mode
    
    @classmethod
    def get_publishable_key(cls) -> str:
        """
        Get the appropriate publishable key for frontend use.
        
        Returns:
            str: Stripe publishable key (test or live based on mode)
        """
        if not cls._initialized:
            cls.initialize()
        
        return getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '')
    
    @classmethod
    def get_webhook_secret(cls) -> str:
        """
        Get the webhook signing secret for signature verification.
        
        Returns:
            str: Stripe webhook secret
        """
        return getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
    
    @classmethod
    def get_api_version(cls) -> Optional[str]:
        """
        Get the Stripe API version being used.
        
        Returns:
            Optional[str]: API version or None if using default
        """
        return getattr(settings, 'STRIPE_API_VERSION', None)


# Initialize on module import
StripeClient.initialize()
