"""
Product Inventory Service

Pure calculation logic for inventory breakdown reporting.
Separated from viewset concerns to allow reuse and easier testing.

Provides:
    - Per-variant stock levels
    - Reorder quantities (based on max_stock_quantity cap + live order demand)
    - Live order cost (cost of units already committed in pending/processing orders)
    - Unit and restock costs
    - Aggregated event-level inventory summary

Filtering (all optional, applied at DB level where possible):
    is_active     – filter products by active status
    category_id   – filter products by category FK
    product_id    – filter to a specific product by UUID
    size          – filter variants by size code
    color         – filter variants by hex colour
    needs_reorder – post-filter: only include variants where quantity_to_order > 0
    has_stock     – post-filter: only include variants where current_stock > 0

Author: AMDG Platform Team
Version: 1.0.0
"""
from dataclasses import dataclass
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
    OrderStatusChoices.COMPLETED,
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
    live_order_units: int          # units in confirmed in-flight orders (pending/processing)
    live_order_cost_amount: Decimal  # cost of those in-flight units (live_order_units × unit_price)
    live_order_cost_currency: str
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
    total_live_order_units: int
    total_live_order_cost_amount: Decimal
    total_live_order_cost_currency: str
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
    total_live_order_units: int
    grand_total_live_order_cost_amount: Decimal   # cost of all in-flight committed orders
    grand_total_live_order_cost_currency: str
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
    live_order_cost_amount = (unit_price.amount * Decimal(live_order_units)).quantize(Decimal("0.01"))

    return VariantInventoryLine(
        variant_id=str(variant.variant_id),
        size=variant.size,
        color=variant.color,
        is_active=variant.is_active,
        current_stock=current_stock,
        max_stock_quantity=max_stock,
        live_order_units=live_order_units,
        live_order_cost_amount=live_order_cost_amount,
        live_order_cost_currency=str(unit_price.currency),
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
    total_live_order_units = sum(v.live_order_units for v in variant_lines)
    total_live_order_cost = sum(v.live_order_cost_amount for v in variant_lines)

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
        total_live_order_units=total_live_order_units,
        total_live_order_cost_amount=Decimal(total_live_order_cost).quantize(Decimal("0.01")),
        total_live_order_cost_currency=currency,
        total_restock_cost_amount=total_restock_cost,
        total_restock_cost_currency=currency,
        total_current_stock_value_amount=Decimal(total_current_stock_value).quantize(Decimal("0.01")),
        total_current_stock_value_currency=currency,
    )


