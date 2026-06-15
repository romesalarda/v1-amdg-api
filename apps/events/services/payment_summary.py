"""
Payment summary service for event bookings.

Centralises the orchestration logic for building the unified payment summary
payload used by the ``my-payment-summary`` event action.  Extracted from the
EventViewSet to keep the viewset thin and make the logic independently testable.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.shortcuts import get_object_or_404

from apps.payments.models import PaymentStatusChoices


class EventPaymentSummaryService:
    """
    Builds the unified payment summary payload for a booking within an event.

    Usage::

        payload = EventPaymentSummaryService.build_for_booking(
            booking=booking,
            event=event,
            attendee_filter=attendee_filter,  # UUID string or None
        )
        serializer = EventMyPaymentSummarySerializer(payload, context=...)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def build_for_booking(
        cls,
        booking,
        event,
        attendee_filter: str | None = None,
    ) -> dict:
        """
        Return the full payment summary dict for *booking* in *event*.

        Parameters
        ----------
        booking:
            The Booking instance to summarise.
        event:
            The Event instance the booking belongs to.
        attendee_filter:
            Optional UUID string identifying a specific attendee.  When
            provided only payments related to that attendee are included in
            the ``attendee_payments`` section.

        Returns
        -------
        dict
            Structured payload ready for ``EventMyPaymentSummarySerializer``.
        """
        from apps.products.models.orders import Order

        booking_attendees = booking.attendees.filter(event=event)

        booking_payments_qs = (
            booking.payments.select_related("method", "target_type")
            .order_by("-created_at")
        )

        order_qs = (
            Order.objects.filter(
                attendee__booking=booking,
                attendee__event=event,
                payment__isnull=False,
            )
            .select_related(
                "payment__method",
                "payment__target_type",
                "attendee",
                "attendee__booking",
            )
            .order_by("-created_at")
        )

        if attendee_filter:
            order_qs = order_qs.filter(attendee__attendee_id=attendee_filter)

        # Build a lookup: payment_id -> [order, ...]
        related_orders_by_payment_id: dict[str, list] = {}
        for order in order_qs:
            if order.payment is None:
                continue
            related_orders_by_payment_id.setdefault(
                str(order.payment.payment_id), []
            ).append(order)

        attendee = None
        if attendee_filter:
            attendee = get_object_or_404(booking_attendees, attendee_id=attendee_filter)

        # ---- booking-level payments ----
        booking_payment_items = [
            cls._serialize_payment_item(
                payment=payment,
                source="BOOKING",
                related_orders=[
                    cls._serialize_order_context(o)
                    for o in related_orders_by_payment_id.get(
                        str(payment.payment_id), []
                    )
                ],
                attendee=attendee,
                summary_context={
                    "section": "booking_payments",
                    "primary_source": "booking",
                },
            )
            for payment in booking_payments_qs
        ]

        canonical_payment_ids = {str(item["payment_id"]) for item in booking_payment_items}

        # Merge extra order contexts into already-canonical booking payments
        for order in order_qs:
            if order.payment is None:
                continue
            payment_id = str(order.payment.payment_id)
            if payment_id not in canonical_payment_ids:
                continue
            booking_item = next(
                (i for i in booking_payment_items if str(i["payment_id"]) == payment_id),
                None,
            )
            if booking_item is not None:
                cls._append_unique_order(booking_item, cls._serialize_order_context(order))

        # ---- shop-order payments (not already canonical) ----
        shop_payment_items = [
            cls._serialize_payment_item(
                payment=order.payment,
                source="SHOP_ORDER",
                order=order,
                attendee=order.attendee,
                related_orders=[cls._serialize_order_context(order)],
                summary_context={
                    "section": "shop_payments",
                    "primary_source": "shop_order",
                },
            )
            for order in order_qs
            if order.payment is not None
            and str(order.payment.payment_id) not in canonical_payment_ids
        ]

        # ---- attendee-specific slice of shop payments ----
        attendee_payment_items: list[dict] = []
        if attendee_filter:
            attendee_payment_items = [
                item
                for item in shop_payment_items
                if item.get("attendee_id") == attendee_filter
            ]

        # ---- deduplicated canonical list ----
        canonical_items: list[dict] = []
        seen_ids: set[str] = set()
        for item in booking_payment_items + shop_payment_items:
            pid = str(item["payment_id"])
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            canonical_items.append(item)

        outstanding_items = [i for i in canonical_items if i.get("is_outstanding")]
        outstanding_total = cls._sum_amounts(outstanding_items)

        return {
            "booking_reference": booking.booking_reference,
            "attendee_filter": attendee_filter,
            "totals": {
                "total_payments": len(canonical_items),
                "outstanding_payments": len(outstanding_items),
                "booking_outstanding_payments": sum(
                    1 for i in booking_payment_items if i.get("is_outstanding")
                ),
                "shop_outstanding_payments": sum(
                    1 for i in shop_payment_items if i.get("is_outstanding")
                ),
                "booking_payments_count": len(booking_payment_items),
                "shop_payments_count": len(shop_payment_items),
                "attendee_payments_count": len(attendee_payment_items),
                "total_outstanding_amount": f"{outstanding_total:.2f}",
            },
            "booking_payments": booking_payment_items,
            "shop_payments": shop_payment_items,
            "attendee_payments": attendee_payment_items,
            "outstanding_payments": outstanding_items,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_payment_item(
        payment,
        source: str,
        order=None,
        attendee=None,
        related_orders: list | None = None,
        summary_context: dict | None = None,
    ) -> dict:
        """Serialise a single payment record into the summary item format."""
        amount = None
        amount_value = None
        currency = None
        original_amount = getattr(payment, "original_amount", None)
        total_refunded_amount = getattr(payment, "total_refunded_amount", None)

        if getattr(payment, "base_amount", None):
            amount = str(payment.final_amount)
            amount_value = str(payment.final_amount.amount)
            currency = str(payment.final_amount.currency)

            if attendee is not None:
                metadata = payment.metadata or {}
                for item in metadata.get("attendee_selections", []):
                    if item.get("attendee_id") == str(attendee.attendee_id):
                        amount = str(item.get("frozen_price", amount))
                        amount_value = str(Decimal(item.get("price", amount_value)))
                        break

        method = getattr(payment, "method", None)

        booking = None
        target_type = getattr(payment, "target_type", None)
        if target_type and target_type.model == "booking":
            booking = payment.target
        elif (
            order is not None
            and getattr(order, "attendee", None)
            and getattr(order.attendee, "booking", None)
        ):
            booking = order.attendee.booking

        related_orders = related_orders or []
        summary_context = summary_context or {}

        return {
            "payment_id": payment.payment_id,
            "payment_reference": payment.payment_reference,
            "status": payment.status,
            "amount": amount,
            "amount_value": amount_value,
            "original_amount": str(original_amount) if original_amount else None,
            "total_refunded_amount": (
                str(total_refunded_amount) if total_refunded_amount else None
            ),
            "currency": currency,
            "created_at": payment.created_at,
            "method_type": getattr(method, "method_type", None),
            "method_title": getattr(method, "title", None),
            "provided_details": getattr(method, "provided_details", None),
            "bank_reference": payment.bank_transfer_reference,
            "source": source,
            "is_outstanding": payment.status
            in [PaymentStatusChoices.DRAFTING, PaymentStatusChoices.PENDING],
            "descriptor": target_type.model if target_type else None,
            "target_type": target_type.model if target_type else None,
            "target_id": str(payment.target_id) if payment.target_id is not None else None,
            "booking_id": str(booking.id) if booking else None,
            "booking_reference": booking.booking_reference if booking else None,
            "order_id": getattr(order, "order_id", None),
            "order_reference": getattr(order, "order_reference_id", None),
            "order_status": getattr(order, "status", None),
            "attendee_id": getattr(attendee, "attendee_id", None),
            "attendee_display_id": getattr(attendee, "attendee_display_id", None),
            "attendee_name": getattr(attendee, "full_name", None),
            "related_orders": related_orders,
            "summary_context": {
                **summary_context,
                "source": source,
                "target_type": target_type.model if target_type else None,
                "target_id": (
                    str(payment.target_id) if payment.target_id is not None else None
                ),
            },
        }

    @staticmethod
    def _serialize_order_context(order) -> dict:
        """Return a lightweight order summary dict for embedding in payment items."""
        attendee = order.attendee
        attendee_booking = getattr(attendee, "booking", None) if attendee else None
        return {
            "order_id": str(order.order_id),
            "order_reference": order.order_reference_id,
            "order_status": order.status,
            "total_amount": str(order.total_amount) if order.total_amount else None,
            "total_amount_value": (
                str(order.total_amount.amount) if order.total_amount else None
            ),
            "booking_id": str(attendee_booking.id) if attendee_booking else None,
            "booking_reference": (
                attendee_booking.booking_reference if attendee_booking else None
            ),
            "attendee_id": str(attendee.attendee_id) if attendee else None,
            "attendee_display_id": getattr(attendee, "attendee_display_id", None),
            "attendee_name": getattr(attendee, "full_name", None),
        }

    @staticmethod
    def _append_unique_order(item: dict, order_context: dict) -> None:
        """Append *order_context* to item['related_orders'] if not already present."""
        related = item.setdefault("related_orders", [])
        if not any(
            existing.get("order_id") == order_context["order_id"]
            for existing in related
        ):
            related.append(order_context)

    @staticmethod
    def _sum_amounts(items: list[dict]) -> Decimal:
        """Sum ``amount_value`` across *items*, ignoring unparseable values."""
        total = Decimal("0.00")
        for item in items:
            try:
                total += Decimal(str(item.get("amount_value") or ""))
            except InvalidOperation:
                continue
        return total
