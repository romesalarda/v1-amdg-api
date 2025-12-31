from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum, Count
from .models import Product, ProductVariant, Order, OrderItem


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    readonly_fields = ('variant_id', 'added_at', 'last_updated_at', 'stock_quantity')
    fields = ('size', 'color', 'stock_quantity', 'max_stock_quantity', 'max_purchase_quantity_per_order', 'is_active', 'verified')
    show_change_link = True


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('title', 'event', 'base_amount', 'verified', 'is_active', 'added_at', 'display_code')
    list_filter = ('verified', 'is_active', 'added_at', 'event')
    search_fields = ('title', 'description', 'display_code', 'event__title', 'event__display_code')
    readonly_fields = ('product_id', 'display_code', 'added_at', 'last_updated_at', 'added_by', 'last_updated_by')
    autocomplete_fields = ('event', 'added_by', 'last_updated_by')
    inlines = [ProductVariantInline]
    list_select_related = ('event', 'added_by')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('product_id', 'display_code', 'title', 'description', 'event')
        }),
        ('Pricing', {
            'fields': ('base_amount', 'percentage_modifier')
        }),
        ('Status', {
            'fields': ('verified', 'is_active')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'last_updated_by', 'last_updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            variant_count=Count('variants'),
            total_stock=Sum('variants__stock_quantity')
        )


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('get_product_title', 'size', 'color_badge', 'stock_quantity', 'max_stock_quantity', 
                    'max_purchase_quantity_per_order', 'is_active', 'verified', 'added_at')
    list_filter = ('size', 'is_active', 'verified', 'added_at', 'product__event')
    search_fields = ('product__title', 'product__display_code', 'product__event__title', 'variant_id')
    readonly_fields = ('variant_id', 'added_at', 'last_updated_at', 'last_updated_by', 'get_event')
    autocomplete_fields = ('product', 'added_by', 'last_updated_by')
    list_select_related = ('product', 'product__event', 'added_by')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('variant_id', 'product', 'get_event')
        }),
        ('Variant Details', {
            'fields': ('size', 'color')
        }),
        ('Stock Management', {
            'fields': ('stock_quantity', 'max_stock_quantity', 'max_purchase_quantity_per_order')
        }),
        ('Pricing (Inherited from Product)', {
            'fields': ('base_amount', 'percentage_modifier'),
            'description': 'Pricing is inherited from the parent product. The base_amount is automatically set.'
        }),
        ('Status', {
            'fields': ('verified', 'is_active')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'last_updated_by', 'last_updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_product_title(self, obj):
        return obj.product.title
    get_product_title.short_description = 'Product'
    get_product_title.admin_order_field = 'product__title'
    
    def color_badge(self, obj):
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            obj.color,
            obj.color
        )
    color_badge.short_description = 'Color'
    
    def get_event(self, obj):
        return obj.product.event.title if obj.product and obj.product.event else '-'
    get_event.short_description = 'Event'
    
    actions = ['increment_stock_by_10', 'decrement_stock_by_10']
    
    def increment_stock_by_10(self, request, queryset):
        for variant in queryset:
            try:
                variant.increment_stock(10)
                variant.refresh_from_db()
            except Exception as e:
                self.message_user(request, f"Error incrementing stock for {variant}: {str(e)}", level='error')
        self.message_user(request, f"Successfully incremented stock for {queryset.count()} variants")
    increment_stock_by_10.short_description = "Increment stock by 10"
    
    def decrement_stock_by_10(self, request, queryset):
        for variant in queryset:
            try:
                variant.decrement_stock(10)
                variant.refresh_from_db()
            except Exception as e:
                self.message_user(request, f"Error decrementing stock for {variant}: {str(e)}", level='error')
        self.message_user(request, f"Successfully decremented stock for {queryset.count()} variants")
    decrement_stock_by_10.short_description = "Decrement stock by 10"


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_variant', 'quantity', 'unit_price', 'total_price')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_reference_id', 'get_event', 'customer', 'attendee', 'status', 
                    'total_amount', 'verification_status', 'created_at')
    list_filter = ('status', 'verification_status', 'created_at', 'updated_at')
    search_fields = ('order_reference_id', 'order_id', 'customer__email', 'customer__first_name', 
                     'customer__last_name', 'attendee__user__email')
    readonly_fields = ('order_id', 'order_reference_id', 'created_at', 'updated_at', 'get_event',
                       'verified_updated_at', 'verified_by', 'processed_at', 'processed_by')
    autocomplete_fields = ('customer', 'attendee', 'created_by', 'updated_by', 'payment')
    inlines = [OrderItemInline]
    list_select_related = ('customer', 'attendee', 'attendee__event', 'payment', 'created_by')
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order_id', 'order_reference_id', 'get_event', 'status')
        }),
        ('Customer Details', {
            'fields': ('customer', 'attendee')
        }),
        ('Payment', {
            'fields': ('total_amount', 'payment')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_updated_at', 'verified_by', 'processed_at', 'processed_by'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_by', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_event(self, obj):
        if obj.attendee and obj.attendee.event:
            return format_html(
                '<a href="{}">{}</a>',
                reverse('admin:events_event_change', args=[obj.attendee.event.pk]),
                obj.attendee.event.title
            )
        return '-'
    get_event.short_description = 'Event'
    
    actions = ['transition_to_pending', 'transition_to_processing', 'transition_to_completed', 
               'transition_to_cancelled', 'mark_as_verified']
    
    def transition_to_pending(self, request, queryset):
        for order in queryset:
            try:
                order.transition_to('pending')
                self.message_user(request, f"Order {order.order_reference_id} transitioned to pending")
            except Exception as e:
                self.message_user(request, f"Error transitioning {order.order_reference_id}: {str(e)}", level='error')
    transition_to_pending.short_description = "Transition to Pending"
    
    def transition_to_processing(self, request, queryset):
        for order in queryset:
            try:
                order.transition_to('processing')
                self.message_user(request, f"Order {order.order_reference_id} transitioned to processing")
            except Exception as e:
                self.message_user(request, f"Error transitioning {order.order_reference_id}: {str(e)}", level='error')
    transition_to_processing.short_description = "Transition to Processing"
    
    def transition_to_completed(self, request, queryset):
        for order in queryset:
            try:
                order.transition_to('completed')
                self.message_user(request, f"Order {order.order_reference_id} transitioned to completed")
            except Exception as e:
                self.message_user(request, f"Error transitioning {order.order_reference_id}: {str(e)}", level='error')
    transition_to_completed.short_description = "Transition to Completed"
    
    def transition_to_cancelled(self, request, queryset):
        for order in queryset:
            try:
                order.transition_to('cancelled')
                self.message_user(request, f"Order {order.order_reference_id} transitioned to cancelled")
            except Exception as e:
                self.message_user(request, f"Error transitioning {order.order_reference_id}: {str(e)}", level='error')
    transition_to_cancelled.short_description = "Transition to Cancelled"
    
    def mark_as_verified(self, request, queryset):
        for order in queryset:
            try:
                order.mark_verified(request.user)
                self.message_user(request, f"Order {order.order_reference_id} marked as verified")
            except Exception as e:
                self.message_user(request, f"Error verifying {order.order_reference_id}: {str(e)}", level='error')
    mark_as_verified.short_description = "Mark as Verified"


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'get_order_reference', 'product_variant', 'quantity', 'unit_price', 'total_price')
    list_filter = ('order__status', 'order__created_at')
    search_fields = ('order__order_reference_id', 'order__order_id', 'product_variant__product__title')
    readonly_fields = ('order', 'product_variant', 'quantity', 'unit_price', 'total_price')
    list_select_related = ('order', 'product_variant', 'product_variant__product')
    
    fieldsets = (
        ('Order Item Information', {
            'fields': ('order', 'product_variant', 'quantity')
        }),
        ('Pricing', {
            'fields': ('unit_price', 'total_price'),
            'description': 'Prices are locked at the time of order creation.'
        }),
    )
    
    def get_order_reference(self, obj):
        return obj.order.order_reference_id
    get_order_reference.short_description = 'Order Reference'
    get_order_reference.admin_order_field = 'order__order_reference_id'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
