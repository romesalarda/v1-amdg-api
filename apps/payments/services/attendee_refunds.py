from decimal import Decimal
import logging
from typing import Any, Dict, List

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from djmoney.money import Money

from apps.attendee.models import Attendee
from apps.bookings.models import Booking, Ticket, TicketStatusChoices
from apps.common.models import VerificationStatus
from apps.payments.models import PaymentStatusChoices, RefundAssociation, RefundRequest
from apps.payments.models.donations import Donation
from apps.products.models import Order, OrderItem, OrderStatusChoices, OrderItemStatusChoices, RefundRollbackLog
from apps.organisations.models import EventSponsor

from apps.events.services.notifications import create_notification, NotificationPriorityChoices, NotificationTypeChoices

logger = logging.getLogger(__name__)


class AttendeeRefundService:
    """Orchestrates attendee-scoped refund validation and side effects."""

    ROLLBACK_SNAPSHOT_KEY = "rollback_snapshot"

    TARGET_KIND_BOOKING = "booking"
    TARGET_KIND_ORDER = "order"
    TARGET_KIND_TICKET = "ticket"
    TARGET_KIND_DONATION = "donation"
    TARGET_KIND_SPONSORSHIP = "sponsorship"
    TARGET_KIND_NONE = "none"
    TARGET_KIND_UNSUPPORTED = "unsupported"

    FULL_REFUND_ONLY_TARGET_KINDS = {
        TARGET_KIND_DONATION,
        TARGET_KIND_SPONSORSHIP,
        TARGET_KIND_TICKET,
        TARGET_KIND_NONE,
    }

    ITEMIZED_REFUND_TARGET_KINDS = {
        TARGET_KIND_BOOKING,
        TARGET_KIND_ORDER,
    }

    REFUND_SCOPE_TARGETED_ORDER_ITEMS = "targeted_order_items"
    REFUND_SCOPE_TARGETED_BOOKING_PRODUCTS = "targeted_booking_products"
    REFUND_SCOPE_HYBRID_BOOKING = "hybrid_booking_attendees_and_products"

    TARGETED_REFUND_SCOPES = {
        REFUND_SCOPE_TARGETED_ORDER_ITEMS,
        REFUND_SCOPE_TARGETED_BOOKING_PRODUCTS,
        REFUND_SCOPE_HYBRID_BOOKING,
    }

    @classmethod
    def get_payment_target_kind(cls, payment) -> str:
        target = getattr(payment, "target", None)
        if target is None:
            return cls.TARGET_KIND_NONE
        if isinstance(target, Booking):
            return cls.TARGET_KIND_BOOKING
        if isinstance(target, Order):
            return cls.TARGET_KIND_ORDER
        if isinstance(target, Ticket):
            return cls.TARGET_KIND_TICKET
        if isinstance(target, Donation):
            return cls.TARGET_KIND_DONATION
        if isinstance(target, EventSponsor):
            return cls.TARGET_KIND_SPONSORSHIP
        return cls.TARGET_KIND_UNSUPPORTED

    @classmethod
    def assert_supported_payment_target(cls, payment) -> str:
        target_kind = cls.get_payment_target_kind(payment)
        if target_kind == cls.TARGET_KIND_UNSUPPORTED:
            raise ValidationError("Refunds are not supported for this payment target type.")
        return target_kind

    @classmethod
    def is_full_refund_only_target_kind(cls, target_kind: str) -> bool:
        return target_kind in cls.FULL_REFUND_ONLY_TARGET_KINDS

    @classmethod
    def supports_itemized_refunds(cls, payment) -> bool:
        return cls.get_payment_target_kind(payment) in cls.ITEMIZED_REFUND_TARGET_KINDS

    @classmethod
    def calculate_full_target_breakdown(cls, payment) -> Dict[str, Any]:
        """Build frozen context for full refunds that are target-level only."""
        target_kind = cls.assert_supported_payment_target(payment)
        if target_kind not in {
            cls.TARGET_KIND_ORDER,
            cls.TARGET_KIND_DONATION,
            cls.TARGET_KIND_SPONSORSHIP,
            cls.TARGET_KIND_TICKET,
            cls.TARGET_KIND_NONE,
        }:
            raise ValidationError("Full-target refund context is not available for this payment type.")

        total = Decimal(str(payment.base_amount.amount)).quantize(Decimal("0.01"))
        return {
            "scope": "full_target",
            "target_kind": target_kind,
            "total": float(total),
            "total_currency": payment.base_amount.currency.code,
            "items": [],
            "entity_counts": {
                "tickets": 0,
                "orders": 0,
                "items": 0,
            },
        }

    @classmethod
    def is_booking_payment(cls, payment) -> bool:
        return cls.get_payment_target_kind(payment) == cls.TARGET_KIND_BOOKING

    @classmethod
    def _transition_order_to_pending_refund(cls, order: Order) -> bool:
        if order.status in {OrderStatusChoices.PENDING_REFUND, OrderStatusChoices.REFUNDED, OrderStatusChoices.CANCELLED}:
            return False
        if order.status == OrderStatusChoices.DRAFT:
            order.transition_to(OrderStatusChoices.PENDING)
            order.transition_to(OrderStatusChoices.PENDING_REFUND)
            return True
        if order.status == OrderStatusChoices.PENDING:
            order.transition_to(OrderStatusChoices.PENDING_REFUND)
            return True
        if order.status in {OrderStatusChoices.PROCESSING, OrderStatusChoices.COMPLETED, OrderStatusChoices.PARTIALLY_REFUNDED, OrderStatusChoices.PENDING}:
            order.transition_to(OrderStatusChoices.PENDING_REFUND)
            return True
        return False

    @classmethod
    def _get_rollback_snapshot(cls, refund_request: RefundRequest) -> Dict[str, Any]:
        metadata = refund_request.metadata or {}
        snapshot = metadata.get(cls.ROLLBACK_SNAPSHOT_KEY)
        if isinstance(snapshot, dict):
            return snapshot
        return {}

    @classmethod
    def _save_rollback_snapshot(cls, refund_request: RefundRequest, snapshot: Dict[str, Any]) -> None:
        metadata = refund_request.metadata or {}
        metadata[cls.ROLLBACK_SNAPSHOT_KEY] = snapshot
        refund_request.metadata = metadata
        refund_request.save(update_fields=["metadata"])

    @classmethod
    def initialize_rollback_snapshot(cls, refund_request: RefundRequest) -> None:
        """Capture payment state before any refund side-effects mutate linked entities."""
        snapshot = cls._get_rollback_snapshot(refund_request)
        changed = False

        if not snapshot.get("payment_status_before_request"):
            snapshot["payment_status_before_request"] = refund_request.payment.status
            changed = True

        if not isinstance(snapshot.get("orders"), dict):
            snapshot["orders"] = {}
            changed = True

        if changed:
            cls._save_rollback_snapshot(refund_request, snapshot)

    @classmethod
    def _snapshot_order_status(
        cls,
        refund_request: RefundRequest,
        order: Order,
        snapshot: Dict[str, Any],
    ) -> bool:
        orders_snapshot = snapshot.setdefault("orders", {})
        if not isinstance(orders_snapshot, dict):
            snapshot["orders"] = {}
            orders_snapshot = snapshot["orders"]

        key = str(order.id)
        if key in orders_snapshot:
            return False

        orders_snapshot[key] = {"status": order.status}
        return True

    @classmethod
    def _transition_order_to_partially_refunded(cls, order: Order) -> bool:
        """Transition order to PARTIALLY_REFUNDED after a partial refund is processed.
        Falls back gracefully from PENDING_REFUND. If the order was already PARTIALLY_REFUNDED
        it stays there (idempotent). Returns True if a transition was made.
        """
        if order.status == OrderStatusChoices.PARTIALLY_REFUNDED:
            return False
        if order.status in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
            return False
        if order.status == OrderStatusChoices.PENDING_REFUND:
            order.transition_to(OrderStatusChoices.PARTIALLY_REFUNDED)
            return True
        if order.status == OrderStatusChoices.DRAFT:
            order.transition_to(OrderStatusChoices.PENDING)
            order.transition_to(OrderStatusChoices.PENDING_REFUND)
            order.transition_to(OrderStatusChoices.PARTIALLY_REFUNDED)
            return True
        if order.status == OrderStatusChoices.PENDING:
            order.transition_to(OrderStatusChoices.PENDING_REFUND)
            order.transition_to(OrderStatusChoices.PARTIALLY_REFUNDED)
            return True
        # Order never entered pending_refund yet (e.g. completed) — move it through
        if order.status in {OrderStatusChoices.COMPLETED, OrderStatusChoices.PROCESSING}:
            order.transition_to(OrderStatusChoices.PENDING_REFUND)
            order.transition_to(OrderStatusChoices.PARTIALLY_REFUNDED)
            return True
        return False

    @classmethod
    def _transition_order_to_refunded(cls, order: Order, *, restore_stock: bool = True) -> bool:
        if order.status in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
            return False

        if order.status == OrderStatusChoices.DRAFT:
            order.transition_to(OrderStatusChoices.PENDING)
            order.transition_to(OrderStatusChoices.PROCESSING)
            order.transition_to(OrderStatusChoices.REFUNDED, restore_stock=restore_stock)
            return True

        if order.status == OrderStatusChoices.PENDING:
            order.transition_to(OrderStatusChoices.PROCESSING)
            order.transition_to(OrderStatusChoices.REFUNDED, restore_stock=restore_stock)
            return True

        if order.status in {
            OrderStatusChoices.PROCESSING,
            OrderStatusChoices.COMPLETED,
            OrderStatusChoices.PENDING_REFUND,
            OrderStatusChoices.PARTIALLY_REFUNDED,
        }:
            order.transition_to(OrderStatusChoices.REFUNDED, restore_stock=restore_stock)
            return True

        return False

    @classmethod
    def _normalize_quantity(cls, raw_value, default: int) -> int:
        try:
            quantity = int(raw_value)
        except (TypeError, ValueError):
            quantity = default
        return quantity if quantity > 0 else default

    @classmethod
    def _get_order_item_refunded_quantity(cls, payment, order_item: OrderItem) -> int:
        associations = RefundAssociation.objects.filter(
            refund_request__payment=payment,
            target_type=ContentType.objects.get_for_model(OrderItem),
            target_id=str(order_item.pk),
        ).exclude(
            refund_request__verification_status__in=[
                VerificationStatus.REJECTED,
                VerificationStatus.PROCESSED,
            ],
        )

        refunded_quantity = 0
        for association in associations:
            metadata = association.metadata if isinstance(association.metadata, dict) else {}
            refunded_quantity += cls._normalize_quantity(metadata.get("quantity"), order_item.quantity)

        return refunded_quantity

    @classmethod
    def _is_order_fully_refunded(cls, payment, order: Order) -> bool:
        order_items = list(order.order_items.all())
        if not order_items:
            return False

        if all(
            item.quantity <= 0 or item.status in {OrderItemStatusChoices.REFUNDED, OrderItemStatusChoices.CANCELLED}
            for item in order_items
        ):
            return True

        return all(
            cls._get_order_item_refunded_quantity(payment, order_item) >= order_item.quantity
            for order_item in order_items
        )

    @classmethod
    def _apply_order_item_refund_quantity_and_stock(
        cls,
        refund_request: RefundRequest,
        order_item: OrderItem,
        requested_refund_qty: int,
    ) -> int:
        """Apply processed refund side-effects directly to order-item quantity, totals, and stock."""
        original_quantity = int(order_item.quantity)
        if original_quantity <= 0:
            return 0

        refund_quantity = min(max(int(requested_refund_qty or 0), 0), original_quantity)
        if refund_quantity <= 0:
            return 0

        if order_item.product_variant:
            reason = "partial_refund_restoration" if refund_quantity < original_quantity else "refund_restoration"
            order_item.product_variant.increment_stock(
                refund_quantity,
                reason=reason,
                actor=refund_request.processed_by,
                order_id=order_item.order.order_id,
                payment_id=refund_request.payment.payment_id,
                order_item_id=order_item.id,
                notes=(
                    f"Applied processed refund {refund_request.tracking_reference} "
                    f"for quantity {refund_quantity}."
                ),
            )

        remaining_quantity = max(original_quantity - refund_quantity, 0)
        new_total = (order_item.unit_price.amount * Decimal(remaining_quantity)).quantize(Decimal("0.01"))

        order_item.quantity = remaining_quantity
        order_item.total_price = Money(new_total, order_item.total_price.currency)
        if remaining_quantity == 0:
            order_item.status = OrderItemStatusChoices.REFUNDED

        order_item.save(update_fields=["quantity", "total_price", "status"])
        return refund_quantity

    @classmethod
    def _finalize_order_after_itemized_refunds(cls, order: Order) -> bool:
        """Normalize order state after order-item quantities have been reduced by processed refunds."""
        order.recalculate_total_amount()
        order.refresh_from_db()

        # Zero-quantity items are terminally refunded and must not be flipped back to completed.
        order.order_items.filter(quantity=0).exclude(
            status__in=[OrderItemStatusChoices.REFUNDED, OrderItemStatusChoices.CANCELLED]
        ).update(status=OrderItemStatusChoices.REFUNDED)

        order_items = list(order.order_items.all())
        if not order_items:
            return False

        is_fully_refunded = all(
            item.quantity == 0 or item.status in {OrderItemStatusChoices.REFUNDED, OrderItemStatusChoices.CANCELLED}
            for item in order_items
        )

        if is_fully_refunded:
            if order.status not in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
                # Itemized flows restore stock per refunded quantity. Skip order-level stock restoration.
                return cls._transition_order_to_refunded(order, restore_stock=False)
            return False

        cls._transition_order_to_partially_refunded(order)
        return False

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
    def calculate_booking_ticket_breakdown(cls, payment, attendees: List[Attendee]) -> Dict[str, Any]:
        """Calculate ticket-only totals for selected booking attendees."""
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
                    "currency": currency.code,
                }
            )

        return {
            "scope": "booking_tickets",
            "total": float(total.amount),
            "total_currency": currency.code,
            "tickets": ticket_items,
            "entity_counts": {"tickets": len(ticket_items), "orders": 0, "items": 0},
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

            already_refunded_quantity = cls._get_order_item_refunded_quantity(payment, order_item)
            remaining_quantity = max(order_item.quantity - already_refunded_quantity, 0)
            if remaining_quantity <= 0:
                raise ValidationError(
                    f"Order item {order_item.id} is already fully refunded."
                )

            if requested_quantity > remaining_quantity:
                raise ValidationError(
                    f"Requested quantity ({requested_quantity}) exceeds remaining refundable quantity "
                    f"({remaining_quantity}) for order item {order_item.id}."
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
                    "already_refunded_quantity": already_refunded_quantity,
                    "remaining_quantity": remaining_quantity,
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
                    "already_refunded_quantity": already_refunded_quantity,
                    "remaining_quantity": remaining_quantity,
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
        target_kind = cls.assert_supported_payment_target(payment)
        if target_kind != cls.TARGET_KIND_ORDER:
            raise ValidationError("Targeted order-item refunds are only supported for order-linked payments.")

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

            already_refunded_quantity = cls._get_order_item_refunded_quantity(payment, order_item)
            remaining_quantity = max(order_item.quantity - already_refunded_quantity, 0)
            if remaining_quantity <= 0:
                raise ValidationError(
                    f"Order item {order_item.id} is already fully refunded."
                )

            if requested_quantity > remaining_quantity:
                raise ValidationError(
                    f"Requested quantity ({requested_quantity}) exceeds remaining refundable quantity "
                    f"({remaining_quantity}) for order item {order_item.id}."
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
                    "already_refunded_quantity": already_refunded_quantity,
                    "remaining_quantity": remaining_quantity,
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
        cls.initialize_rollback_snapshot(refund_request)
        snapshot = cls._get_rollback_snapshot(refund_request)
        snapshot_changed = False

        metadata = refund_request.metadata or {}
        refund_scope = metadata.get("refund_scope")
        target_kind = cls.assert_supported_payment_target(refund_request.payment)

        if refund_scope == "full_target" and refund_request.payment.target is not None:
            target_obj = refund_request.payment.target
            ct_id = ContentType.objects.get_for_model(target_obj).id
            key = (ct_id, str(target_obj.pk))
            existing_keys = set(
                RefundAssociation.objects.filter(refund_request=refund_request).values_list("target_type_id", "target_id")
            )
            if key not in existing_keys:
                refund_request.associate_with(
                    target_obj,
                    amount=Money(refund_request.amount.amount, refund_request.amount.currency),
                    metadata={
                        "entity": target_kind,
                        "scope": "full_target",
                    },
                )
            if isinstance(target_obj, Order):
                snapshot_changed = cls._snapshot_order_status(refund_request, target_obj, snapshot) or snapshot_changed
                cls._transition_order_to_pending_refund(target_obj)
            if snapshot_changed:
                cls._save_rollback_snapshot(refund_request, snapshot)
            return

        if refund_scope == cls.REFUND_SCOPE_TARGETED_ORDER_ITEMS:
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
                        "order_item_id": order_item.pk,
                        "attendee_id": item_data.get("attendee_id"),
                        "order_id": item_data.get("order_id"),
                        "quantity": item_data.get("quantity"),
                        "unit_price": item_data.get("unit_price"),
                    },
                )
                snapshot_changed = cls._snapshot_order_status(refund_request, order_item.order, snapshot) or snapshot_changed
                cls._transition_order_to_pending_refund(order_item.order)

            if snapshot_changed:
                cls._save_rollback_snapshot(refund_request, snapshot)
            return

        if refund_scope == cls.REFUND_SCOPE_TARGETED_BOOKING_PRODUCTS:
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
                    .select_related("order", "order__attendee", "product_variant", "package_product")
                    .filter(order__payment=refund_request.payment, id=item_data.get("order_item_id"))
                    .first()
                )
                if not order_item:
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
                        "attendee_id": item_data.get("attendee_id"),
                        "entity": "order_item",
                        "scope": "targeted_booking_products",
                        "order_item_id": order_item.pk,
                        "order_id": item_data.get("order_id"),
                        "quantity": item_data.get("quantity"),
                        "unit_price": item_data.get("unit_price"),
                        "variant_id": item_data.get("variant_id"),
                        "package_product_id": item_data.get("package_product_id"),
                    },
                )
                snapshot_changed = cls._snapshot_order_status(refund_request, order_item.order, snapshot) or snapshot_changed
                cls._transition_order_to_pending_refund(order_item.order)
            if snapshot_changed:
                cls._save_rollback_snapshot(refund_request, snapshot)
            return

        if refund_scope == cls.REFUND_SCOPE_HYBRID_BOOKING:
            breakdown = metadata.get("frozen_breakdown") or {}
            selected_items = breakdown.get("order_items") or []
            ticket_attendee_ids = breakdown.get("ticket_attendee_ids") or metadata.get("selected_attendee_ids") or []

            existing_keys = set(
                RefundAssociation.objects.filter(refund_request=refund_request).values_list("target_type_id", "target_id")
            )
            currency = refund_request.amount.currency

            if ticket_attendee_ids:
                attendees = cls.resolve_booking_attendees(refund_request.payment, ticket_attendee_ids)
                entities = cls.get_refund_entities(refund_request.payment, attendees)

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
                        metadata={
                            "attendee_id": str(ticket.attendee.attendee_id), 
                            "entity": "ticket", 
                            "scope": cls.REFUND_SCOPE_HYBRID_BOOKING,
                            "ticket_id": str(ticket.ticket_id),
                            },
                    )
                    existing_keys.add(key)

            for item_data in selected_items:
                order_item = (
                    OrderItem.objects
                    .select_related("order", "order__attendee", "product_variant", "package_product")
                    .filter(order__payment=refund_request.payment, id=item_data.get("order_item_id"))
                    .first()
                )
                if not order_item:
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
                        "attendee_id": item_data.get("attendee_id"),
                        "entity": "order_item",
                        "scope": cls.REFUND_SCOPE_HYBRID_BOOKING,
                        "order_item_id": order_item.pk,
                        "order_id": item_data.get("order_id"),
                        "quantity": item_data.get("quantity"),
                        "unit_price": item_data.get("unit_price"),
                        "variant_id": item_data.get("variant_id"),
                        "package_product_id": item_data.get("package_product_id"),
                    },
                )
                snapshot_changed = cls._snapshot_order_status(refund_request, order_item.order, snapshot) or snapshot_changed
                cls._transition_order_to_pending_refund(order_item.order)
                existing_keys.add(key)

            if snapshot_changed:
                cls._save_rollback_snapshot(refund_request, snapshot)
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
                    "scope": "booking_attendee_order",
                    "order_id": str(order.order_id),
                },
            )
            snapshot_changed = cls._snapshot_order_status(refund_request, order, snapshot) or snapshot_changed
            cls._transition_order_to_pending_refund(order)

        if snapshot_changed:
            cls._save_rollback_snapshot(refund_request, snapshot)

    @classmethod
    @transaction.atomic
    def apply_verify_block(cls, refund_request: RefundRequest) -> Dict[str, int]:
        # Ensure we have concrete associations before enforcing verify-stage blocking.
        cls.attach_associations(refund_request)
        metadata = refund_request.metadata or {}
        refund_scope = metadata.get("refund_scope")
        is_targeted_scope = refund_scope in cls.TARGETED_REFUND_SCOPES

        blocked_order_ids = set()
        for association in refund_request.associations.select_related("target_type"):
            target = association.target_object
            if isinstance(target, Order) and cls._transition_order_to_pending_refund(target):
                blocked_order_ids.add(target.id)
            if isinstance(target, OrderItem) and cls._transition_order_to_pending_refund(target.order):
                blocked_order_ids.add(target.order_id)

        attendee_ids = metadata.get("selected_attendee_ids") or []
        if attendee_ids and not is_targeted_scope:
            selected_orders = Order.objects.filter(
                payment=refund_request.payment,
                attendee__attendee_id__in=attendee_ids,
            )
            for order in selected_orders:
                if cls._transition_order_to_pending_refund(order):
                    blocked_order_ids.add(order.id)

        blocked_orders = len(blocked_order_ids)

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
        is_targeted_scope = refund_scope in cls.TARGETED_REFUND_SCOPES
        order_item_refund_quantities: Dict[int, int] = {}
        affected_order_ids = set()

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
                affected_order_ids.add(target.id)
                if target.status not in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
                    if refund_scope == "full_target" and refund_request.is_full:
                        if cls._transition_order_to_refunded(target):
                            finalized_orders += 1
                    elif association.amount.amount >= target.total_amount.amount:
                        # Order-level association covering the full order amount
                        if cls._transition_order_to_refunded(target):
                            finalized_orders += 1
                    elif cls._is_order_fully_refunded(refund_request.payment, target):
                        if cls._transition_order_to_refunded(target):
                            finalized_orders += 1
                    else:
                        cls._transition_order_to_partially_refunded(target)
                continue

            if isinstance(target, OrderItem):
                affected_order_ids.add(target.order_id)
                quantity = association.metadata.get("quantity") if isinstance(association.metadata, dict) else None
                try:
                    refunded_qty = int(quantity)
                except (TypeError, ValueError):
                    refunded_qty = 0
                if refunded_qty <= 0:
                    refunded_qty = target.quantity

                applied_qty = cls._apply_order_item_refund_quantity_and_stock(refund_request, target, refunded_qty)
                if applied_qty > 0:
                    order_item_refund_quantities[target.id] = order_item_refund_quantities.get(target.id, 0) + applied_qty

        if refund_scope in cls.TARGETED_REFUND_SCOPES and order_item_refund_quantities:
            order_ids = list(
                OrderItem.objects
                .filter(id__in=order_item_refund_quantities.keys())
                .values_list("order_id", flat=True)
                .distinct()
            )
            affected_order_ids.update(order_ids)

            for order in Order.objects.filter(id__in=order_ids).prefetch_related("order_items"):
                if cls._finalize_order_after_itemized_refunds(order):
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
                    if cls._is_order_fully_refunded(refund_request.payment, order):
                        if cls._transition_order_to_refunded(order):
                            finalized_orders += 1
                    else:
                        cls._transition_order_to_partially_refunded(order)

        if affected_order_ids:
            for order in Order.objects.filter(id__in=affected_order_ids).prefetch_related("order_items"):
                if order.status in {OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED}:
                    continue
                if refund_scope in cls.TARGETED_REFUND_SCOPES:
                    if cls._finalize_order_after_itemized_refunds(order):
                        finalized_orders += 1
                    continue

                if cls._is_order_fully_refunded(refund_request.payment, order):
                    if cls._transition_order_to_refunded(order):
                        finalized_orders += 1
                else:
                    cls._transition_order_to_partially_refunded(order)

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

        create_notification(
            event=refund_request.payment.event,
            payment=refund_request.payment,
            message=f"Refund finalized for payment {refund_request.payment.payment_reference}: {finalized_tickets} tickets and {finalized_orders} orders finalized.",
            metadata={
                "refund_tracking_reference": refund_request.tracking_reference,
                "payment_reference": refund_request.payment.payment_reference,
            },
            notification_type=NotificationTypeChoices.REFUND_PROCESSED,
            priority=NotificationPriorityChoices.HIGH,
            force_create=True,
        )

        return {"finalized_tickets": finalized_tickets, "finalized_orders": finalized_orders}

    @classmethod
    def determine_payment_status_after_process(cls, refund_request: RefundRequest) -> str:
        if refund_request.is_full:
            return PaymentStatusChoices.REFUNDED

        processed_total = Decimal("0.00")
        for processed_request in refund_request.payment.refund_requests.filter(
            verification_status=VerificationStatus.PROCESSED
        ):
            processed_total += Decimal(str(processed_request.amount.amount))

        payment_total = Decimal(str(refund_request.payment.base_amount.amount))
        if processed_total.quantize(Decimal("0.01")) >= payment_total.quantize(Decimal("0.01")):
            return PaymentStatusChoices.REFUNDED

        return PaymentStatusChoices.PARTIALLY_REFUNDED

    @classmethod
    def determine_payment_status_after_verify(cls, refund_request: RefundRequest) -> str:
        if refund_request.is_full:
            return PaymentStatusChoices.PENDING_REFUND
        return PaymentStatusChoices.PARTIALLY_REFUNDED

    @classmethod
    def _validate_rollback_snapshot(cls, snapshot: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        if not isinstance(snapshot, dict):
            return ['snapshot is not a dictionary']

        if not isinstance(snapshot.get('orders', {}), dict):
            issues.append('orders snapshot is not a dictionary')

        payment_status_before_request = snapshot.get('payment_status_before_request')
        if payment_status_before_request and payment_status_before_request not in {
            PaymentStatusChoices.COMPLETED,
            PaymentStatusChoices.PARTIALLY_REFUNDED,
        }:
            issues.append('payment_status_before_request is not restorable')

        return issues

    @classmethod
    @transaction.atomic
    def apply_reject_rollback(cls, refund_request: RefundRequest) -> Dict[str, Any]:
        """Rollback in-flight refund side effects when a refund request is rejected."""
        snapshot = cls._get_rollback_snapshot(refund_request)
        initial_order_id = None
        for association in refund_request.associations.select_related("target_type"):
            target = association.target_object
            if isinstance(target, Order):
                initial_order_id = target.id
                break
            if isinstance(target, OrderItem):
                initial_order_id = target.order_id
                break

        rollback_log = RefundRollbackLog.objects.create(
            order_id=initial_order_id,
            payment_id=refund_request.payment.payment_id,
            status=RefundRollbackLog.RollbackStatusChoices.VALIDATING,
            snapshot_before=snapshot if isinstance(snapshot, dict) else {},
            actor=getattr(refund_request, 'last_updated_by', None),
        )

        snapshot_issues = cls._validate_rollback_snapshot(snapshot)
        if snapshot_issues:
            rollback_log.status = RefundRollbackLog.RollbackStatusChoices.VALIDATION_FAILED
            rollback_log.validation_issues = snapshot_issues
            rollback_log.error_message = 'Invalid rollback snapshot payload'
            rollback_log.save(update_fields=['status', 'validation_issues', 'error_message', 'updated_at'])
            logger.error(
                'Reject rollback aborted for refund_request=%s due to invalid snapshot: %s',
                refund_request.pk,
                snapshot_issues,
            )
            raise ValidationError('Rollback snapshot is invalid; manual intervention required.')

        order_snapshots = snapshot.get("orders") if isinstance(snapshot.get("orders"), dict) else {}

        # Build candidate order IDs from both snapshot and associations.
        candidate_order_ids = {int(order_id) for order_id in order_snapshots.keys() if str(order_id).isdigit()}
        for association in refund_request.associations.select_related("target_type"):
            target = association.target_object
            if isinstance(target, Order):
                candidate_order_ids.add(target.id)
            elif isinstance(target, OrderItem):
                candidate_order_ids.add(target.order_id)

        restored_orders = 0
        skipped_orders = 0
        failed_order_ids: List[int] = []
        rollback_log.status = RefundRollbackLog.RollbackStatusChoices.RESTORING
        rollback_log.save(update_fields=['status', 'updated_at'])

        for order in Order.objects.filter(id__in=candidate_order_ids).prefetch_related("order_items"):
            if order.status != OrderStatusChoices.PENDING_REFUND:
                skipped_orders += 1
                continue

            snap = order_snapshots.get(str(order.id), {}) if isinstance(order_snapshots, dict) else {}
            desired_status = snap.get("status") if isinstance(snap, dict) else None
            if desired_status not in {OrderStatusChoices.COMPLETED, OrderStatusChoices.PARTIALLY_REFUNDED}:
                has_refunded_items = order.order_items.filter(status=OrderItemStatusChoices.REFUNDED).exists()
                desired_status = OrderStatusChoices.PARTIALLY_REFUNDED if has_refunded_items else OrderStatusChoices.COMPLETED

            try:
                if order.status != desired_status:
                    order.transition_to(desired_status)

                # Ensure any in-flight item flags are cleared when restoring to completed.
                if desired_status == OrderStatusChoices.COMPLETED:
                    order.order_items.filter(status=OrderItemStatusChoices.PENDING_REFUND).update(
                        status=OrderItemStatusChoices.COMPLETED
                    )

                restored_orders += 1
            except ValidationError:
                fallback_status = (
                    OrderStatusChoices.PARTIALLY_REFUNDED
                    if desired_status == OrderStatusChoices.COMPLETED
                    else OrderStatusChoices.COMPLETED
                )
                try:
                    if order.status != fallback_status:
                        order.transition_to(fallback_status)

                    if fallback_status == OrderStatusChoices.COMPLETED:
                        order.order_items.filter(status=OrderItemStatusChoices.PENDING_REFUND).update(
                            status=OrderItemStatusChoices.COMPLETED
                        )

                    restored_orders += 1
                except ValidationError:
                    failed_order_ids.append(order.id)

        restored_payment_status = snapshot.get("payment_status_before_request")
        if restored_payment_status not in {PaymentStatusChoices.COMPLETED, PaymentStatusChoices.PARTIALLY_REFUNDED}:
            has_prior_processed_refund = refund_request.payment.refund_requests.exclude(
                pk=refund_request.pk
            ).filter(
                verification_status=VerificationStatus.PROCESSED,
            ).exists()
            restored_payment_status = (
                PaymentStatusChoices.PARTIALLY_REFUNDED
                if has_prior_processed_refund
                else PaymentStatusChoices.COMPLETED
            )

        rollback_log.status = (
            RefundRollbackLog.RollbackStatusChoices.FAILED
            if failed_order_ids
            else RefundRollbackLog.RollbackStatusChoices.COMPLETED
        )
        rollback_log.snapshot_after = {
            'restored_orders': restored_orders,
            'skipped_orders': skipped_orders,
            'failed_order_ids': failed_order_ids,
            'restored_payment_status': restored_payment_status,
        }
        rollback_log.validation_issues = snapshot_issues
        rollback_log.save(update_fields=['status', 'snapshot_after', 'validation_issues', 'updated_at'])

        create_notification(
            event=refund_request.payment.event,
            payment=refund_request.payment,
            message=(
                f"Refund rejection rollback for payment {refund_request.payment.payment_reference}: "
                f"{restored_orders} orders restored, {skipped_orders} orders skipped, "
                f"{len(failed_order_ids)} orders failed to restore."
            ),
            metadata={
                "refund_tracking_reference": refund_request.tracking_reference,
                "payment_reference": refund_request.payment.payment_reference,
                "restored_orders": restored_orders,
                "skipped_orders": skipped_orders,
                "failed_order_ids": failed_order_ids,
                "restored_payment_status": restored_payment_status,
            },
            notification_type=NotificationTypeChoices.REFUND_REJECTION,
            priority=NotificationPriorityChoices.HIGH,
            force_create=True,
        )

        return {
            "restored_orders": restored_orders,
            "skipped_orders": skipped_orders,
            "failed_order_ids": failed_order_ids,
            "restored_payment_status": restored_payment_status,
        }
