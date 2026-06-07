"""
Refund email service.

Builds and dispatches transactional refund confirmation emails:

  - Booking refund (covers tickets and booking-linked order products)
  - Standalone order refund

Usage (from Celery tasks only — do not call send_* methods directly from views):

    from apps.payments.email_service import RefundEmailService
    RefundEmailService.send_booking_refund(refund_request_pk)
    RefundEmailService.send_order_refund(refund_request_pk)
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

from apps.common.email import send_templated_email

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


class RefundEmailService:
    """Service responsible for building context and sending refund emails."""

    BOOKING_REFUND_TEMPLATE = "emails/booking_refund.html"
    ORDER_REFUND_TEMPLATE = "emails/order_refund.html"

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
        """
        variant = item.product_variant
        if not variant:
            return None

        try:
            variant_img = variant.variant_images.filter(tag="VARIANT_PHOTO_MAIN").first()
            if variant_img and getattr(variant_img, "image", None):
                return _make_absolute_url(variant_img.image.url)
        except Exception:
            logger.warning(
                "_resolve_item_image: could not load variant image for variant %s",
                getattr(variant, "variant_id", variant.pk),
            )

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
    # Event block builder
    # ------------------------------------------------------------------

    @classmethod
    def _build_event_block(cls, payment) -> dict:
        """
        Construct the shared event / venue section of the template context.

        Reads the event directly from ``payment.event``.
        """
        event = payment.event
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

        venue_string = (
            event.primary_venue.name
            if event.primary_venue and event.primary_venue.name
            else "Venue TBC"
        )

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

    # ------------------------------------------------------------------
    # Refund association collectors
    # ------------------------------------------------------------------

    @classmethod
    def _collect_refunded_ticket_pks(cls, refund_request) -> set:
        """
        Return the set of Ticket primary keys present in refund associations.
        """
        from apps.bookings.models import Ticket

        refunded_pks: set = set()
        for association in refund_request.associations.select_related("target_type").all():
            target = association.target_object
            if isinstance(target, Ticket):
                refunded_pks.add(target.pk)
        return refunded_pks

    @classmethod
    def _collect_refunded_order_item_data(cls, refund_request) -> dict:
        """
        Return a dict mapping OrderItem primary key → dict with ``quantity_refunded``
        and ``amount`` for each OrderItem association.

        If multiple associations exist for the same OrderItem, quantities are summed.
        """
        from apps.products.models import OrderItem

        result: dict = {}
        for association in refund_request.associations.select_related("target_type").all():
            target = association.target_object
            if isinstance(target, OrderItem):
                raw_qty = None
                if isinstance(association.metadata, dict):
                    raw_qty = association.metadata.get("quantity")
                try:
                    qty = int(raw_qty)
                except (TypeError, ValueError):
                    qty = target.quantity

                existing = result.get(target.pk)
                if existing:
                    existing["quantity_refunded"] = existing["quantity_refunded"] + qty
                    existing["amount"] = existing["amount"] + association.amount
                else:
                    result[target.pk] = {
                        "quantity_refunded": qty,
                        "amount": association.amount,
                    }
        return result

    @classmethod
    def _collect_refunded_order_ids(cls, refund_request) -> set:
        """
        Return the set of Order primary keys that are directly associated with
        this refund request (i.e. the whole Order is considered refunded).
        """
        from apps.products.models import Order

        refunded_ids: set = set()
        for association in refund_request.associations.select_related("target_type").all():
            target = association.target_object
            if isinstance(target, Order):
                refunded_ids.add(target.pk)
        return refunded_ids

    # ------------------------------------------------------------------
    # Order item list builder (shared by both context builders)
    # ------------------------------------------------------------------

    @classmethod
    def _build_order_items_list(
        cls,
        order,
        refunded_order_item_data: dict,
        order_is_fully_refunded: bool,
    ) -> list[dict]:
        """
        Build the per-item list for an order, annotating each item with
        ``is_refunded`` and ``quantity_refunded``.
        """
        items = list(
            order.order_items.select_related("product_variant__product").order_by("id")
        )

        result: list[dict] = []
        for item in items:
            variant = item.product_variant
            product_title = "Product"
            variant_label = ""
            color_hex = ""

            if variant and getattr(variant, "product", None):
                product_title = variant.product.title or "Product"

            if variant:
                size_display = (
                    variant.get_size_display()
                    if variant.size and variant.size != "NA"
                    else ""
                )
                color_hex = str(variant.color) if variant.color else ""
                label_parts = [p for p in [size_display, color_hex] if p]
                variant_label = " / ".join(label_parts)

            image_url = cls._resolve_item_image(item)

            item_refund_data = refunded_order_item_data.get(item.pk)
            if order_is_fully_refunded:
                is_refunded = True
                quantity_refunded = item.quantity
            elif item_refund_data:
                is_refunded = True
                quantity_refunded = item_refund_data["quantity_refunded"]
            else:
                is_refunded = False
                quantity_refunded = 0

            result.append(
                {
                    "product_title": product_title,
                    "variant_label": variant_label,
                    "color_hex": color_hex,
                    "quantity": item.quantity,
                    "quantity_refunded": quantity_refunded,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "image_url": image_url,
                    "is_refunded": is_refunded,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    @classmethod
    def build_booking_refund_context(cls, refund_request, payment) -> dict:
        """
        Build the full template context for ``booking_refund.html``.

        Loads all tickets and orders attached to the payment, annotating
        each with ``is_refunded`` so the template can highlight them.
        """
        from apps.bookings.models import Booking
        from apps.products.models import Order

        context = cls._build_event_block(payment)

        refunded_ticket_pks = cls._collect_refunded_ticket_pks(refund_request)
        refunded_order_item_data = cls._collect_refunded_order_item_data(refund_request)
        refunded_order_ids = cls._collect_refunded_order_ids(refund_request)

        # ── Tickets ──────────────────────────────────────────────────
        all_tickets = list(
            payment.tickets.select_related("attendee", "ticket_type").order_by("issued_at")
        )
        ticket_data: list[dict] = []
        for ticket in all_tickets:
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
                    "is_refunded": ticket.pk in refunded_ticket_pks,
                }
            )

        # ── Orders ───────────────────────────────────────────────────
        all_orders = list(
            Order.objects.filter(payment=payment)
            .prefetch_related("order_items__product_variant__product")
            .order_by("id")
        )
        order_data: list[dict] = []
        for order in all_orders:
            order_is_fully_refunded = order.pk in refunded_order_ids
            items = cls._build_order_items_list(
                order, refunded_order_item_data, order_is_fully_refunded
            )
            any_item_refunded = any(i["is_refunded"] for i in items)
            order_data.append(
                {
                    "order_reference": order.order_reference_id,
                    "total_amount": order.total_amount,
                    "is_fully_refunded": order_is_fully_refunded,
                    "has_any_refunded": any_item_refunded or order_is_fully_refunded,
                    "items": items,
                }
            )

        # ── Booking reference ─────────────────────────────────────────
        booking_reference = ""
        try:
            booking = payment.target
            if isinstance(booking, Booking):
                booking_reference = booking.booking_reference
        except Exception:
            logger.warning(
                "build_booking_refund_context: could not resolve booking for payment %s",
                payment.payment_reference,
            )

        event = payment.event
        view_booking_url = (
            f"{settings.FRONTEND_URL}/events/{event.url_safe_title}"
            f"/b/{booking_reference}"
            if booking_reference
            else f"{settings.FRONTEND_URL}/events/{event.url_safe_title}"
        )

        user_display_name = "Guest"
        if payment.user and hasattr(payment.user, "get_display_name"):
            user_display_name = payment.user.get_display_name() or "Guest"

        refund_count_tickets = len(refunded_ticket_pks)
        refund_count_orders = len(refunded_order_ids) + sum(
            1 for v in refunded_order_item_data.values()
        )

        context.update(
            {
                "booking_reference": booking_reference,
                "user_display_name": user_display_name,
                "refund_reference": refund_request.tracking_reference,
                "refund_amount": refund_request.amount,
                "is_full_refund": refund_request.is_full,
                "ticket_data": ticket_data,
                "ticket_count": len(all_tickets),
                "order_data": order_data,
                "refund_count_tickets": refund_count_tickets,
                "view_booking_url": view_booking_url,
            }
        )
        return context

    @classmethod
    def build_order_refund_context(cls, refund_request, payment) -> dict:
        """
        Build the full template context for ``order_refund.html``.

        Loads the standalone order and all its items, annotating each with
        ``is_refunded`` so the template can highlight refunded rows.
        """
        from apps.products.models import Order

        context = cls._build_event_block(payment)

        refunded_order_item_data = cls._collect_refunded_order_item_data(refund_request)
        refunded_order_ids = cls._collect_refunded_order_ids(refund_request)

        # The payment target is the Order directly for standalone order payments.
        order = None
        try:
            target = payment.target
            if isinstance(target, Order):
                order = Order.objects.prefetch_related(
                    "order_items__product_variant__product"
                ).get(pk=target.pk)
        except Exception:
            logger.warning(
                "build_order_refund_context: could not resolve order for payment %s",
                payment.payment_reference,
            )

        order_reference = ""
        total_amount = None
        order_items: list[dict] = []
        if order:
            order_reference = order.order_reference_id
            total_amount = order.total_amount
            order_is_fully_refunded = order.pk in refunded_order_ids
            order_items = cls._build_order_items_list(
                order, refunded_order_item_data, order_is_fully_refunded
            )

        event = payment.event
        view_order_url = f"{settings.FRONTEND_URL}/events/{event.url_safe_title}"

        user_display_name = "Guest"
        if payment.user and hasattr(payment.user, "get_display_name"):
            user_display_name = payment.user.get_display_name() or "Guest"

        context.update(
            {
                "order_reference": order_reference,
                "user_display_name": user_display_name,
                "refund_reference": refund_request.tracking_reference,
                "refund_amount": refund_request.amount,
                "is_full_refund": refund_request.is_full,
                "order_items": order_items,
                "item_count": len(order_items),
                "total_amount": total_amount,
                "view_order_url": view_order_url,
            }
        )
        return context

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    @classmethod
    def send_booking_refund(cls, refund_request_pk: int | str) -> bool:
        """
        Render and send the booking refund email.

        Intended to be called from a Celery task after the refund has been
        committed to the database.

        Args:
            refund_request_pk: Primary key of the RefundRequest.

        Returns:
            True if the email was dispatched without error, False otherwise.
        """
        from apps.payments.models import RefundRequest, Payment

        try:
            refund_request = (
                RefundRequest.objects.select_related("payment__user", "payment__event")
                .get(pk=refund_request_pk)
            )
        except RefundRequest.DoesNotExist:
            logger.error(
                "send_booking_refund: RefundRequest pk=%s not found", refund_request_pk
            )
            return False

        payment = refund_request.payment
        recipient = getattr(payment.user, "email", None) if payment.user else None
        if not recipient:
            logger.warning(
                "send_booking_refund: no recipient email for payment %s",
                payment.payment_reference,
            )
            return False

        context = cls.build_booking_refund_context(refund_request, payment)
        subject = f"Refund Processed — {context.get('event_title', 'Your Event')}"
        success = send_templated_email(
            subject=subject,
            template_name=cls.BOOKING_REFUND_TEMPLATE,
            context=context,
            recipient_list=[recipient],
        )
        if success:
            logger.info(
                "send_booking_refund: email sent to %s for refund %s",
                recipient,
                refund_request.tracking_reference,
            )
        return success

    @classmethod
    def send_order_refund(cls, refund_request_pk: int | str) -> bool:
        """
        Render and send the standalone order refund email.

        Intended to be called from a Celery task after the refund has been
        committed to the database.

        Args:
            refund_request_pk: Primary key of the RefundRequest.

        Returns:
            True if the email was dispatched without error, False otherwise.
        """
        from apps.payments.models import RefundRequest, Payment

        try:
            refund_request = (
                RefundRequest.objects.select_related("payment__user", "payment__event")
                .get(pk=refund_request_pk)
            )
        except RefundRequest.DoesNotExist:
            logger.error(
                "send_order_refund: RefundRequest pk=%s not found", refund_request_pk
            )
            return False

        payment = refund_request.payment
        recipient = getattr(payment.user, "email", None) if payment.user else None
        if not recipient:
            logger.warning(
                "send_order_refund: no recipient email for payment %s",
                payment.payment_reference,
            )
            return False

        context = cls.build_order_refund_context(refund_request, payment)
        subject = f"Refund Processed — {context.get('event_title', 'Your Order')}"
        success = send_templated_email(
            subject=subject,
            template_name=cls.ORDER_REFUND_TEMPLATE,
            context=context,
            recipient_list=[recipient],
        )
        if success:
            logger.info(
                "send_order_refund: email sent to %s for refund %s",
                recipient,
                refund_request.tracking_reference,
            )
        return success
