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
from apps.products.models import Order, OrderStatusChoices

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
    @transaction.atomic
    def attach_associations(cls, refund_request: RefundRequest) -> None:
        metadata = refund_request.metadata or {}
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

        blocked_orders = 0
        for association in refund_request.associations.select_related("target_type"):
            target = association.target_object
            if isinstance(target, Order) and target.status in {
                OrderStatusChoices.PROCESSING,
                OrderStatusChoices.COMPLETED,
            }:
                target.transition_to(OrderStatusChoices.PENDING_REFUND)
                blocked_orders += 1

        metadata = refund_request.metadata or {}
        attendee_ids = metadata.get("selected_attendee_ids") or []
        if attendee_ids:
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

        metadata = refund_request.metadata or {}
        attendee_ids = metadata.get("selected_attendee_ids") or []
        if attendee_ids:
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
