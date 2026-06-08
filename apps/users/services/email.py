"""
User email service.

Builds and dispatches transactional emails for user account events:

  - Password changed notification
  - Password reset confirmation
  - Welcome email (with upcoming OPEN events)
  - Email address verification

Usage (from Celery tasks only — never call send_* from views directly):

    from apps.users.email_service import UserEmailService
    UserEmailService.send_password_changed(user_pk)
    UserEmailService.send_password_reset_confirmation(user_pk)
    UserEmailService.send_welcome(user_pk)
    UserEmailService.send_email_verification(user_pk, verification_url)
"""
from __future__ import annotations

import base64
import logging

from django.conf import settings
from django.utils import timezone

from apps.common.services.email import send_templated_email

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# EMAIL_VERIFICATION_TIMEOUT is in seconds; default matches PASSWORD_RESET_TIMEOUT.
_EMAIL_VERIFY_TIMEOUT_SECS: int = 3600  # 1 hour

# Number of upcoming OPEN events to show in the welcome email.
_WELCOME_MAX_EVENTS: int = 3


def _make_absolute_url(url: str) -> str:
    """Return *url* as an absolute URL suitable for email clients.

    Django's ImageField.url returns a relative path when local storage is
    active.  Email clients cannot resolve relative URLs, so we prepend
    ``settings.BACKEND_URL``.  S3-hosted URLs are already absolute.
    """
    if not url:
        return url
    if url.startswith(("http://", "https://", "data:")):
        return url
    backend_url = getattr(settings, "BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{backend_url}/{url.lstrip('/')}"


class UserEmailService:
    """
    Service responsible for building context and sending user-related
    transactional emails.

    All public methods are classmethods so no instance state is required.
    Model imports are deferred to the method body to prevent circular imports.
    """

    PASSWORD_CHANGED_TEMPLATE = "emails/password_changed.html"
    PASSWORD_RESET_CONFIRMATION_TEMPLATE = "emails/password_reset_confirmation.html"
    WELCOME_TEMPLATE = "emails/welcome.html"
    EMAIL_VERIFICATION_TEMPLATE = "emails/email_verification.html"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _get_user(cls, user_pk: int | str):
        """Fetch the user by pk.  Returns the user instance or None."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            return User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            logger.error(
                "UserEmailService: User pk=%s not found — email not sent", user_pk
            )
            return None

    @classmethod
    def _base_context(cls, user) -> dict:
        """Common context keys present in every user email."""
        return {
            "user_display_name": (
                user.get_display_name()
                if hasattr(user, "get_display_name")
                else (user.get_full_name() or user.email)
            ),
            "user_email": user.email,
        }

    # ------------------------------------------------------------------
    # send_password_changed
    # ------------------------------------------------------------------

    @classmethod
    def send_password_changed(cls, user_pk: int | str) -> bool:
        """Send 'your password was changed' notification.

        Returns True if email dispatched without error, False otherwise.
        """
        user = cls._get_user(user_pk)
        if user is None:
            return False

        if not user.email:
            logger.warning(
                "send_password_changed: no email for user pk=%s — skipping", user_pk
            )
            return False

        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        context = cls._base_context(user)
        context.update(
            {
                "changed_at": timezone.now(),
                "dashboard_url": f"{frontend_url}/dashboard",
            }
        )

        return send_templated_email(
            subject="Your AMDG password was changed",
            template_name=cls.PASSWORD_CHANGED_TEMPLATE,
            context=context,
            recipient_list=[user.email],
        )

    # ------------------------------------------------------------------
    # send_password_reset_confirmation
    # ------------------------------------------------------------------

    @classmethod
    def send_password_reset_confirmation(cls, user_pk: int | str) -> bool:
        """Send 'your password has been reset' confirmation.

        Returns True if email dispatched without error, False otherwise.
        """
        user = cls._get_user(user_pk)
        if user is None:
            return False

        if not user.email:
            logger.warning(
                "send_password_reset_confirmation: no email for user pk=%s — skipping",
                user_pk,
            )
            return False

        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        context = cls._base_context(user)
        context.update(
            {
                "reset_at": timezone.now(),
                "login_url": f"{frontend_url}/login",
            }
        )

        return send_templated_email(
            subject="Your AMDG password has been reset",
            template_name=cls.PASSWORD_RESET_CONFIRMATION_TEMPLATE,
            context=context,
            recipient_list=[user.email],
        )

    # ------------------------------------------------------------------
    # send_welcome
    # ------------------------------------------------------------------

    @classmethod
    def _build_event_card(cls, event) -> dict:
        """Build a minimal context dict for one upcoming event card."""
        from django.utils import timezone as tz_module

        tz = getattr(event, "timezone", None)
        start_dt = event.start_datetime
        if tz:
            try:
                start_dt = start_dt.astimezone(tz)
            except Exception:
                pass

        # Venue string
        venue_parts: list[str] = []
        location = getattr(event, "location", None)
        if location:
            venue_parts.append(location.area_name)
            chapter = getattr(location, "chapter", None)
            if chapter and getattr(chapter, "chapter_name", None):
                venue_parts.append(chapter.chapter_name)
        venue_string = ", ".join(venue_parts) if venue_parts else ""

        # Landing image URL
        landing_image_url: str | None = None
        try:
            main_image = event.main_landing_image
            if main_image and main_image.image:
                landing_image_url = _make_absolute_url(main_image.image.url)
        except Exception:
            logger.warning(
                "send_welcome: could not resolve landing image for event pk=%s",
                event.pk,
            )

        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        return {
            "title": event.title,
            "start_datetime": start_dt,
            "venue_string": venue_string,
            "short_description": event.short_description or "",
            "landing_image_url": landing_image_url,
            "event_url": f"{frontend_url}/events/{event.url_safe_title}",
        }

    @classmethod
    def send_welcome(cls, user_pk: int | str) -> bool:
        """Send the welcome email with up to 3 upcoming OPEN events.

        Returns True if email dispatched without error, False otherwise.
        """
        from apps.events.models.events import Event, EventStatusChoices

        user = cls._get_user(user_pk)
        if user is None:
            return False

        if not user.email:
            logger.warning(
                "send_welcome: no email for user pk=%s — skipping", user_pk
            )
            return False

        now = timezone.now()
        raw_events = (
            Event.objects.filter(
                status=EventStatusChoices.OPEN,
                start_datetime__gt=now,
            )
            .select_related("location__chapter")
            .order_by("start_datetime")[: _WELCOME_MAX_EVENTS]
        )

        upcoming_events = [cls._build_event_card(ev) for ev in raw_events]

        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        context = cls._base_context(user)
        context.update(
            {
                "upcoming_events": upcoming_events,
                "dashboard_url": f"{frontend_url}/dashboard",
                "events_url": f"{frontend_url}/events",
            }
        )

        return send_templated_email(
            subject="Welcome to AMDG — you're in!",
            template_name=cls.WELCOME_TEMPLATE,
            context=context,
            recipient_list=[user.email],
        )

    # ------------------------------------------------------------------
    # send_email_verification
    # ------------------------------------------------------------------

    @classmethod
    def send_email_verification(
        cls, user_pk: int | str, verification_url: str
    ) -> bool:
        """Send the email verification link.

        Args:
            user_pk:          Primary key of the user.
            verification_url: Fully-qualified frontend URL carrying uid+token.

        Returns True if email dispatched without error, False otherwise.
        """
        if not verification_url or not verification_url.startswith(("http://", "https://")):
            logger.error(
                "send_email_verification: invalid verification_url=%r for user pk=%s",
                verification_url,
                user_pk,
            )
            return False

        user = cls._get_user(user_pk)
        if user is None:
            return False

        if not user.email:
            logger.warning(
                "send_email_verification: no email for user pk=%s — skipping", user_pk
            )
            return False

        expiry_hours = max(
            1,
            getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", _EMAIL_VERIFY_TIMEOUT_SECS)
            // 3600,
        )

        context = cls._base_context(user)
        context.update(
            {
                "verification_url": verification_url,
                "expiry_hours": expiry_hours,
            }
        )

        return send_templated_email(
            subject="Verify your AMDG email address",
            template_name=cls.EMAIL_VERIFICATION_TEMPLATE,
            context=context,
            recipient_list=[user.email],
        )
