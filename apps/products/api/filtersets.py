"""
Production-grade filtersets for the products app.

Provides comprehensive filtering capabilities for product models with
advanced querying options including price ranges, stock availability,
full-text search, and complex field filtering - suitable for e-commerce platforms.

FilterSets:
    - ProductCategoryFilterSet: Filter categories by name
    - EventProductCategoryFilterSet: Filter event-category associations
    - ProductFilterSet: Advanced product filtering with price, stock, availability
    - ProductVariantFilterSet: Filter variants by size, color, stock, price
    - OrderFilterSet: Filter orders by status, date, customer, amount

Author: AMDG Platform Team
Version: 1.0.0
"""
from django_filters import rest_framework as filters
from django.db.models import Q, F, Count, Sum
from django.utils import timezone
from datetime import timedelta

from apps.products.models import (
    Product, ProductVariant, ProductSizeChoices,
    Order, OrderItem, OrderStatusChoices,
    ProductCategory, EventProductCategory
)


class ProductCategoryFilterSet(filters.FilterSet):
    """
    Filterset for ProductCategory with name search.
    
    Supports filtering by:
    - Name (exact, contains)
    - Description search
    
    Example queries:
        ?name=Clothing
        ?name__icontains=shirt
        ?search=sports
    """
    
    name = filters.CharFilter(
        field_name='name',
        lookup_expr='iexact',
        help_text="Exact category name (case-insensitive)"
    )
    name__contains = filters.CharFilter(
        field_name='name',
        lookup_expr='icontains',
        help_text="Category name contains (case-insensitive)"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search across name and description"
    )
    
    class Meta:
        model = ProductCategory
        fields = ['name', 'name__contains', 'search']
    
    def filter_search(self, queryset, name, value):
        """Full-text search across name and description."""
        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value)
        )


class EventProductCategoryFilterSet(filters.FilterSet):
    """
    Filterset for EventProductCategory associations.
    
    Supports filtering by:
    - Event ID or UUID
    - Category ID
    - Date ranges
    
    Example queries:
        ?event=123
        ?category=5
        ?added_after=2025-01-01
    """
    
    event = filters.NumberFilter(
        field_name='event__id',
        help_text="Filter by event ID"
    )
    
    category = filters.NumberFilter(
        field_name='category__id',
        help_text="Filter by category ID"
    )
    category__name = filters.CharFilter(
        field_name='category__name',
        lookup_expr='icontains',
        help_text="Filter by category name"
    )
    
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter associations added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter associations added before this date"
    )
    
    class Meta:
        model = EventProductCategory
        fields = ['event', 'category', 'category__name', 'added_after', 'added_before']


