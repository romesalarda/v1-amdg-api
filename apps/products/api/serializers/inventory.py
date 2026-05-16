"""
Product Inventory Serializers

Strict, read-only serializers for the inventory breakdown endpoints.
These serializers only represent output shapes – no write logic is included.

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from drf_spectacular.types import OpenApiTypes
from typing import Optional

from apps.products.services.inventory import (
    VariantInventoryLine,
    ProductInventoryLine,
    EventInventorySummary,
)


# ---------------------------------------------------------------------------
# Variant-level serializer
# ---------------------------------------------------------------------------

@extend_schema_serializer(component_name="InventoryVariantLine")
class VariantInventoryLineSerializer(serializers.Serializer):
    """Read-only inventory figures for a single product variant."""

    variant_id = serializers.UUIDField(
        help_text="Unique identifier of the variant."
    )
    size = serializers.CharField(
        help_text="Size code for this variant (e.g. SM, LG, OS)."
    )
    color = serializers.CharField(
        help_text="Hex colour code for this variant (e.g. #FFFFFF)."
    )
    is_active = serializers.BooleanField(
        help_text="Whether this variant is currently active/purchasable."
    )
    current_stock = serializers.IntegerField(
        help_text="Units currently in stock."
    )
    live_order_units = serializers.IntegerField(
        help_text=(
            "Units committed in confirmed in-flight orders (pending/processing). "
            "Stock was already decremented for these, but they will physically "
            "leave the warehouse when fulfilled."
        )
    )
    live_order_cost = serializers.SerializerMethodField(
        help_text="Total monetary value of the in-flight committed units (live_order_units × unit_price)."
    )
    max_stock_quantity = serializers.IntegerField(
        allow_null=True,
        help_text="Maximum stock cap. Null means no cap has been set."
    )
    quantity_to_order = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Units that need to be ordered to reach max_stock_quantity after in-flight orders are fulfilled. "
            "Formula: max(0, max_stock - current_stock + live_order_units). "
            "Null when no max_stock_quantity cap is set."
        )
    )
    unit_price = serializers.SerializerMethodField(
        help_text="Final unit price after percentage modifier, formatted as a money string."
    )
    restock_cost = serializers.SerializerMethodField(
        help_text=(
            "Total cost to restock this variant to its max cap "
            "(quantity_to_order × unit_price). Null when no cap is set."
        )
    )
    current_stock_value = serializers.SerializerMethodField(
        help_text="Current inventory value for this variant (current_stock × unit_price)."
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_live_order_cost(self, obj: VariantInventoryLine) -> str:
        return f"{obj.live_order_cost_amount} {obj.live_order_cost_currency}"

    @extend_schema_field(OpenApiTypes.STR)
    def get_unit_price(self, obj: VariantInventoryLine) -> str:
        return f"{obj.unit_price_amount} {obj.unit_price_currency}"

    @extend_schema_field({"type": "string", "nullable": True})
    def get_restock_cost(self, obj: VariantInventoryLine) -> Optional[str]:
        if obj.restock_cost_amount is None:
            return None
        return f"{obj.restock_cost_amount} {obj.restock_cost_currency}"

    @extend_schema_field(OpenApiTypes.STR)
    def get_current_stock_value(self, obj: VariantInventoryLine) -> str:
        return f"{obj.current_stock_value_amount} {obj.current_stock_value_currency}"


# ---------------------------------------------------------------------------
# Product-level serializer
# ---------------------------------------------------------------------------

@extend_schema_serializer(component_name="InventoryProductLine")
class ProductInventoryLineSerializer(serializers.Serializer):
    """Read-only inventory figures for a product and all its variants."""

    product_id = serializers.UUIDField(
        help_text="Unique identifier of the product."
    )
    display_code = serializers.CharField(
        help_text="Human-readable public identifier for the product."
    )
    title = serializers.CharField(
        help_text="Product title."
    )
    is_active = serializers.BooleanField(
        help_text="Whether this product is currently active."
    )
    verified = serializers.BooleanField(
        help_text="Whether this product has been verified by an administrator."
    )
    variants = VariantInventoryLineSerializer(
        source="variant_lines",
        many=True,
        help_text="Inventory breakdown per variant."
    )
    total_current_stock = serializers.IntegerField(
        help_text="Sum of current_stock across all variants."
    )
    total_live_order_units = serializers.IntegerField(
        help_text="Sum of live_order_units across all variants."
    )
    total_live_order_cost = serializers.SerializerMethodField(
        help_text="Total cost of in-flight committed orders across all variants."
    )
    total_restock_cost = serializers.SerializerMethodField(
        help_text=(
            "Total cost to fully restock all variants. "
            "Only present when every variant has a max_stock_quantity cap set; "
            "null otherwise."
        )
    )
    total_current_stock_value = serializers.SerializerMethodField(
        help_text="Combined inventory value across all variants."
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_total_live_order_cost(self, obj: ProductInventoryLine) -> str:
        return f"{obj.total_live_order_cost_amount} {obj.total_live_order_cost_currency}"

    @extend_schema_field({"type": "string", "nullable": True})
    def get_total_restock_cost(self, obj: ProductInventoryLine) -> Optional[str]:
        if obj.total_restock_cost_amount is None:
            return None
        return f"{obj.total_restock_cost_amount} {obj.total_restock_cost_currency}"

    @extend_schema_field(OpenApiTypes.STR)
    def get_total_current_stock_value(self, obj: ProductInventoryLine) -> str:
        return f"{obj.total_current_stock_value_amount} {obj.total_current_stock_value_currency}"


# ---------------------------------------------------------------------------
# Event-level (top-level response) serializer
# ---------------------------------------------------------------------------

@extend_schema_serializer(component_name="EventInventoryBreakdown")
class EventInventoryBreakdownSerializer(serializers.Serializer):
    """
    Full inventory breakdown for an event.

    Returned by GET /api/products/inventory?event=<url_safe_title>.
    """

    event_id = serializers.UUIDField(
        help_text="Unique identifier of the event."
    )
    event_title = serializers.CharField(
        help_text="Display title of the event."
    )
    currency = serializers.CharField(
        help_text="ISO 4217 currency code used for all monetary values in this response."
    )
    has_restock_data = serializers.BooleanField(
        help_text=(
            "True when at least one variant has a max_stock_quantity cap set, "
            "enabling reorder quantity and restock cost calculations."
        )
    )
    total_products = serializers.IntegerField(
        help_text="Number of products in this event."
    )
    total_variants = serializers.IntegerField(
        help_text="Total number of variants across all products."
    )
    total_stock_units = serializers.IntegerField(
        help_text="Total units currently in stock across all variants."
    )
    total_live_order_units = serializers.IntegerField(
        help_text="Total units committed across all in-flight orders event-wide."
    )
    grand_total_live_order_cost = serializers.SerializerMethodField(
        help_text="Total cost of all in-flight committed orders event-wide."
    )
    grand_total_stock_value = serializers.SerializerMethodField(
        help_text="Total monetary value of all stock currently on hand."
    )
    grand_total_restock_cost = serializers.SerializerMethodField(
        help_text=(
            "Total cost to restock all variants that have a max_stock_quantity cap. "
            "Null when no variants have a cap set."
        )
    )
    products = ProductInventoryLineSerializer(
        source="product_lines",
        many=True,
        help_text="Per-product inventory breakdown."
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_grand_total_live_order_cost(self, obj: EventInventorySummary) -> str:
        return f"{obj.grand_total_live_order_cost_amount} {obj.grand_total_live_order_cost_currency}"

    @extend_schema_field(OpenApiTypes.STR)
    def get_grand_total_stock_value(self, obj: EventInventorySummary) -> str:
        return f"{obj.grand_total_stock_value_amount} {obj.currency}"

    @extend_schema_field({"type": "string", "nullable": True})
    def get_grand_total_restock_cost(self, obj: EventInventorySummary) -> Optional[str]:
        if obj.grand_total_restock_cost_amount is None:
            return None
        return f"{obj.grand_total_restock_cost_amount} {obj.currency}"


# ---------------------------------------------------------------------------
# Attendees-by-variant serializer
# ---------------------------------------------------------------------------

@extend_schema_serializer(component_name="InventoryAttendeeOrderLine")
class InventoryAttendeeSerializer(serializers.Serializer):
    """
    Read-only attendee record enriched with order context for a specific variant.

    Returned by GET /api/products/inventory/attendees.
    """

    attendee_id = serializers.UUIDField(
        source="order__attendee__attendee_id",
        help_text="Unique identifier of the attendee."
    )
    attendee_display_id = serializers.CharField(
        source="order__attendee__attendee_display_id",
        help_text="Human-readable attendee identifier (e.g. ATT-CONF-ABCD12)."
    )
    first_name = serializers.CharField(
        source="order__attendee__first_name",
        help_text="Attendee first name."
    )
    last_name = serializers.CharField(
        source="order__attendee__last_name",
        help_text="Attendee last name."
    )
    email = serializers.EmailField(
        source="order__attendee__email",
        allow_null=True,
        help_text="Attendee email address."
    )
    attendee_status = serializers.CharField(
        source="order__attendee__status",
        help_text="Current attendee registration status."
    )
    order_id = serializers.UUIDField(
        source="order__order_id",
        help_text="UUID of the order containing this item."
    )
    order_reference = serializers.CharField(
        source="order__order_reference_id",
        help_text="Human-readable order reference (e.g. ORD-ABCD1234)."
    )
    order_status = serializers.CharField(
        source="order__status",
        help_text="Current status of the order."
    )
    item_status = serializers.CharField(
        source="status",
        help_text="Status of this specific order item."
    )
    quantity = serializers.IntegerField(
        help_text="Number of units of this variant in the order."
    )
    unit_price = serializers.SerializerMethodField(
        help_text="Unit price paid at time of order."
    )
    total_price = serializers.SerializerMethodField(
        help_text="Total price for this order item (quantity × unit_price)."
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_unit_price(self, obj) -> str:
        return f"{obj['unit_price']} {obj['unit_price_currency']}"

    @extend_schema_field(OpenApiTypes.STR)
    def get_total_price(self, obj) -> str:
        return f"{obj['total_price']} {obj['total_price_currency']}"



# ---------------------------------------------------------------------------
# Variant-level serializer
# ---------------------------------------------------------------------------

@extend_schema_serializer(component_name="InventoryVariantLine")
class VariantInventoryLineSerializer(serializers.Serializer):
    """Read-only inventory figures for a single product variant."""

    variant_id = serializers.UUIDField(
        help_text="Unique identifier of the variant."
    )
    size = serializers.CharField(
        help_text="Size code for this variant (e.g. SM, LG, OS)."
    )
    color = serializers.CharField(
        help_text="Hex colour code for this variant (e.g. #FFFFFF)."
    )
    is_active = serializers.BooleanField(
        help_text="Whether this variant is currently active/purchasable."
    )
    current_stock = serializers.IntegerField(
        help_text="Units currently in stock."
    )
    live_order_units = serializers.IntegerField(
        help_text=(
            "Units committed in confirmed in-flight orders (pending/processing). "
            "Stock was already decremented for these, but they will physically "
            "leave the warehouse when fulfilled."
        )
    )
    max_stock_quantity = serializers.IntegerField(
        allow_null=True,
        help_text="Maximum stock cap. Null means no cap has been set."
    )
    quantity_to_order = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Units that need to be ordered to reach max_stock_quantity. "
            "Null when no max_stock_quantity cap is set."
        )
    )
    unit_price = serializers.SerializerMethodField(
        help_text="Final unit price after percentage modifier, formatted as a money string."
    )
    restock_cost = serializers.SerializerMethodField(
        help_text=(
            "Total cost to restock this variant to its max cap "
            "(quantity_to_order × unit_price). Null when no cap is set."
        )
    )
    current_stock_value = serializers.SerializerMethodField(
        help_text="Current inventory value for this variant (current_stock × unit_price)."
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_unit_price(self, obj: VariantInventoryLine) -> str:
        return f"{obj.unit_price_amount} {obj.unit_price_currency}"

    @extend_schema_field({"type": "string", "nullable": True})
    def get_restock_cost(self, obj: VariantInventoryLine) -> Optional[str]:
        if obj.restock_cost_amount is None:
            return None
        return f"{obj.restock_cost_amount} {obj.restock_cost_currency}"

    @extend_schema_field(OpenApiTypes.STR)
    def get_current_stock_value(self, obj: VariantInventoryLine) -> str:
        return f"{obj.current_stock_value_amount} {obj.current_stock_value_currency}"


# ---------------------------------------------------------------------------
# Product-level serializer
# ---------------------------------------------------------------------------

@extend_schema_serializer(component_name="InventoryProductLine")
class ProductInventoryLineSerializer(serializers.Serializer):
    """Read-only inventory figures for a product and all its variants."""

    product_id = serializers.UUIDField(
        help_text="Unique identifier of the product."
    )
    display_code = serializers.CharField(
        help_text="Human-readable public identifier for the product."
    )
    title = serializers.CharField(
        help_text="Product title."
    )
    is_active = serializers.BooleanField(
        help_text="Whether this product is currently active."
    )
    verified = serializers.BooleanField(
        help_text="Whether this product has been verified by an administrator."
    )
    variants = VariantInventoryLineSerializer(
        source="variant_lines",
        many=True,
        help_text="Inventory breakdown per variant."
    )
    total_current_stock = serializers.IntegerField(
        help_text="Sum of current_stock across all variants."
    )
    total_restock_cost = serializers.SerializerMethodField(
        help_text=(
            "Total cost to fully restock all variants. "
            "Only present when every variant has a max_stock_quantity cap set; "
            "null otherwise."
        )
    )
    total_current_stock_value = serializers.SerializerMethodField(
        help_text="Combined inventory value across all variants."
    )

    @extend_schema_field({"type": "string", "nullable": True})
    def get_total_restock_cost(self, obj: ProductInventoryLine) -> Optional[str]:
        if obj.total_restock_cost_amount is None:
            return None
        return f"{obj.total_restock_cost_amount} {obj.total_restock_cost_currency}"

    @extend_schema_field(OpenApiTypes.STR)
    def get_total_current_stock_value(self, obj: ProductInventoryLine) -> str:
        return f"{obj.total_current_stock_value_amount} {obj.total_current_stock_value_currency}"


# ---------------------------------------------------------------------------
# Event-level (top-level response) serializer
# ---------------------------------------------------------------------------

@extend_schema_serializer(component_name="EventInventoryBreakdown")
class EventInventoryBreakdownSerializer(serializers.Serializer):
    """
    Full inventory breakdown for an event.

    Returned by GET /api/products/inventory?event=<url_safe_title>.
    """

    event_id = serializers.UUIDField(
        help_text="Unique identifier of the event."
    )
    event_title = serializers.CharField(
        help_text="Display title of the event."
    )
    currency = serializers.CharField(
        help_text="ISO 4217 currency code used for all monetary values in this response."
    )
    has_restock_data = serializers.BooleanField(
        help_text=(
            "True when at least one variant has a max_stock_quantity cap set, "
            "enabling reorder quantity and restock cost calculations."
        )
    )
    total_products = serializers.IntegerField(
        help_text="Number of products in this event."
    )
    total_variants = serializers.IntegerField(
        help_text="Total number of variants across all products."
    )
    total_stock_units = serializers.IntegerField(
        help_text="Total units currently in stock across all variants."
    )
    grand_total_stock_value = serializers.SerializerMethodField(
        help_text="Total monetary value of all stock currently on hand."
    )
    grand_total_restock_cost = serializers.SerializerMethodField(
        help_text=(
            "Total cost to restock all variants that have a max_stock_quantity cap. "
            "Null when no variants have a cap set."
        )
    )
    products = ProductInventoryLineSerializer(
        source="product_lines",
        many=True,
        help_text="Per-product inventory breakdown."
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_grand_total_stock_value(self, obj: EventInventorySummary) -> str:
        return f"{obj.grand_total_stock_value_amount} {obj.currency}"

    @extend_schema_field({"type": "string", "nullable": True})
    def get_grand_total_restock_cost(self, obj: EventInventorySummary) -> Optional[str]:
        if obj.grand_total_restock_cost_amount is None:
            return None
        return f"{obj.grand_total_restock_cost_amount} {obj.currency}"
