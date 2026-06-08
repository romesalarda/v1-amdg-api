"""
Booking email service.

Builds and dispatches transactional booking confirmation emails:

  - Confirmation with per-attendee ticket QR cards (Stripe / bank-transfer verified)
  - Pending bank-transfer notification (awaiting payment verification)

Usage (from Celery tasks only — do not call send_* methods directly from views):

    from apps.bookings.email_service import BookingEmailService
    BookingEmailService.send_booking_confirmation(booking_pk, payment_pk)
    BookingEmailService.send_booking_pending_bank_transfer(booking_pk, payment_pk)
"""
from __future__ import annotations

import base64
import logging

from django.conf import settings

from apps.common.services.email import send_templated_email
from qr_code.qrcode.maker import make_qr_code_image
from qr_code.qrcode.utils import QRCodeOptions

from ..models import Booking
from apps.payments.models import Payment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level QR options (reused for every ticket in a request)
# ---------------------------------------------------------------------------


def _make_absolute_url(url: str) -> str:
    """
    Ensure *url* is an absolute URL suitable for use inside an email.

    Django's ImageField.url returns a relative path (``/media/...``) when local
    storage is active.  Email clients cannot resolve relative URLs, so we
    prepend settings.BACKEND_URL.  When S3 storage is active, url is already
    absolute and is returned unchanged.
    """
    if not url:
        return url
    if url.startswith(("http://", "https://", "data:")):
        return url
    backend_url = getattr(settings, "BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{backend_url}/{url.lstrip('/')}"


_QR_OPTIONS = QRCodeOptions(size="M", image_format="PNG", error_correction="M")

# Internal PaymentMethod.provided_details keys that should never be shown to users.
_INTERNAL_BANK_DETAIL_KEYS = frozenset(
    {"stripe_account_id", "stripe_publishable_key", "stripe_connect_account_id"}
)


class BookingEmailService:
    """Service responsible for building context and sending booking emails."""

    CONFIRMATION_TEMPLATE = "emails/booking_confirmation.html"
    PENDING_TRANSFER_TEMPLATE = "emails/booking_pending_bank_transfer.html"
    EVIDENCE_RECEIVED_TEMPLATE = "emails/booking_evidence_received.html"

    # ------------------------------------------------------------------
    # QR code helper
    # ------------------------------------------------------------------

    @staticmethod
    def generate_ticket_qr_datauri(ticket_code: str) -> str | None:
        """
        Generate a base64-encoded PNG data URI for *ticket_code*.

        Returns None if generation fails so the email still renders
        (ticket code text is always shown as a fallback).
        """
        if not ticket_code:
            logger.warning("generate_ticket_qr_datauri called with empty ticket_code")
            return None

        try:
            image_bytes = make_qr_code_image(ticket_code, _QR_OPTIONS)
            b64 = base64.b64encode(image_bytes).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except Exception:
            logger.exception(
                "Failed to generate QR code data URI for ticket_code=%s", ticket_code
            )
            return None

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    @classmethod
    def _build_event_block(cls, booking: Booking) -> dict:
        """
        Construct the shared event / venue section of the template context.

        Handles missing relations (location, organisation, landing image)
        gracefully so a bad event config never blocks email delivery.
        """
        event = booking.event
        tz = getattr(event, "timezone", None)

        start_dt = event.start_datetime
        end_dt = event.end_datetime
        if tz:
            try:
                start_dt = start_dt.astimezone(tz)
                end_dt = end_dt.astimezone(tz)
            except Exception:
                logger.warning(
                    "Could not convert event datetimes to timezone %s for event %s",
                    tz,
                    event.event_id,
                )

        # Build venue string from AreaLocation → ChapterLocation
        # venue_parts: list[str] = []
        # location = getattr(event, "location", None)
        # if location:
        #     venue_parts.append(location.area_name)
        #     chapter = getattr(location, "chapter", None)
        #     if chapter and getattr(chapter, "chapter_name", None):
        #         venue_parts.append(chapter.chapter_name)
        # venue_string = ", ".join(venue_parts) if venue_parts else "Venue TBC"

        venue_string = event.primary_venue.name if event.primary_venue and event.primary_venue.name else "Venue TBC"

        # Resolve event landing image URL
        landing_image_url: str | None = None
        try:
            main_image = event.main_landing_image
            if main_image and main_image.image:
                landing_image_url = _make_absolute_url(main_image.image.url)
            else:
                logger.info(
                    "Event %s has no main landing image — skipping image in email",
                    event.event_id,
                )
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
            "event_end": end_dt,
            "event_timezone_name": str(tz) if tz else "UTC",
            "venue_string": venue_string,
            "organisation_name": organisation_name,
            "landing_image_url": landing_image_url,
        }

    @classmethod
    def build_confirmation_context(cls, booking: Booking, payment: Payment) -> dict:
        """
        Build the full template context for *booking_confirmation.html*.

        Fetches all tickets attached to *payment* and generates a QR data URI
        for each one.  A missing or failed QR falls back gracefully to None so
        the template can fall back to displaying the ticket code as plain text.
        """
        context = cls._build_event_block(booking)

        tickets = list(
            payment.tickets.select_related("attendee", "ticket_type").order_by("issued_at")
        )

        ticket_data: list[dict] = []
        for ticket in tickets:
            attendee = ticket.attendee
            attendee_name = "Attendee"
            if attendee:
                first = (getattr(attendee, "first_name", "") or "").strip()
                last = (getattr(attendee, "last_name", "") or "").strip()
                full_name = f"{first} {last}".strip()
                if not full_name:
                    full_name = getattr(attendee, "email", "") or "Attendee"
                attendee_name = full_name

            ticket_type_title = "Ticket"
            if ticket.ticket_type:
                ticket_type_title = ticket.ticket_type.title or "Ticket"

            ticket_data.append(
                {
                    "ticket_code": ticket.ticket_code,
                    "ticket_type_title": ticket_type_title,
                    "attendee_name": attendee_name,
                    "qr_data_uri": cls.generate_ticket_qr_datauri(ticket.ticket_code),
                }
            )

        view_tickets_url = (
            f"{settings.FRONTEND_URL}/events/{booking.event.url_safe_title}"
            f"/b/{booking.booking_reference}"
        )

        user_display_name = "Guest"
        if booking.made_by and hasattr(booking.made_by, "get_display_name"):
            user_display_name = booking.made_by.get_display_name() or "Guest"

        context.update(
            {
                "booking_reference": booking.booking_reference,
                "user_display_name": user_display_name,
                "ticket_data": ticket_data,
                "ticket_count": len(ticket_data),
                "view_tickets_url": view_tickets_url,
            }
        )
        return context

    @classmethod
    def build_pending_bank_transfer_context(cls, booking: Booking, payment: Payment) -> dict:
        """
        Build the full template context for *booking_pending_bank_transfer.html*.

        Strips internal/Stripe-specific keys from
        ``payment.method.provided_details`` before exposing them to the
        template so only human-readable account details reach the user.
        """
        context = cls._build_event_block(booking)

        # Sanitise PaymentMethod.provided_details for display
        bank_details: dict = {}
        if payment.method and payment.method.provided_details:
            raw = payment.method.provided_details
            if isinstance(raw, dict):
                bank_details = {
                    k: v
                    for k, v in raw.items()
                    if k not in _INTERNAL_BANK_DETAIL_KEYS
                    and v not in (None, "", [])
                }
            else:
                logger.warning(
                    "payment.method.provided_details for payment %s is not a dict (type=%s); "
                    "skipping bank details in email",
                    payment.payment_reference,
                    type(raw).__name__,
                )

        view_booking_url = (
            f"{settings.FRONTEND_URL}/events/{booking.event.url_safe_title}"
            f"/b/{booking.booking_reference}"
        )

        user_display_name = "Guest"
        if booking.made_by and hasattr(booking.made_by, "get_display_name"):
            user_display_name = booking.made_by.get_display_name() or "Guest"

        context.update(
            {
                "booking_reference": booking.booking_reference,
                "user_display_name": user_display_name,
                "bank_transfer_reference": payment.bank_transfer_reference or "",
                "bank_details": bank_details,
                "payment_method_title": (
                    payment.method.title if payment.method else "Bank Transfer"
                ),
                "view_booking_url": view_booking_url,
            }
        )
        return context

    @classmethod
    def build_evidence_received_context(cls, booking: Booking, payment: Payment) -> dict:
        """
        Build the template context for *booking_evidence_received.html*.

        Used when the user uploaded bank transfer evidence at checkout time.
        No bank details are included — the user has already transferred.
        """
        context = cls._build_event_block(booking)

        view_booking_url = (
            f"{settings.FRONTEND_URL}/events/{booking.event.url_safe_title}"
            f"/b/{booking.booking_reference}"
        )

        user_display_name = "Guest"
        if booking.made_by and hasattr(booking.made_by, "get_display_name"):
            user_display_name = booking.made_by.get_display_name() or "Guest"

        context.update(
            {
                "booking_reference": booking.booking_reference,
                "user_display_name": user_display_name,
                "view_booking_url": view_booking_url,
            }
        )
        return context

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    @classmethod
    def send_booking_confirmation(cls, booking_pk: int | str, payment_pk: int | str) -> bool:
        """
        Render and send the booking confirmation email (tickets included).

        Intended to be called from a Celery task after ticket creation has
        committed to the database.

        Args:
            booking_pk: Primary key of the Booking.
            payment_pk: Primary key of the Payment (used to fetch tickets).

        Returns:
            True if the email was dispatched without error, False otherwise.
        """
        
        try:
            booking = (
                Booking.objects.select_related(
                    "event__location__chapter",
                    "event__organisation",
                    "made_by",
                ).get(pk=booking_pk)
            )
        except Booking.DoesNotExist:
            logger.error(
                "send_booking_confirmation: Booking pk=%s not found — email not sent",
                booking_pk,
            )
            return False

        try:
            payment = Payment.objects.select_related("method").get(pk=payment_pk)
        except Payment.DoesNotExist:
            logger.error(
                "send_booking_confirmation: Payment pk=%s not found — email not sent",
                payment_pk,
            )
            return False

        if not booking.made_by or not booking.made_by.email:
            logger.warning(
                "send_booking_confirmation: No email address for booking %s — skipping",
                booking.booking_reference,
            )
            return False

        context = cls.build_confirmation_context(booking, payment)
        event_title = context.get("event_title", "your event")

        return send_templated_email(
            subject=f"You're In! Your booking for {event_title} is confirmed",
            template_name=cls.CONFIRMATION_TEMPLATE,
            context=context,
            recipient_list=[booking.made_by.email],
        )

    @classmethod
    def send_booking_pending_bank_transfer(
        cls, booking_pk: int | str, payment_pk: int | str
    ) -> bool:
        """
        Render and send the 'booking received, awaiting bank transfer' email.

        Intended to be called from a Celery task immediately after the booking
        has been created but before payment is verified.

        Args:
            booking_pk: Primary key of the Booking.
            payment_pk: Primary key of the Payment.

        Returns:
            True if the email was dispatched without error, False otherwise.
        """
        from apps.bookings.models import Booking
        from apps.payments.models import Payment

        try:
            booking = (
                Booking.objects.select_related(
                    "event__location__chapter",
                    "event__organisation",
                    "made_by",
                ).get(pk=booking_pk)
            )
        except Booking.DoesNotExist:
            logger.error(
                "send_booking_pending_bank_transfer: Booking pk=%s not found — email not sent",
                booking_pk,
            )
            return False

        try:
            payment = Payment.objects.select_related("method").get(pk=payment_pk)
        except Payment.DoesNotExist:
            logger.error(
                "send_booking_pending_bank_transfer: Payment pk=%s not found — email not sent",
                payment_pk,
            )
            return False

        if not booking.made_by or not booking.made_by.email:
            logger.warning(
                "send_booking_pending_bank_transfer: No email address for booking %s — skipping",
                booking.booking_reference,
            )
            return False

        event_title = booking.event.title if booking.event else "your event"
        has_evidence = payment.bank_transfer_evidence.exists()

        if has_evidence:
            context = cls.build_evidence_received_context(booking, payment)
            return send_templated_email(
                subject=f"Booking received — {event_title} (evidence received, verifying)",
                template_name=cls.EVIDENCE_RECEIVED_TEMPLATE,
                context=context,
                recipient_list=[booking.made_by.email],
            )

        context = cls.build_pending_bank_transfer_context(booking, payment)
        event_title = context.get("event_title", "your event")

        return send_templated_email(
            subject=f"Booking received — {event_title} (awaiting payment)",
            template_name=cls.PENDING_TRANSFER_TEMPLATE,
            context=context,
            recipient_list=[booking.made_by.email],
        )
