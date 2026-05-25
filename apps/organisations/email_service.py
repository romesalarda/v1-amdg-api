"""
Organisations email service.

Builds and dispatches transactional sponsorship emails:

  - Payment confirmation (Stripe / bank-transfer verified)

Usage (from Celery tasks only — do not call send_* methods directly from views):

    from apps.organisations.email_service import SponsorshipEmailService
    SponsorshipEmailService.send_sponsorship_payment_confirmation(sponsor_pk, payment_pk)
"""
from __future__ import annotations

import logging

from django.conf import settings

from apps.common.email import send_templated_email

logger = logging.getLogger(__name__)


def _make_absolute_url(url: str) -> str:
    """Ensure *url* is an absolute URL suitable for use inside an email."""
    if not url:
        return url
    if url.startswith(("http://", "https://", "data:")):
        return url
    backend_url = getattr(settings, "BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{backend_url}/{url.lstrip('/')}"


class SponsorshipEmailService:
    """Service responsible for building context and sending sponsorship emails."""

    CONFIRMATION_TEMPLATE = "emails/sponsorship_payment_confirmation.html"

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    @classmethod
    def _build_event_block(cls, event) -> dict:
        """Construct the shared event / venue section of the template context."""
        tz = getattr(event, "timezone", None)
        start_dt = event.start_datetime
        if tz:
            try:
                start_dt = start_dt.astimezone(tz)
            except Exception:
                logger.warning(
                    "Could not convert event datetime to timezone %s for event %s",
                    tz,
                    event.event_id,
                )

        venue_parts: list[str] = []
        location = getattr(event, "location", None)
        if location:
            venue_parts.append(location.area_name)
            chapter = getattr(location, "chapter", None)
            if chapter and getattr(chapter, "chapter_name", None):
                venue_parts.append(chapter.chapter_name)
        venue_string = ", ".join(venue_parts) if venue_parts else "Venue TBC"

        landing_image_url: str | None = None
        try:
            main_image = event.main_landing_image
            if main_image and main_image.image:
                landing_image_url = _make_absolute_url(main_image.image.url)
        except Exception:
            logger.warning(
                "Could not resolve landing image URL for event %s", event.event_id
            )

        organisation_name = "AMDG"
        if event.organisation:
            organisation_name = getattr(event.organisation, "title", "AMDG") or "AMDG"

        return {
            "event_title": event.title,
            "event_start": start_dt,
            "venue_string": venue_string,
            "organisation_name": organisation_name,
            "landing_image_url": landing_image_url,
        }

    @classmethod
    def _build_confirmation_context(cls, sponsor, payment) -> dict:
        """Build the full template context for sponsorship_payment_confirmation.html."""
        context = cls._build_event_block(sponsor.event)

        package = sponsor.package
        package_name = package.package_name if package else None

        method = payment.method
        method_title = getattr(method, "title", "Payment") if method else "Payment"

        user = payment.user
        user_display_name = user.get_display_name() if user else "Sponsor"

        context.update({
            "user_display_name": user_display_name,
            "sponsor_name": sponsor.name,
            "sponsor_organisation": sponsor.organisation.title if sponsor.organisation else sponsor.name,
            "package_name": package_name,
            "payment_reference": payment.payment_reference,
            "payment_amount": str(payment.base_amount),
            "payment_method_title": method_title,
        })
        return context

    # ------------------------------------------------------------------
    # Public send methods
    # ------------------------------------------------------------------

    @classmethod
    def send_sponsorship_payment_confirmation(cls, sponsor_pk: int, payment_pk: int) -> bool:
        """
        Send a sponsorship payment confirmation email.

        Args:
            sponsor_pk: Integer primary key of the EventSponsor instance.
            payment_pk: Integer primary key of the Payment instance.

        Returns:
            True if the email was dispatched successfully, False otherwise.
        """
        from apps.organisations.models import EventSponsor
        from apps.payments.models import Payment

        try:
            sponsor = EventSponsor.objects.select_related(
                "event",
                "event__location",
                "event__location__chapter",
                "event__organisation",
                "organisation",
                "package",
            ).get(pk=sponsor_pk)
        except EventSponsor.DoesNotExist:
            logger.error(
                "send_sponsorship_payment_confirmation: EventSponsor pk=%s not found",
                sponsor_pk,
            )
            return False

        try:
            payment = Payment.objects.select_related("method", "user").get(pk=payment_pk)
        except Payment.DoesNotExist:
            logger.error(
                "send_sponsorship_payment_confirmation: Payment pk=%s not found",
                payment_pk,
            )
            return False

        recipient = payment.user
        if not recipient or not getattr(recipient, "email", None):
            logger.warning(
                "send_sponsorship_payment_confirmation: no recipient email for sponsor_pk=%s payment_pk=%s",
                sponsor_pk,
                payment_pk,
            )
            return False

        context = cls._build_confirmation_context(sponsor, payment)

        return send_templated_email(
            subject=f"Sponsorship Confirmed — {context['event_title']}",
            template_name=cls.CONFIRMATION_TEMPLATE,
            context=context,
            recipient_list=[recipient.email],
        )
