from decimal import Decimal
import logging
from typing import Any, Dict, List

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from djmoney.money import Money

from apps.attendee.models import Attendee
from apps.bookings.models import Booking, Ticket, TicketStatusChoices
from apps.payments.models import PaymentStatusChoices, RefundAssociation, RefundRequest
from apps.products.models import Order, OrderItem, OrderStatusChoices

logger = logging.getLogger(__name__)


class AttendeeRefundService:
    """Orchestrates attendee-scoped refund validation and side effects."""

    @classmethod
    def is_booking_payment(cls, payment) -> bool:
        target = getattr(payment, "target", None)
        return isinstance(target, Booking)

    @classmethod
    def resolve_booking_attendees(cls, payment, attendee_ids: List[str]) -> List[Attendee]:
        if not cls.is_booking_payment(payment):
            raise ValidationError("Attendee selection is only supported for booking-linked payments.")

        booking = payment.target
        queryset = booking.attendees.filter(deleted_at__isnull=True).select_related("booking", "event")
        attendees_by_uuid = {str(a.attendee_id): a for a in queryset}
        missing = [att_id for att_id in attendee_ids if att_id not in attendees_by_uuid]
        if missing:
            raise ValidationError(f"Selected attendees are not in this booking: {', '.join(missing)}")

        return [attendees_by_uuid[att_id] for att_id in attendee_ids]

    @classmethod
    def get_refund_entities(cls, payment, attendees: List[Attendee]) -> Dict[str, List[Any]]:
        attendee_ids = [a.id for a in attendees]
        tickets = list(
            Ticket.objects.filter(attendee_id__in=attendee_ids, payment=payment).select_related("attendee", "package")
        )
        orders = list(
            Order.objects.filter(attendee_id__in=attendee_ids, payment=payment).select_related("attendee")
        )
        return {"tickets": tickets, "orders": orders}

    @classmethod
    def has_used_ticket(cls, payment, attendees: List[Attendee]) -> bool:
        entities = cls.get_refund_entities(payment, attendees)
        return any(ticket.status == TicketStatusChoices.USED for ticket in entities["tickets"])

    @classmethod
    def _ticket_amount(cls, payment, ticket: Ticket) -> Money:
        currency = payment.base_amount.currency
        metadata = payment.metadata or {}
        ticket_breakdown = metadata.get("ticket_breakdown") if isinstance(metadata, dict) else {}
        entry = ticket_breakdown.get(str(ticket.ticket_id), {}) if isinstance(ticket_breakdown, dict) else {}

        amount_str = entry.get("amount")
        if amount_str is not None:
            return Money(Decimal(str(amount_str)), currency)

        if ticket.package and ticket.package.base_amount:
            return Money(ticket.package.base_amount.amount, currency)

        return Money(Decimal("0.00"), currency)

    @classmethod
    def calculate_breakdown(cls, payment, attendees: List[Attendee]) -> Dict[str, Any]:
        entities = cls.get_refund_entities(payment, attendees)
        currency = payment.base_amount.currency
        total = Money(Decimal("0.00"), currency)

        ticket_items = []
        for ticket in entities["tickets"]:
            amount = cls._ticket_amount(payment, ticket)
            total += amount
            ticket_items.append(
                {
                    "ticket_id": str(ticket.ticket_id),
                    "attendee_id": str(ticket.attendee.attendee_id),
                    "amount": str(amount.amount),
                }
            )

        order_items = []
        for order in entities["orders"]:
            amount = Money(order.total_amount.amount, currency)
            total += amount
            order_items.append(
                {
                    "order_id": str(order.order_id),
                    "attendee_id": str(order.attendee.attendee_id) if order.attendee else None,
                    "amount": str(amount.amount),
                }
            )

        return {
            "total": float(total.amount),
            "total_currency": currency.code,
            "tickets": ticket_items,
            "orders": order_items,
            "entity_counts": {"tickets": len(ticket_items), "orders": len(order_items)},
        }

    @classmethod
    def calculate_targeted_booking_product_breakdown(cls, payment, refund_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate and validate targeted booking product-line refund selections."""
        if not cls.is_booking_payment(payment):
            raise ValidationError("Targeted booking product refunds are only supported for booking-linked payments.")

        if not refund_items:
            raise ValidationError("refund_items is required for targeted booking product refunds.")

        booking = payment.target
        attendees = booking.attendees.filter(deleted_at__isnull=True)
        attendees_by_uuid = {str(a.attendee_id): a for a in attendees}

        currency = payment.base_amount.currency
        total = Decimal("0.00")
        grouped_by_order: Dict[str, Dict[str, Any]] = {}
        selected_attendee_ids: List[str] = []
        per_item_details: List[Dict[str, Any]] = []

        for raw_item in refund_items:
            if not isinstance(raw_item, dict):
                raise ValidationError("Each refund_items entry must be an object.")

            attendee_id = str(raw_item.get("attendee_id") or "").strip()
            if not attendee_id:
                raise ValidationError("Each refund_items entry must include attendee_id.")
            if attendee_id not in attendees_by_uuid:
                raise ValidationError(f"Attendee {attendee_id} is not part of this booking.")

            order_item_id = raw_item.get("order_item_id")
            variant_id = str(raw_item.get("variant_id") or "").strip()
            package_product_id = raw_item.get("package_product_id")
            requested_quantity = int(raw_item.get("quantity") or 0)
            if requested_quantity <= 0:
                raise ValidationError("Each refund_items entry must include quantity >= 1.")

            item_qs = OrderItem.objects.select_related(
                "order",
                "order__attendee",
                "product_variant",
                "package_product",
            ).filter(
                order__payment=payment,
                order__attendee=attendees_by_uuid[attendee_id],
            )

            if order_item_id is not None:
                item_qs = item_qs.filter(id=order_item_id)
            if variant_id:
                item_qs = item_qs.filter(product_variant__variant_id=variant_id)
            if package_product_id is not None:
                item_qs = item_qs.filter(package_product_id=package_product_id)

            matches = list(item_qs[:2])
            if len(matches) != 1:
                raise ValidationError(
                    "Could not uniquely resolve selected booking product item. "
                    "Provide attendee_id with order_item_id, or a unique variant/package combination."
                )

            order_item = matches[0]
            if requested_quantity > order_item.quantity:
                raise ValidationError(
                    f"Requested quantity ({requested_quantity}) exceeds purchased quantity "
                    f"({order_item.quantity}) for order item {order_item.id}."
                )

            line_total = (order_item.unit_price.amount * Decimal(requested_quantity)).quantize(Decimal("0.01"))
            total += line_total

            order_id = str(order_item.order.order_id)
            grouped = grouped_by_order.setdefault(
                order_id,
                {
                    "order_id": order_id,
                    "attendee_id": attendee_id,
                    "amount": Decimal("0.00"),
                    "items": [],
                },
            )
            grouped["amount"] += line_total
            grouped["items"].append(
                {
                    "order_item_id": order_item.id,
                    "variant_id": str(order_item.product_variant.variant_id) if order_item.product_variant else None,
                    "package_product_id": order_item.package_product_id,
                    "quantity": requested_quantity,
                    "unit_price": str(order_item.unit_price.amount),
                    "amount": str(line_total),
                    "currency": currency.code,
                }
            )

            per_item_details.append(
                {
                    "order_id": order_id,
                    "order_item_id": order_item.id,
                    "attendee_id": attendee_id,
                    "variant_id": str(order_item.product_variant.variant_id) if order_item.product_variant else None,
                    "package_product_id": order_item.package_product_id,
                    "quantity": requested_quantity,
                    "unit_price": str(order_item.unit_price.amount),
                    "amount": str(line_total),
                    "currency": currency.code,
                }
            )
            selected_attendee_ids.append(attendee_id)

        unique_attendee_ids = list(dict.fromkeys(selected_attendee_ids))
        order_summaries = []
        for order_data in grouped_by_order.values():
            order_summaries.append(
                {
                    "order_id": order_data["order_id"],
                    "attendee_id": order_data["attendee_id"],
                    "amount": str(order_data["amount"].quantize(Decimal("0.01"))),
                    "currency": currency.code,
                    "items": order_data["items"],
                }
            )

        return {
            "scope": "targeted_booking_products",
            "total": float(total.quantize(Decimal("0.01"))),
            "total_currency": currency.code,
            "selected_attendee_ids": unique_attendee_ids,
            "orders": order_summaries,
            "items": per_item_details,
            "entity_counts": {
                "tickets": 0,
                "orders": len(order_summaries),
                "items": len(per_item_details),
            },
        }

    @classmethod
    def calculate_targeted_order_item_breakdown(cls, payment, refund_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate and validate targeted order-item refund selections for non-booking payments."""
        if cls.is_booking_payment(payment):
            raise ValidationError("Use booking-targeted breakdown for booking-linked payments.")

        if not refund_items:
            raise ValidationError("refund_items is required for targeted order refunds.")

        currency = payment.base_amount.currency
        total = Decimal("0.00")
        per_item_details: List[Dict[str, Any]] = []

        for raw_item in refund_items:
            if not isinstance(raw_item, dict):
                raise ValidationError("Each refund_items entry must be an object.")

            order_item_id = raw_item.get("order_item_id")
            requested_quantity = int(raw_item.get("quantity") or 0)
            if not order_item_id:
                raise ValidationError("Each refund_items entry must include order_item_id.")
            if requested_quantity <= 0:
                raise ValidationError("Each refund_items entry must include quantity >= 1.")

            order_item = (
                OrderItem.objects
                .select_related("order")
                .filter(order__payment=payment, id=order_item_id)
                .first()
            )
            if order_item is None:
                raise ValidationError(f"Order item {order_item_id} is not part of this payment.")

            if requested_quantity > order_item.quantity:
                raise ValidationError(
                    f"Requested quantity ({requested_quantity}) exceeds purchased quantity "
                    f"({order_item.quantity}) for order item {order_item.id}."
                )

            line_total = (order_item.unit_price.amount * Decimal(requested_quantity)).quantize(Decimal("0.01"))
            total += line_total

            per_item_details.append(
                {
                    "order_id": str(order_item.order.order_id),
                    "order_item_id": order_item.id,
                    "quantity": requested_quantity,
                    "unit_price": str(order_item.unit_price.amount),
                    "amount": str(line_total),
                    "currency": currency.code,
                }
            )

        return {
            "scope": "targeted_order_items",
            "total": float(total.quantize(Decimal("0.01"))),
            "total_currency": currency.code,
            "items": per_item_details,
            "entity_counts": {
                "tickets": 0,
                "orders": 0,
                "items": len(per_item_details),
            },
        }

    @classmethod
    @transaction.atomic
    def attach_associations(cls, refund_request: RefundRequest) -> None:
        metadata = refund_request.metadata or {}
        refund_scope = metadata.get("refund_scope")
        if refund_scope == "targeted_order_items":
            selected_items = (metadata.get("frozen_breakdown") or {}).get("items") or []
            if not selected_items:
                return

            existing_keys = set(
                RefundAssociation.objects.filter(refund_request=refund_request).values_list("target_type_id", "target_id")
            )
            currency = refund_request.amount.currency

            for item_data in selected_items:
                order_item = (
                    OrderItem.objects
                    .select_related("order")
                    .filter(order__payment=refund_request.payment, id=item_data.get("order_item_id"))
                    .first()
                )
                if order_item is None:
                    continue

                ct_id = ContentType.objects.get_for_model(order_item).id
                key = (ct_id, str(order_item.pk))
                if key in existing_keys:
                    continue

                amount = Decimal(str(item_data.get("amount") or "0")).quantize(Decimal("0.01"))
                if amount <= 0:
                    continue

                refund_request.associate_with(
                    order_item,
                    amount=Money(amount, currency),
                    metadata={
                        "entity": "order_item",
                        "scope": "targeted_order_items",
                        "order_id": item_data.get("order_id"),
                        "quantity": item_data.get("quantity"),
                        "unit_price": item_data.get("unit_price"),
                    },
                )
            return

        if refund_scope == "targeted_booking_products":
            order_summaries = (metadata.get("frozen_breakdown") or {}).get("orders") or []
            if not order_summaries:
                return

            existing_keys = set(
                RefundAssociation.objects.filter(refund_request=refund_request).values_list("target_type_id", "target_id")
            )
            currency = refund_request.amount.currency

            for order_data in order_summaries:
                order = Order.objects.filter(
                    payment=refund_request.payment,
                    order_id=order_data.get("order_id"),
                ).select_related("attendee").first()
                if not order:
                    continue
                ct_id = ContentType.objects.get_for_model(order).id
                key = (ct_id, str(order.pk))
                if key in existing_keys:
                    continue

                amount = Decimal(str(order_data.get("amount") or "0")).quantize(Decimal("0.01"))
                if amount <= 0:
                    continue

                refund_request.associate_with(
                    order,
                    amount=Money(amount, currency),
                    metadata={
                        "attendee_id": order_data.get("attendee_id"),
                        "entity": "order",
                        "scope": "targeted_booking_products",
                        "targeted_items": order_data.get("items") or [],
                    },
                )
            return

        attendee_ids = metadata.get("selected_attendee_ids") or []
        if not attendee_ids:
            return

        attendees = cls.resolve_booking_attendees(refund_request.payment, attendee_ids)
        entities = cls.get_refund_entities(refund_request.payment, attendees)
        currency = refund_request.amount.currency

        existing_keys = set(
            RefundAssociation.objects.filter(refund_request=refund_request).values_list("target_type_id", "target_id")
        )

        for ticket in entities["tickets"]:
            amount = cls._ticket_amount(refund_request.payment, ticket)
            if amount.amount <= 0:
                continue
            ct_id = ContentType.objects.get_for_model(ticket).id
            key = (ct_id, str(ticket.pk))
            if key in existing_keys:
                continue
            refund_request.associate_with(
                ticket,
                amount=Money(amount.amount, currency),
                metadata={"attendee_id": str(ticket.attendee.attendee_id), "entity": "ticket"},
            )

        for order in entities["orders"]:
            amount = Money(order.total_amount.amount, currency)
            if amount.amount <= 0:
                continue
            ct_id = ContentType.objects.get_for_model(order).id
            key = (ct_id, str(order.pk))
            if key in existing_keys:
                continue
            refund_request.associate_with(
                order,
                amount=amount,
                metadata={
                    "attendee_id": str(order.attendee.attendee_id) if order.attendee else None,
                    "entity": "order",
                },
            )

    @classmethod
    @transaction.atomic
    def apply_verify_block(cls, refund_request: RefundRequest) -> Dict[str, int]:
        # Ensure we have concrete associations before enforcing verify-stage blocking.
        cls.attach_associations(refund_request)
        metadata = refund_request.metadata or {}
        refund_scope = metadata.get("refund_scope")
        is_targeted_scope = refund_scope in {"targeted_booking_products", "targeted_order_items"}

        blocked_orders = 0
        for association in refund_request.associations.select_related("target_type"):
            target = association.target_object
            if isinstance(target, Order) and target.status in {
                OrderStatusChoices.PROCESSING,
                OrderStatusChoices.COMPLETED,
            }:
                target.transition_to(OrderStatusChoices.PENDING_REFUND)
                blocked_orders += 1

        attendee_ids = metadata.get("selected_attendee_ids") or []
        if attendee_ids and not is_targeted_scope:
            selected_orders = Order.objects.filter(
                payment=refund_request.payment,
                attendee__attendee_id__in=attendee_ids,
            )
            for order in selected_orders:
                if order.status in {OrderStatusChoices.PROCESSING, OrderStatusChoices.COMPLETED}:
                    order.transition_to(OrderStatusChoices.PENDING_REFUND)
                    blocked_orders += 1

        metadata["verify_blocked_at"] = refund_request.verified_updated_at.isoformat() if refund_request.verified_updated_at else None
        metadata["verify_blocked_order_count"] = blocked_orders
        refund_request.metadata = metadata
        refund_request.save(update_fields=["metadata"])
        return {"blocked_orders": blocked_orders}

    @classmethod
    @transaction.atomic
    def apply_process_finalize(cls, refund_request: RefundRequest) -> Dict[str, int]:
        finalized_tickets = 0
        finalized_orders = 0
        metadata = refund_request.metadata or {}
        refund_scope = metadata.get("refund_scope")
        is_targeted_scope = refund_scope in {"targeted_booking_products", "targeted_order_items"}
        order_item_refund_quantities: Dict[int, int] = {}

        for association in refund_request.associations.select_related("target_type"):
            target = association.target_object

            if isinstance(target, Ticket):
                if target.status != TicketStatusChoices.CANCELLED:
                    target.status = TicketStatusChoices.CANCELLED
                    target.uses = 0
                    target.save(update_fields=["status", "uses"])
                    finalized_tickets += 1
                continue

            if isinstance(target, Order):
                if target.status in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
                    continue
                if target.status != OrderStatusChoices.REFUNDED:
                    target.transition_to(OrderStatusChoices.REFUNDED)
                    finalized_orders += 1
                continue

            if isinstance(target, OrderItem):
                quantity = association.metadata.get("quantity") if isinstance(association.metadata, dict) else None
                try:
                    refunded_qty = int(quantity)
                except (TypeError, ValueError):
                    refunded_qty = 0
                if refunded_qty <= 0:
                    refunded_qty = target.quantity
                order_item_refund_quantities[target.id] = order_item_refund_quantities.get(target.id, 0) + refunded_qty

        if refund_scope == "targeted_order_items" and order_item_refund_quantities:
            order_ids = list(
                OrderItem.objects
                .filter(id__in=order_item_refund_quantities.keys())
                .values_list("order_id", flat=True)
                .distinct()
            )
            for order in Order.objects.filter(id__in=order_ids).prefetch_related("order_items"):
                order_items = list(order.order_items.all())
                if not order_items:
                    continue

                is_fully_refunded = all(
                    order_item_refund_quantities.get(item.id, 0) >= item.quantity
                    for item in order_items
                )
                if not is_fully_refunded:
                    continue

                if order.status in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
                    continue
                order.transition_to(OrderStatusChoices.REFUNDED)
                finalized_orders += 1

        attendee_ids = metadata.get("selected_attendee_ids") or []
        if attendee_ids and not is_targeted_scope:
            selected_tickets = Ticket.objects.filter(
                payment=refund_request.payment,
                attendee__attendee_id__in=attendee_ids,
            )
            for ticket in selected_tickets:
                if ticket.status != TicketStatusChoices.CANCELLED:
                    ticket.status = TicketStatusChoices.CANCELLED
                    ticket.uses = 0
                    ticket.save(update_fields=["status", "uses"])
                    finalized_tickets += 1

            selected_orders = Order.objects.filter(
                payment=refund_request.payment,
                attendee__attendee_id__in=attendee_ids,
            )
            for order in selected_orders:
                if order.status not in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
                    order.transition_to(OrderStatusChoices.REFUNDED)
                    finalized_orders += 1

        metadata["process_finalized_at"] = refund_request.processed_at.isoformat() if refund_request.processed_at else None
        metadata["process_finalized_ticket_count"] = finalized_tickets
        metadata["process_finalized_order_count"] = finalized_orders
        refund_request.metadata = metadata
        refund_request.save(update_fields=["metadata"])

        logger.info(
            "Refund finalized",
            extra={
                "refund_tracking_reference": refund_request.tracking_reference,
                "payment_reference": refund_request.payment.payment_reference,
                "finalized_tickets": finalized_tickets,
                "finalized_orders": finalized_orders,
            },
        )

        return {"finalized_tickets": finalized_tickets, "finalized_orders": finalized_orders}

    @classmethod
    def determine_payment_status_after_process(cls, refund_request: RefundRequest) -> str:
        if refund_request.is_full:
            return PaymentStatusChoices.REFUNDED
        return PaymentStatusChoices.PARTIALLY_REFUNDED

    @classmethod
    def determine_payment_status_after_verify(cls, refund_request: RefundRequest) -> str:
        if refund_request.is_full:
            return PaymentStatusChoices.PENDING_REFUND
        return PaymentStatusChoices.PARTIALLY_REFUNDED
