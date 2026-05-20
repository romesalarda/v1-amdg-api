"""
Shared email utilities for the AMDG platform.

All emails sent by the platform should go through send_templated_email so that
branding, logging, and backend switching are handled in one place.
"""
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def send_templated_email(
    subject: str,
    template_name: str,
    context: dict,
    recipient_list: list[str],
    from_email: str | None = None,
) -> bool:
    """
    Render an HTML email template and send it.

    A plain-text version is derived automatically by stripping HTML tags so
    that all email clients receive a readable fallback.

    Args:
        subject:        Email subject line.
        template_name:  Path to the Django template (e.g. 'emails/password_reset.html').
        context:        Template context dictionary.
        recipient_list: List of recipient email addresses.
        from_email:     Sender address; defaults to settings.DEFAULT_FROM_EMAIL.

    Returns:
        True if the email was dispatched without error, False otherwise.
    """
    from_email = from_email or settings.DEFAULT_FROM_EMAIL

    try:
        html_body = render_to_string(template_name, context)
        text_body = strip_tags(html_body)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=recipient_list,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()

        logger.info(
            "Email sent | subject=%r | to=%s | template=%s",
            subject,
            ", ".join(recipient_list),
            template_name,
        )
        return True

    except Exception:
        logger.exception(
            "Failed to send email | subject=%r | to=%s | template=%s",
            subject,
            ", ".join(recipient_list),
            template_name,
        )
        return False