def compute_event_inventory(
    event,
    *,
    is_active: Optional[bool] = None,
    category_id: Optional[int] = None,
    product_id: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    needs_reorder: Optional[bool] = None,
    has_stock: Optional[bool] = None,
) -> EventInventorySummary:
    """
    Compute the full inventory breakdown for a given event.

    All filters are optional.  DB-level filters (is_active, category_id,
    product_id, size, color) are applied before any Python processing.
    Post-computation filters (needs_reorder, has_stock) prune variant and
    product lines from the result after calculations are done.

    :param event: Event model instance
    :param is_active: If set, only include products matching this active flag.
    :param category_id: If set, only include products in this category.
    :param product_id: If set, only return results for the product with this UUID.
    :param size: If set, only include variants with this size code (e.g. ``LG``).
    :param color: If set, only include variants with this hex colour (e.g. ``#FF0000``).
    :param needs_reorder: If True, only include variants where quantity_to_order > 0.
    :param has_stock: If True, only include variants where current_stock > 0.
    :returns: EventInventorySummary dataclass
    """
    from apps.products.models.orders import OrderItem

    # --- Build product queryset with DB-level filters ---
    product_qs = event.products.order_by("title")

    if is_active is not None:
        product_qs = product_qs.filter(is_active=is_active)
    if category_id is not None:
        product_qs = product_qs.filter(categories__id=category_id)
    if product_id is not None:
        product_qs = product_qs.filter(product_id=product_id)

    # Build variant queryset for DB-level variant filters
    variant_filters: dict = {}
    if size is not None:
        variant_filters["size__iexact"] = size
    if color is not None:
        variant_filters["color__iexact"] = color

    # Prefetch only the filtered variants
    from django.db.models import Prefetch
    variant_qs = ProductVariant.objects.all()
    if variant_filters:
        variant_qs = variant_qs.filter(**variant_filters)

    products = list(
        product_qs.prefetch_related(
            Prefetch("variants", queryset=variant_qs)
        )
    )

    # Exclude products that have no variants after variant-level filtering
    if variant_filters:
        products = [p for p in products if p.variants.all()]

    # Determine the dominant currency from the first product, fall back to GBP
    first_product = products[0] if products else None
    currency = str(first_product.base_amount.currency) if first_product else "GBP"

    # --- Single batch query for live in-flight order counts ---
    variant_pks = [
        variant.pk
        for product in products
        for variant in product.variants.all()
    ]
    live_counts: dict[int, int] = {}
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
        live_counts = {row["product_variant_id"]: row["total"] for row in rows}

    product_lines = [_build_product_line(p, currency, live_counts) for p in products]

    # --- Post-computation filtering ---
    if needs_reorder is not None or has_stock is not None:
        filtered_lines: list[ProductInventoryLine] = []
        for pl in product_lines:
            filtered_variants = []
            for v in pl.variant_lines:
                if needs_reorder is True and not (v.quantity_to_order is not None and v.quantity_to_order > 0):
                    continue
                if has_stock is True and v.current_stock <= 0:
                    continue
                if has_stock is False and v.current_stock > 0:
                    continue
                filtered_variants.append(v)

            # Re-aggregate product totals over the filtered variant set
            if not filtered_variants:
                continue

            total_cs = sum(fv.current_stock for fv in filtered_variants)
            total_csv = sum(fv.current_stock_value_amount for fv in filtered_variants)
            total_lou = sum(fv.live_order_units for fv in filtered_variants)
            total_loc = sum(fv.live_order_cost_amount for fv in filtered_variants)
            all_restock = all(fv.restock_cost_amount is not None for fv in filtered_variants)
            t_restock: Optional[Decimal] = (
                sum(fv.restock_cost_amount for fv in filtered_variants)  # type: ignore[misc]
                if all_restock else None
            )

            import dataclasses
            filtered_lines.append(dataclasses.replace(
                pl,
                variant_lines=filtered_variants,
                total_current_stock=total_cs,
                total_live_order_units=total_lou,
                total_live_order_cost_amount=Decimal(total_loc).quantize(Decimal("0.01")),
                total_restock_cost_amount=t_restock,
                total_current_stock_value_amount=Decimal(total_csv).quantize(Decimal("0.01")),
            ))
        product_lines = filtered_lines

    # --- Event-level aggregation ---
    total_variants = sum(len(pl.variant_lines) for pl in product_lines)
    total_stock_units = sum(pl.total_current_stock for pl in product_lines)
    total_live_order_units = sum(pl.total_live_order_units for pl in product_lines)
    grand_total_stock_value = sum(
        pl.total_current_stock_value_amount for pl in product_lines
    ) or Decimal("0.00")
    grand_total_live_order_cost = sum(
        pl.total_live_order_cost_amount for pl in product_lines
    ) or Decimal("0.00")

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
        total_live_order_units=total_live_order_units,
        grand_total_live_order_cost_amount=Decimal(grand_total_live_order_cost).quantize(Decimal("0.01")),
        grand_total_live_order_cost_currency=currency,
        grand_total_stock_value_amount=Decimal(grand_total_stock_value).quantize(Decimal("0.01")),
        grand_total_restock_cost_amount=(
            Decimal(grand_total_restock).quantize(Decimal("0.01"))
            if grand_total_restock is not None else None
        ),
        has_restock_data=has_restock_data,
    )