class ProductFilterSet(filters.FilterSet):
    """
    Advanced filterset for Product model with e-commerce grade search.
    
    Supports filtering by:
    - Title search (exact, contains, starts with)
    - Event ID or UUID
    - Category (single or multiple)
    - Price ranges (min/max)
    - Verification and active status
    - Availability (has variants, in stock)
    - Date ranges (added)
    - Full-text search across title and description
    
    Example queries:
        ?title__icontains=shirt&event=123
        ?min_price=10&max_price=50&category=1,2
        ?is_active=true&verified=true&in_stock=true
        ?search=cotton&event=123
        ?added_after=2025-01-01&has_variants=true
    """
    
    # Title filters
    title = filters.CharFilter(
        field_name='title',
        lookup_expr='iexact',
        help_text="Exact product title (case-insensitive)"
    )
    title__contains = filters.CharFilter(
        field_name='title',
        lookup_expr='icontains',
        help_text="Product title contains (case-insensitive)"
    )
    title__startswith = filters.CharFilter(
        field_name='title',
        lookup_expr='istartswith',
        help_text="Product title starts with (case-insensitive)"
    )
    
    # Event filters
    event = filters.NumberFilter(
        field_name='event__id',
        help_text="Filter by event ID"
    )
    
    # Category filters
    category = filters.ModelMultipleChoiceFilter(
        field_name='categories',
        queryset=ProductCategory.objects.all(),
        help_text="Filter by category ID (can specify multiple, comma-separated)"
    )
    category__name = filters.CharFilter(
        field_name='categories__name',
        lookup_expr='icontains',
        help_text="Filter by category name"
    )
    
    # Price filters (on base_amount)
    min_price = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='gte',
        help_text="Minimum product price"
    )
    max_price = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='lte',
        help_text="Maximum product price"
    )
    price = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='exact',
        help_text="Exact product price"
    )
    
    # Status filters
    verified = filters.BooleanFilter(
        field_name='verified',
        help_text="Filter by verification status"
    )
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )
    
    # Availability filters
    has_variants = filters.BooleanFilter(
        method='filter_has_variants',
        help_text="Filter products that have variants"
    )
    in_stock = filters.BooleanFilter(
        method='filter_in_stock',
        help_text="Filter products with available stock (in any variant)"
    )
    
    # Date filters
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter products added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter products added before this date"
    )
    added_date = filters.DateFilter(
        field_name='added_at',
        lookup_expr='date',
        help_text="Filter products added on specific date (YYYY-MM-DD)"
    )
    
    # Display code filter
    display_code = filters.CharFilter(
        field_name='display_code',
        lookup_expr='iexact',
        help_text="Filter by display code (case-insensitive)"
    )
    display_code__contains = filters.CharFilter(
        field_name='display_code',
        lookup_expr='icontains',
        help_text="Display code contains"
    )
    
    # Added by filter
    added_by = filters.NumberFilter(
        field_name='added_by__id',
        help_text="Filter by user ID who added the product"
    )
    
    # Full-text search
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search across title, description, display code, and categories"
    )
    
    class Meta:
        model = Product
        fields = [
            'title', 'title__contains', 'title__startswith',
            'event',
            'category', 'category__name',
            'min_price', 'max_price', 'price',
            'verified', 'is_active',
            'has_variants', 'in_stock',
            'added_after', 'added_before', 'added_date',
            'display_code', 'display_code__contains',
            'added_by',
            'search'
        ]
    
    def filter_has_variants(self, queryset, name, value):
        """Filter products that have variants."""
        if value:
            return queryset.annotate(variant_count=Count('variants')).filter(variant_count__gt=0)
        else:
            return queryset.annotate(variant_count=Count('variants')).filter(variant_count=0)
    
    def filter_in_stock(self, queryset, name, value):
        """Filter products with available stock."""
        if value:
            # Products with at least one variant that has stock > 0 and is active
            return queryset.filter(
                variants__stock_quantity__gt=0,
                variants__is_active=True
            ).distinct()
        else:
            # Products with no variants or all variants out of stock
            return queryset.exclude(
                variants__stock_quantity__gt=0,
                variants__is_active=True
            )
    
    def filter_search(self, queryset, name, value):
        """Full-text search across multiple fields."""
        return queryset.filter(
            Q(title__icontains=value) |
            Q(description__icontains=value) |
            Q(display_code__icontains=value) |
            Q(categories__name__icontains=value)
        ).distinct()


