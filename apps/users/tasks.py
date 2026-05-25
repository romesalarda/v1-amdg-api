"""
Celery tasks for the users app.

All user-related transactional email tasks are defined here so that the
task registry is cleanly separated from service logic.
"""
import logging

from celery import shared_task

from apps.users.email_service import UserEmailService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_welcome_email(self, user_pk: int) -> str:
    """
    Send the welcome email to a newly registered user.

    Includes up to 3 upcoming OPEN events with landing images, a link to
    the user's dashboard, and a link to browse all events.

    Args:
        user_pk: Integer primary key of the CommunityUser instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info("send_welcome_email: user_pk=%s", user_pk)
    try:
        success = UserEmailService.send_welcome(user_pk)
        if success:
            return f"welcome email sent | user_pk={user_pk}"
        return f"welcome email skipped (no recipient or user not found) | user_pk={user_pk}"
    except Exception as exc:
        logger.exception("send_welcome_email: unexpected error for user_pk=%s", user_pk)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_verification_email(self, user_pk: int, verification_url: str) -> str:
    """
    Send the email address verification link to a user.

    Should be dispatched immediately after registration (and on resend
    requests) via ``transaction.on_commit`` to ensure the user record has
    committed to the database before the task runs.

    Args:
        user_pk:          Integer primary key of the CommunityUser instance.
        verification_url: Fully-qualified frontend URL carrying uid+token query params.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info(
        "send_email_verification_email: user_pk=%s", user_pk
    )
    try:
        success = UserEmailService.send_email_verification(user_pk, verification_url)
        if success:
            return f"verification email sent | user_pk={user_pk}"
        return (
            f"verification email skipped (no recipient, user not found, or "
            f"invalid URL) | user_pk={user_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_email_verification_email: unexpected error for user_pk=%s", user_pk
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_changed_email(self, user_pk: int) -> str:
    """
    Send a 'your password was changed' security notification.

    Dispatched after a successful authenticated password change so the
    account owner is alerted even if the change was made by a third party.

    Args:
        user_pk: Integer primary key of the CommunityUser instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info("send_password_changed_email: user_pk=%s", user_pk)
    try:
        success = UserEmailService.send_password_changed(user_pk)
        if success:
            return f"password changed email sent | user_pk={user_pk}"
        return (
            f"password changed email skipped (no recipient or user not found) "
            f"| user_pk={user_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_password_changed_email: unexpected error for user_pk=%s", user_pk
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_confirmation_email(self, user_pk: int) -> str:
    """
    Send a 'your password has been successfully reset' confirmation email.

    Dispatched after a successful password reset so the user knows their
    new credentials are active and can sign in.

    Args:
        user_pk: Integer primary key of the CommunityUser instance.

    Returns:
        A short status string for Celery result inspection.
    """
    logger.info("send_password_reset_confirmation_email: user_pk=%s", user_pk)
    try:
        success = UserEmailService.send_password_reset_confirmation(user_pk)
        if success:
            return f"password reset confirmation email sent | user_pk={user_pk}"
        return (
            f"password reset confirmation email skipped (no recipient or user not found) "
            f"| user_pk={user_pk}"
        )
    except Exception as exc:
        logger.exception(
            "send_password_reset_confirmation_email: unexpected error for user_pk=%s",
            user_pk,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, user_id: int, reset_url: str) -> str:
    """
    Send the password reset link email.

    Uses the branded HTML template at templates/emails/password_reset.html.
    Dispatched from the forgot-password endpoint via transaction.on_commit.

    Args:
        user_id:   Integer primary key of the CommunityUser instance.
        reset_url: Fully-qualified frontend URL carrying uid+token query params.

    Returns:
        A short status string for Celery result inspection.
    """
    from apps.common.email import send_templated_email
    from django.contrib.auth import get_user_model
    from django.conf import settings

    logger.info("send_password_reset_email: user_id=%s", user_id)
    User = get_user_model()

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("send_password_reset_email: User pk=%s not found", user_id)
        return f"skipped (user not found) | user_id={user_id}"

    if not user.email:
        logger.warning("send_password_reset_email: no email for user pk=%s", user_id)
        return f"skipped (no email) | user_id={user_id}"

    try:
        expiry_hours = max(
            1, getattr(settings, "PASSWORD_RESET_TIMEOUT", 3600) // 3600
        )
        success = send_templated_email(
            subject="Reset your AMDG password",
            template_name="emails/password_reset.html",
            context={
                "user_display_name": (
                    user.get_display_name()
                    if hasattr(user, "get_display_name")
                    else user.get_full_name() or user.email
                ),
                "reset_url": reset_url,
                "expiry_hours": expiry_hours,
            },
            recipient_list=[user.email],
        )
        if success:
            return f"password reset email sent | user_id={user_id}"
        return f"password reset email skipped (send failed) | user_id={user_id}"
    except Exception as exc:
        logger.exception(
            "send_password_reset_email: unexpected error for user_id=%s", user_id
        )
        raise self.retry(exc=exc)


@shared_task
def cleanup_old_sessions() -> str:
    """Clean up expired sessions from the database (scheduled via Celery Beat)."""
    from django.core.management import call_command

    call_command("clearsessions")
    return "Old sessions cleaned up"
