"""
Product Inventory Service

Pure calculation logic for inventory breakdown reporting.
Separated from viewset concerns to allow reuse and easier testing.

Provides:
    - Per-variant stock levels
    - Reorder quantities (based on max_stock_quantity cap + live order demand)
    - Unit and restock costs
    - Aggregated event-level inventory summary

Author: AMDG Platform Team
Version: 1.0.0
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from django.db.models import Sum
from djmoney.money import Money

from apps.products.models import Product, ProductVariant, OrderStatusChoices

# Order statuses that represent confirmed, in-flight demand.
# Stock is already decremented at order-item creation, but these units will
# physically leave the warehouse when fulfilled – the admin must plan for them.
_LIVE_ORDER_STATUSES = (
    OrderStatusChoices.PENDING,
    OrderStatusChoices.PROCESSING,
    OrderStatusChoices.COMPLETED,  # include completed orders to account for any unfulfilled items
)


@dataclass(frozen=True)
class VariantInventoryLine:
    """Inventory breakdown for a single product variant."""
    variant_id: str
    size: str
    color: str
    is_active: bool
    current_stock: int
    max_stock_quantity: Optional[int]
    live_order_units: int  # units in confirmed in-flight orders (pending/processing)
    quantity_to_order: Optional[int]  # None when no max_stock cap is set
    unit_price_amount: Decimal
    unit_price_currency: str
    restock_cost_amount: Optional[Decimal]  # None when quantity_to_order is None
    restock_cost_currency: str
    current_stock_value_amount: Decimal
    current_stock_value_currency: str


@dataclass(frozen=True)
class ProductInventoryLine:
    """Inventory breakdown for a single product across all its variants."""
    product_id: str
    display_code: str
    title: str
    is_active: bool
    verified: bool
    variant_lines: list[VariantInventoryLine]
    total_current_stock: int
    total_restock_cost_amount: Optional[Decimal]
    total_restock_cost_currency: str
    total_current_stock_value_amount: Decimal
    total_current_stock_value_currency: str


@dataclass(frozen=True)
class EventInventorySummary:
    """Top-level inventory summary for an event."""
    event_id: str
    event_title: str
    currency: str
    product_lines: list[ProductInventoryLine]
    total_products: int
    total_variants: int
    total_stock_units: int
    grand_total_stock_value_amount: Decimal
    grand_total_restock_cost_amount: Optional[Decimal]  # None when no variants have a max cap
    has_restock_data: bool  # True when at least one variant has max_stock_quantity set


def _build_variant_line(
    variant: ProductVariant,
    currency: str,
    live_order_units: int,
) -> VariantInventoryLine:
    """
    Compute inventory figures for a single variant.

    Reorder quantity logic
    ----------------------
    Stock is decremented at order-creation time, so ``current_stock`` already
    excludes units reserved for active orders.  However, units in confirmed
    in-flight orders (``pending`` / ``processing``) will physically leave the
    warehouse when fulfilled.  The admin must plan to replenish those units too,
    so the formula is::

        quantity_to_order = max(0, max_stock - current_stock + live_order_units)

    This gives the number of units that must be purchased to bring stock back
    to its maximum cap *after* all current in-flight demand is dispatched.
    """
    unit_price: Money = variant.modified_amount
    current_stock = variant.stock_quantity
    max_stock = variant.max_stock_quantity

    quantity_to_order: Optional[int] = None
    restock_cost_amount: Optional[Decimal] = None

    if max_stock is not None:
        quantity_to_order = max(0, max_stock - current_stock + live_order_units)
        restock_cost_amount = (unit_price.amount * Decimal(quantity_to_order)).quantize(Decimal("0.01"))

    current_stock_value_amount = (unit_price.amount * Decimal(current_stock)).quantize(Decimal("0.01"))

    return VariantInventoryLine(
        variant_id=str(variant.variant_id),
        size=variant.size,
        color=variant.color,
        is_active=variant.is_active,
        current_stock=current_stock,
        max_stock_quantity=max_stock,
        live_order_units=live_order_units,
        quantity_to_order=quantity_to_order,
        unit_price_amount=unit_price.amount,
        unit_price_currency=str(unit_price.currency),
        restock_cost_amount=restock_cost_amount,
        restock_cost_currency=str(unit_price.currency),
        current_stock_value_amount=current_stock_value_amount,
        current_stock_value_currency=str(unit_price.currency),
    )


def _build_product_line(
    product: Product,
    currency: str,
    live_counts: dict[int, int],
) -> ProductInventoryLine:
    """Compute inventory figures for a product and all its variants."""
    variant_lines = [
        _build_variant_line(variant, currency, live_counts.get(variant.pk, 0))
        for variant in product.variants.all()
    ]

    total_current_stock = sum(v.current_stock for v in variant_lines)
    total_current_stock_value = sum(v.current_stock_value_amount for v in variant_lines)

    # Only aggregate restock cost when every variant has a max cap (otherwise partial sums are misleading)
    all_have_restock = all(v.restock_cost_amount is not None for v in variant_lines) if variant_lines else False
    total_restock_cost: Optional[Decimal] = None
    if all_have_restock and variant_lines:
        total_restock_cost = sum(  # type: ignore[assignment]
            v.restock_cost_amount for v in variant_lines  # type: ignore[misc]
        )

    return ProductInventoryLine(
        product_id=str(product.product_id),
        display_code=product.display_code,
        title=product.title,
        is_active=product.is_active,
        verified=product.verified,
        variant_lines=variant_lines,
        total_current_stock=total_current_stock,
        total_restock_cost_amount=total_restock_cost,
        total_restock_cost_currency=currency,
        total_current_stock_value_amount=total_current_stock_value.quantize(Decimal("0.01")),
        total_current_stock_value_currency=currency,
    )


def compute_event_inventory(event) -> EventInventorySummary:
    """
    Compute the full inventory breakdown for a given event.

    Fetches all products and their variants for the event in a single
    optimised query, then performs all calculations in Python to avoid
    complex DB aggregations.

    :param event: Event model instance
    :returns: EventInventorySummary dataclass
    """
    # Determine the dominant currency from the first product, fall back to GBP
    first_product = event.products.select_related().first()
    currency = str(first_product.base_amount.currency) if first_product else "GBP"

    products = list(
        event.products
        .prefetch_related("variants")
        .order_by("title")
    )

    # --- Single batch query for live in-flight order counts ---
    # Fetch the sum of quantities per variant across confirmed in-flight orders
    # in one DB round-trip to avoid N+1 queries.
    from apps.products.models.orders import OrderItem

    variant_pks = [
        variant.pk
        for product in products
        for variant in product.variants.all()
    ]
    live_counts: dict[int, int] = {}
    print(f"Computing inventory for event {event.title} ({event.event_id}) with {len(products)} products and {len(variant_pks)} variants.")
    if variant_pks:
        rows = (
            OrderItem.objects
            .filter(
                product_variant_id__in=variant_pks,
                order__status__in=_LIVE_ORDER_STATUSES,
            )
            .values("product_variant_id")
            .annotate(total=Sum("quantity"))
        )
        print(rows)
        live_counts = {row["product_variant_id"]: row["total"] for row in rows}

    product_lines = [_build_product_line(p, currency, live_counts) for p in products]

    total_variants = sum(len(pl.variant_lines) for pl in product_lines)
    total_stock_units = sum(pl.total_current_stock for pl in product_lines)
    grand_total_stock_value = sum(
        pl.total_current_stock_value_amount for pl in product_lines
    ) or Decimal("0.00")

    # Determine whether restock cost can be computed at a global level
    has_restock_data = any(
        any(v.quantity_to_order is not None for v in pl.variant_lines)
        for pl in product_lines
    )
    grand_total_restock: Optional[Decimal] = None
    if has_restock_data:
        grand_total_restock = sum(
            v.restock_cost_amount
            for pl in product_lines
            for v in pl.variant_lines
            if v.restock_cost_amount is not None
        ) or Decimal("0.00")  # type: ignore[assignment]

    return EventInventorySummary(
        event_id=str(event.event_id),
        event_title=event.title,
        currency=currency,
        product_lines=product_lines,
        total_products=len(product_lines),
        total_variants=total_variants,
        total_stock_units=total_stock_units,
        grand_total_stock_value_amount=Decimal(grand_total_stock_value).quantize(Decimal("0.01")),
        grand_total_restock_cost_amount=(
            Decimal(grand_total_restock).quantize(Decimal("0.01"))
            if grand_total_restock is not None else None
        ),
        has_restock_data=has_restock_data,
    )