class ProductVariantFilterSet(filters.FilterSet):
    """
    Advanced filterset for ProductVariant model.
    
    Supports filtering by:
    - Product ID or UUID
    - Size and color
    - Stock availability and ranges
    - Price ranges
    - Verification and active status
    - Purchase limits
    
    Example queries:
        ?product=123&size=MD&in_stock=true
        ?min_stock=10&max_stock=100
        ?color__icontains=blue&is_active=true
        ?size__in=SM,MD,LG
    """
    
    # Product filters
    product = filters.NumberFilter(
        field_name='product__id',
        help_text="Filter by product ID"
    )
    product__product_id = filters.UUIDFilter(
        field_name='product__product_id',
        help_text="Filter by product UUID"
    )
    product__title = filters.CharFilter(
        field_name='product__title',
        lookup_expr='icontains',
        help_text="Filter by product title"
    )
    
    # Size filters
    size = filters.ChoiceFilter(
        field_name='size',
        choices=ProductSizeChoices.choices,
        help_text="Filter by size"
    )
    size__in = filters.MultipleChoiceFilter(
        field_name='size',
        choices=ProductSizeChoices.choices,
        help_text="Filter by multiple sizes (comma-separated)"
    )
    
    # Color filters
    color = filters.CharFilter(
        field_name='color',
        lookup_expr='iexact',
        help_text="Filter by color (case-insensitive)"
    )
    color__contains = filters.CharFilter(
        field_name='color',
        lookup_expr='icontains',
        help_text="Color contains (case-insensitive)"
    )
    
    # Stock filters
    in_stock = filters.BooleanFilter(
        method='filter_in_stock',
        help_text="Filter variants with stock available"
    )
    min_stock = filters.NumberFilter(
        field_name='stock_quantity',
        lookup_expr='gte',
        help_text="Minimum stock quantity"
    )
    max_stock = filters.NumberFilter(
        field_name='stock_quantity',
        lookup_expr='lte',
        help_text="Maximum stock quantity"
    )
    low_stock = filters.BooleanFilter(
        method='filter_low_stock',
        help_text="Filter variants with low stock (< 10 units)"
    )
    
    # Price filters (inherited from product)
    min_price = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='gte',
        help_text="Minimum variant price"
    )
    max_price = filters.NumberFilter(
        field_name='base_amount',
        lookup_expr='lte',
        help_text="Maximum variant price"
    )
    
    # Status filters
    verified = filters.BooleanFilter(
        field_name='verified',
        help_text="Filter by verification status"
    )
    is_active = filters.BooleanFilter(
        field_name='is_active',
        help_text="Filter by active status"
    )
    
    # Purchase limit filters
    max_purchase_quantity = filters.NumberFilter(
        field_name='max_purchase_quantity_per_order',
        lookup_expr='lte',
        help_text="Filter by max purchase quantity"
    )
    
    # Date filters
    added_after = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='gte',
        help_text="Filter variants added after this date"
    )
    added_before = filters.DateTimeFilter(
        field_name='added_at',
        lookup_expr='lte',
        help_text="Filter variants added before this date"
    )
    
    # Event filter (through product)
    event = filters.NumberFilter(
        field_name='product__event__id',
        help_text="Filter by event ID"
    )
    
    class Meta:
        model = ProductVariant
        fields = [
            'product', 'product__product_id', 'product__title',
            'size', 'size__in', 'color', 'color__contains',
            'in_stock', 'min_stock', 'max_stock', 'low_stock',
            'min_price', 'max_price',
            'verified', 'is_active',
            'max_purchase_quantity',
            'added_after', 'added_before',
            'event',
        ]
    
    def filter_in_stock(self, queryset, name, value):
        """Filter variants with stock available."""
        if value:
            return queryset.filter(stock_quantity__gt=0)
        else:
            return queryset.filter(stock_quantity=0)
    
    def filter_low_stock(self, queryset, name, value):
        """Filter variants with low stock."""
        low_stock_threshold = 10
        if value:
            return queryset.filter(
                stock_quantity__gt=0,
                stock_quantity__lt=low_stock_threshold
            )
        else:
            return queryset.exclude(
                stock_quantity__gt=0,
                stock_quantity__lt=low_stock_threshold
            )


