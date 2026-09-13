"""
Order email service.

Builds and dispatches transactional order emails:

  - Order confirmation (Stripe / bank-transfer verified payment)
  - Pending bank-transfer notification (awaiting payment verification)

Usage (from Celery tasks only — do not call send_* methods directly from views):

    from apps.products.email_service import OrderEmailService
    OrderEmailService.send_order_confirmation(order_pk, payment_pk)
    OrderEmailService.send_order_pending_bank_transfer(order_pk, payment_pk)
"""
from __future__ import annotations

import logging

from django.conf import settings

from apps.common.services.email import send_templated_email
from apps.payments.models import Payment
from apps.products.models import Order

logger = logging.getLogger(__name__)

# Internal PaymentMethod.provided_details keys that should never be shown to users.
_INTERNAL_BANK_DETAIL_KEYS = frozenset(
    {"stripe_account_id", "stripe_publishable_key", "stripe_connect_account_id"}
)


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


class OrderEmailService:
    """Service responsible for building context and sending order emails."""

    CONFIRMATION_TEMPLATE = "emails/order_confirmation.html"
    PENDING_TRANSFER_TEMPLATE = "emails/order_pending_bank_transfer.html"
    EVIDENCE_RECEIVED_TEMPLATE = "emails/order_evidence_received.html"

    # ------------------------------------------------------------------
    # Image resolver
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_item_image(item) -> str | None:
        """
        Resolve the best available image URL for an OrderItem.

        Resolution order:
          1. Variant's VARIANT_PHOTO_MAIN resource
          2. Product's PRODUCT_PHOTO_MAIN resource
          3. None — template renders a placeholder block

        Returns None if no image is found or if resolution fails, so the
        email still renders without raising.
        """
        variant = item.product_variant
        if not variant:
            return None

        # 1. Variant main image
        try:
            variant_img = variant.variant_images.filter(tag="VARIANT_PHOTO_MAIN").first()
            if variant_img and getattr(variant_img, "image", None):
                return _make_absolute_url(variant_img.image.url)
        except Exception:
            logger.warning(
                "_resolve_item_image: could not load variant image for variant %s",
                getattr(variant, "variant_id", variant.pk),
            )

        # 2. Fallback: product main image
        try:
            product_img = variant.product.product_images.filter(
                tag="PRODUCT_PHOTO_MAIN"
            ).first()
            if product_img and getattr(product_img, "image", None):
                return _make_absolute_url(product_img.image.url)
        except Exception:
            logger.warning(
                "_resolve_item_image: could not load product image for product %s",
                getattr(getattr(variant, "product", None), "product_id", None),
            )

        return None

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    @classmethod
    def _build_event_block(cls, order) -> dict:
        """
        Construct the shared event / venue section of the template context.

        Accesses the event via ``order.event`` (property: order.attendee.event).
        All relations are handled gracefully so a missing config never blocks
        email delivery.
        """
        event = order.event
        tz = getattr(event, "timezone", None)

        start_dt = event.start_datetime
        end_dt = event.end_datetime
        if tz:
            try:
                start_dt = start_dt.astimezone(tz)
                end_dt = end_dt.astimezone(tz)
            except Exception:
                logger.warning(
                    "_build_event_block: could not convert datetimes to timezone %s "
                    "for event %s",
                    tz,
                    getattr(event, "event_id", None),
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
        except Exception:
            logger.warning(
                "_build_event_block: could not resolve landing image for event %s",
                getattr(event, "event_id", None),
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
    def _build_order_items(cls, order) -> list[dict]:
        """
        Build the list of per-item dicts for the order email templates.

        Resolves variant and product images, and constructs a human-readable
        variant label — e.g. "Medium / #0062ff" — with the hex colour token
        exposed separately for inline colour swatches in HTML.

        Image resolution: VARIANT_PHOTO_MAIN → PRODUCT_PHOTO_MAIN → None.
        """
        items = list(
            order.order_items.select_related(
                "product_variant__product",
            ).order_by("id")
        )

        result: list[dict] = []
        for item in items:
            variant = item.product_variant
            product_title = "Product"
            variant_label = ""
            color_hex = ""
            image_url: str | None = None

            if variant and getattr(variant, "product", None):
                product_title = variant.product.title or "Product"

            if variant:
                # Size: show human-readable name, omit "Not Applicable"
                size_display = (
                    variant.get_size_display()
                    if variant.size and variant.size != "NA"
                    else ""
                )
                # Color: hex string from ColorField (e.g. "#0062ff")
                color_hex = str(variant.color) if variant.color else ""

                label_parts = [p for p in [size_display, color_hex] if p]
                variant_label = " / ".join(label_parts)

                image_url = cls._resolve_item_image(item)

            result.append(
                {
                    "product_title": product_title,
                    "variant_label": variant_label,
                    "color_hex": color_hex,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "image_url": image_url,
                }
            )

        return result

    @classmethod
    def build_confirmation_context(cls, order: Order, payment: Payment) -> dict:
        """
        Build the full template context for ``order_confirmation.html``.

        Fetches all order items, resolves per-item images, and constructs
        the event block so the email includes full event details.
        """
        context = cls._build_event_block(order)
        order_items = cls._build_order_items(order)

        event = order.event
        view_order_url = f"{settings.FRONTEND_URL}/events/{event.url_safe_title}"

        user_display_name = "Guest"
        if order.customer and hasattr(order.customer, "get_display_name"):
            user_display_name = order.customer.get_display_name() or "Guest"

        context.update(
            {
                "order_reference": order.order_reference_id,
                "user_display_name": user_display_name,
                "order_items": order_items,
                "item_count": len(order_items),
                "total_amount": order.total_amount,
                "view_order_url": view_order_url,
            }
        )
        return context

    @classmethod
    def build_pending_bank_transfer_context(cls, order: Order, payment: Payment) -> dict:
        """
        Build the full template context for ``order_pending_bank_transfer.html``.

        Strips internal/Stripe-specific keys from
        ``payment.method.provided_details`` before exposing them to the
        template so only human-readable account details reach the user.
        """
        context = cls._build_event_block(order)
        order_items = cls._build_order_items(order)

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
                    "build_pending_bank_transfer_context: provided_details for payment %s "
                    "is not a dict (type=%s) — skipping bank details in email",
                    payment.payment_reference,
                    type(raw).__name__,
                )

        event = order.event
        view_order_url = f"{settings.FRONTEND_URL}/events/{event.url_safe_title}"

        user_display_name = "Guest"
        if order.customer and hasattr(order.customer, "get_display_name"):
            user_display_name = order.customer.get_display_name() or "Guest"

        context.update(
            {
                "order_reference": order.order_reference_id,
                "user_display_name": user_display_name,
                "order_items": order_items,
                "item_count": len(order_items),
                "total_amount": order.total_amount,
                "bank_transfer_reference": payment.bank_transfer_reference or "",
                "bank_details": bank_details,
                "payment_method_title": (
                    payment.method.title if payment.method else "Bank Transfer"
                ),
                "view_order_url": view_order_url,
            }
        )
        return context

    @classmethod
    def build_evidence_received_context(cls, order: Order, payment: Payment) -> dict:
        """
        Build the template context for ``order_evidence_received.html``.

        Used when the user uploaded bank transfer evidence at checkout time.
        No bank details are included — the user has already transferred.
        """
        context = cls._build_event_block(order)
        order_items = cls._build_order_items(order)

        event = order.event
        view_order_url = f"{settings.FRONTEND_URL}/events/{event.url_safe_title}"

        user_display_name = "Guest"
        if order.customer and hasattr(order.customer, "get_display_name"):
            user_display_name = order.customer.get_display_name() or "Guest"

        context.update(
            {
                "order_reference": order.order_reference_id,
                "user_display_name": user_display_name,
                "order_items": order_items,
                "item_count": len(order_items),
                "total_amount": order.total_amount,
                "view_order_url": view_order_url,
            }
        )
        return context

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    @classmethod
    def send_order_confirmation(cls, order_pk: int | str, payment_pk: int | str) -> bool:
        """
        Render and send the order confirmation email.

        Intended to be called from a Celery task after the order payment has
        committed to the database.

        Args:
            order_pk:   Primary key of the Order.
            payment_pk: Primary key of the Payment.

        Returns:
            True if the email was dispatched without error, False otherwise.
        """
        from apps.products.models import Order
        from apps.payments.models import Payment

        try:
            order = Order.objects.select_related(
                "attendee__event__location__chapter",
                "attendee__event__organisation",
                "customer",
            ).get(pk=order_pk)
        except Order.DoesNotExist:
            logger.error(
                "send_order_confirmation: Order pk=%s not found — email not sent",
                order_pk,
            )
            return False

        try:
            payment = Payment.objects.select_related("method").get(pk=payment_pk)
        except Payment.DoesNotExist:
            logger.error(
                "send_order_confirmation: Payment pk=%s not found — email not sent",
                payment_pk,
            )
            return False

        if not order.customer or not order.customer.email:
            logger.warning(
                "send_order_confirmation: No email address for order %s — skipping",
                order.order_reference_id,
            )
            return False

        context = cls.build_confirmation_context(order, payment)
        event_title = context.get("event_title", "your event")

        return send_templated_email(
            subject=f"Order Confirmed — {event_title}",
            template_name=cls.CONFIRMATION_TEMPLATE,
            context=context,
            recipient_list=[order.customer.email],
        )

    @classmethod
    def send_order_pending_bank_transfer(
        cls, order_pk: int | str, payment_pk: int | str
    ) -> bool:
        """
        Render and send the 'order received, awaiting bank transfer' email.

        Intended to be called from a Celery task immediately after the bank
        transfer checkout completes (payment reserved, order linked).

        Args:
            order_pk:   Primary key of the Order.
            payment_pk: Primary key of the Payment.

        Returns:
            True if the email was dispatched without error, False otherwise.
        """

        try:
            order = Order.objects.select_related(
                "attendee__event__location__chapter",
                "attendee__event__organisation",
                "customer",
            ).get(pk=order_pk)
        except Order.DoesNotExist:
            logger.error(
                "send_order_pending_bank_transfer: Order pk=%s not found — email not sent",
                order_pk,
            )
            return False

        try:
            payment = Payment.objects.select_related("method").get(pk=payment_pk)
        except Payment.DoesNotExist:
            logger.error(
                "send_order_pending_bank_transfer: Payment pk=%s not found — email not sent",
                payment_pk,
            )
            return False

        if not order.customer or not order.customer.email:
            logger.warning(
                "send_order_pending_bank_transfer: No email address for order %s — skipping",
                order.order_reference_id,
            )
            return False

        event_title = order.event.title if order.event else "your event"
        has_evidence = payment.bank_transfer_evidence.exists()

        if has_evidence:
            context = cls.build_evidence_received_context(order, payment)
            return send_templated_email(
                subject=f"Order Received — {event_title} (evidence received, verifying)",
                template_name=cls.EVIDENCE_RECEIVED_TEMPLATE,
                context=context,
                recipient_list=[order.customer.email],
            )

        context = cls.build_pending_bank_transfer_context(order, payment)
        event_title = context.get("event_title", "your event")

        return send_templated_email(
            subject=f"Order Received — {event_title} (awaiting payment)",
            template_name=cls.PENDING_TRANSFER_TEMPLATE,
            context=context,
            recipient_list=[order.customer.email],
        )
