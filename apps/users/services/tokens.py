"""
Custom token generators for the users app.
"""
from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """
    Token generator for email address verification.

    Produces a signed, time-limited token that is bound to the user's
    current ``email_verified`` state.  The token automatically invalidates
    once the user verifies their email address (because ``email_verified``
    flips to ``True``, changing the hash value), preventing replay attacks.

    It also invalidates if the user's email address or password changes,
    matching Django's built-in password-reset token behaviour.

    Usage::

        from apps.users.tokens import email_verification_token

        token = email_verification_token.make_token(user)
        is_valid = email_verification_token.check_token(user, token)
    """

    def _make_hash_value(self, user, timestamp: int) -> str:
        # Include email_verified so the token is single-use: once the user
        # verifies, the hash value changes and the token is rejected.
        return (
            str(user.pk)
            + str(user.password)
            + str(user.email)
            + str(user.email_verified)
            + str(timestamp)
        )


# Module-level singleton — import this rather than instantiating the class.
email_verification_token = EmailVerificationTokenGenerator()