class OrderFilterSet(filters.FilterSet):
    """
    Advanced filterset for Order model.
    
    Supports filtering by:
    - Order reference and ID
    - Status (single or multiple)
    - Customer and attendee
    - Date ranges (created, updated)
    - Amount ranges
    - Event (through attendee)
    - Payment status
    
    Example queries:
        ?status=completed&created_after=2025-01-01
        ?customer=123&min_amount=50
        ?attendee_id=550e8400-e29b-41d4-a716-446655440000
        ?order_reference__contains=ORD-FAM
        ?status__in=pending,processing
        ?event=456
    """
    
    # Order reference filters
    order_reference = filters.CharFilter(
        field_name='order_reference_id',
        lookup_expr='iexact',
        help_text="Exact order reference (case-insensitive)"
    )
    order_reference__contains = filters.CharFilter(
        field_name='order_reference_id',
        lookup_expr='icontains',
        help_text="Order reference contains"
    )
    
    # Order ID filter
    order_id = filters.UUIDFilter(
        field_name='order_id',
        help_text="Filter by order UUID"
    )
    
    # Status filters
    status = filters.ChoiceFilter(
        field_name='status',
        choices=OrderStatusChoices.choices,
        help_text="Filter by order status"
    )
    status__in = filters.MultipleChoiceFilter(
        field_name='status',
        choices=OrderStatusChoices.choices,
        help_text="Filter by multiple statuses (comma-separated)"
    )
    
    # Customer filters
    customer = filters.NumberFilter(
        field_name='customer__id',
        help_text="Filter by customer user ID"
    )
    customer__email = filters.CharFilter(
        field_name='customer__email',
        lookup_expr='icontains',
        help_text="Filter by customer email"
    )
    customer__username = filters.CharFilter(
        field_name='customer__username',
        lookup_expr='icontains',
        help_text="Filter by customer username"
    )
    
    # Attendee filters
    attendee = filters.NumberFilter(
        field_name='attendee__id',
        help_text="Filter by attendee ID"
    )
    attendee_id = filters.UUIDFilter(
        field_name='attendee__attendee_id',
        help_text="Filter by attendee UUID (public facing identifier)"
    )
    attendee_email = filters.CharFilter(
        field_name='attendee__email',
        lookup_expr='icontains',
        help_text="Filter by attendee email"
    )
    
    # Event filter (through attendee)
    event = filters.NumberFilter(
        field_name='attendee__event__id',
        help_text="Filter by event ID"
    )

    # Date range filters
    created_after = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text="Filter orders created after this date"
    )
    created_before = filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text="Filter orders created before this date"
    )
    created_date = filters.DateFilter(
        field_name='created_at',
        lookup_expr='date',
        help_text="Filter orders created on specific date (YYYY-MM-DD)"
    )
    
    updated_after = filters.DateTimeFilter(
        field_name='updated_at',
        lookup_expr='gte',
        help_text="Filter orders updated after this date"
    )
    updated_before = filters.DateTimeFilter(
        field_name='updated_at',
        lookup_expr='lte',
        help_text="Filter orders updated before this date"
    )
    
    # Amount filters
    min_amount = filters.NumberFilter(
        field_name='total_amount',
        lookup_expr='gte',
        help_text="Minimum order amount"
    )
    max_amount = filters.NumberFilter(
        field_name='total_amount',
        lookup_expr='lte',
        help_text="Maximum order amount"
    )
    amount = filters.NumberFilter(
        field_name='total_amount',
        lookup_expr='exact',
        help_text="Exact order amount"
    )
    
    # Payment filter
    has_payment = filters.BooleanFilter(
        method='filter_has_payment',
        help_text="Filter orders with or without payment"
    )
    payment__status = filters.CharFilter(
        field_name='payment__status',
        help_text="Filter by payment status"
    )
    
    # Created by filter
    created_by = filters.NumberFilter(
        field_name='created_by__id',
        help_text="Filter by user ID who created the order"
    )
    
    # Full-text search
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search across order reference, customer name, attendee name"
    )
    
    class Meta:
        model = Order
        fields = [
            'order_reference', 'order_reference__contains', 'order_id',
            'status', 'status__in',
            'customer', 'customer__email', 'customer__username',
            'attendee', 'attendee_id', 'attendee_email',
            'event',
            'created_after', 'created_before', 'created_date',
            'updated_after', 'updated_before',
            'min_amount', 'max_amount', 'amount',
            'has_payment', 'payment__status',
            'created_by',
            'search'
        ]
    
    def filter_has_payment(self, queryset, name, value):
        """Filter orders with or without payment."""
        if value:
            return queryset.filter(payment__isnull=False)
        else:
            return queryset.filter(payment__isnull=True)
    
    def filter_search(self, queryset, name, value):
        """Full-text search across order, customer, and attendee fields."""
        return queryset.filter(
            Q(order_reference_id__icontains=value) |
            Q(customer__email__icontains=value) |
            Q(customer__username__icontains=value) |
            Q(customer__first_name__icontains=value) |
            Q(customer__last_name__icontains=value) |
            Q(attendee__email__icontains=value) |
            Q(attendee__first_name__icontains=value) |
            Q(attendee__last_name__icontains=value)
        ).distinct()
