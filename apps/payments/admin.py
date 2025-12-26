from django.contrib import admin
from django.utils.html import format_html
from apps.payments.models import (
    Payment, PaymentMethod, Discount, DiscountRule
)


class DiscountRuleInline(admin.TabularInline):
    model = DiscountRule
    extra = 0
    fields = ('rule_type', 'name', 'value', 'active')


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'discount_type', 'get_discount_value', 'target',
        'active', 'created_at'
    )
    list_filter = ('discount_type', 'active', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at', 'target')
    inlines = [DiscountRuleInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'active')
        }),
        ('Discount Configuration', {
            'fields': ('discount_type', 'percentage', 'amount')
        }),
        ('Target', {
            'fields': ('target_type', 'target_id', 'target'),
            'description': 'The object this discount applies to (e.g., BookingPackage)'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_discount_value(self, obj):
        if obj.discount_type == 'PERCENTAGE':
            return f"{obj.percentage}%"
        else:
            return str(obj.amount)
    get_discount_value.short_description = 'Value'


@admin.register(DiscountRule)
class DiscountRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount', 'rule_type', 'value', 'active')
    list_filter = ('rule_type', 'active', 'discount')
    search_fields = ('name', 'discount__name', 'value')


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'method_type', 'is_active', 'event',
        'created_at'
    )
    list_filter = ('method_type', 'is_active', 'event')
    search_fields = ('title', 'code', 'description')
    readonly_fields = ('method_id', 'code', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'code', 'description', 'method_type', 'is_active', 'event')
        }),
        ('Configuration', {
            'fields': ('provided_details',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'payment_reference', 'get_target', 'get_payment_amount',
        'status', 'method', 'user', 'created_at'
    )
    list_filter = ('status', 'method', 'created_at')
    search_fields = (
        'payment_reference', 'bank_transfer_reference', 'user__username',
        'user__email'
    )
    readonly_fields = (
        'payment_id', 'payment_reference',
        'created_at', 'updated_at', 'base_amount', 'modified_amount',
        'target'
    )
    
    fieldsets = (
        ('Payment Information', {
            'fields': (
                'payment_id', 'payment_reference',
                'user', 'status'
            )
        }),
        ('Amount', {
            'fields': ('base_amount', 'percentage_modifier', 'modified_amount')
        }),
        ('Payment Method', {
            'fields': ('method', 'event')
        }),
        ('Target', {
            'fields': ('target_type', 'target_id', 'target'),
            'description': 'The object this payment is for (e.g., Booking)'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_target(self, obj):
        if obj.target:
            return format_html(
                '<a href="{}">{}</a>',
                f'/admin/{obj.target_type.app_label}/{obj.target_type.model}/{obj.target_id}/change/',
                str(obj.target)
            )
        return '-'
    get_target.short_description = 'Target'
    
    def get_payment_amount(self, obj):
        return obj.modified_amount
    get_payment_amount.short_description = 'Amount'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'method', 'target_type'
        )
