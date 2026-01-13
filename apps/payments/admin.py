from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, Count
from django.urls import reverse
from apps.payments.models import (
    Payment, PaymentMethod, Discount, DiscountRule,
    RefundRequest, RefundAssociation, RefundPolicy,
    Donation, PaymentHistoryAction
)


# ============================================================================
# INLINE ADMIN CLASSES
# ============================================================================

class DiscountRuleInline(admin.TabularInline):
    """Inline admin for DiscountRule within Discount admin."""
    model = DiscountRule
    extra = 0
    fields = ('rule_type', 'name', 'value', 'active')
    readonly_fields = ('rule_id', 'created_at', 'updated_at')


class PaymentHistoryActionInline(admin.TabularInline):
    """Inline admin for PaymentHistoryAction within Payment admin."""
    model = PaymentHistoryAction
    extra = 0
    fields = ('action', 'description', 'performed_by', 'timestamp')
    readonly_fields = ('action_id', 'action', 'description', 'performed_by', 'timestamp', 'metadata')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


class RefundAssociationInline(admin.TabularInline):
    """Inline admin for RefundAssociation within RefundRequest admin."""
    model = RefundAssociation
    extra = 0
    fields = ('target_type', 'target_id', 'amount', 'description')
    readonly_fields = ('id', 'target_object_link')
    
    def target_object_link(self, obj):
        """Display link to target object."""
        if obj.target_object:
            return format_html(
                '<a href="{}">{}</a>',
                f'/admin/{obj.target_type.app_label}/{obj.target_type.model}/{obj.target_id}/change/',
                str(obj.target_object)
            )
        return '-'
    target_object_link.short_description = 'Target Object'


# ============================================================================
# MODEL ADMIN CLASSES
# ============================================================================

@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    """Enhanced admin for Discount model."""
    
    list_display = (
        'name', 'discount_type', 'get_discount_value', 'target',
        'active', 'created_at', 'get_rule_count'
    )
    list_filter = ('discount_type', 'active', 'created_at', 'target_type')
    search_fields = ('name', 'description')
    readonly_fields = ('discount_id', 'created_at', 'updated_at', 'target')
    inlines = [DiscountRuleInline]
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('discount_id', 'name', 'description', 'active')
        }),
        ('Discount Configuration', {
            'fields': ('discount_type', 'percentage', 'amount'),
            'description': 'Set either percentage OR amount based on discount type'
        }),
        ('Target', {
            'fields': ('target_type', 'target_id', 'target'),
            'description': 'The object this discount applies to (e.g., BookingPackage, Workshop)'
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_discounts', 'deactivate_discounts']
    
    def get_discount_value(self, obj):
        """Display discount value with formatting."""
        if obj.discount_type == 'PERCENTAGE':
            return format_html('<strong>{}%</strong>', obj.percentage)
        else:
            return format_html('<strong>{}</strong>', obj.amount)
    get_discount_value.short_description = 'Value'
    get_discount_value.admin_order_field = 'percentage'
    
    def get_rule_count(self, obj):
        """Display number of associated rules."""
        count = obj.rules.count()
        if count > 0:
            return format_html('<span style="color: green;">{} rules</span>', count)
        return format_html('<span style="color: gray;">No rules</span>')
    get_rule_count.short_description = 'Rules'
    
    def activate_discounts(self, request, queryset):
        """Bulk action to activate discounts."""
        updated = queryset.update(active=True)
        self.message_user(request, f'{updated} discount(s) activated.')
    activate_discounts.short_description = 'Activate selected discounts'
    
    def deactivate_discounts(self, request, queryset):
        """Bulk action to deactivate discounts."""
        updated = queryset.update(active=False)
        self.message_user(request, f'{updated} discount(s) deactivated.')
    deactivate_discounts.short_description = 'Deactivate selected discounts'


@admin.register(DiscountRule)
class DiscountRuleAdmin(admin.ModelAdmin):
    """Enhanced admin for DiscountRule model."""
    
    list_display = ('name', 'discount', 'rule_type', 'value', 'active', 'created_at')
    list_filter = ('rule_type', 'active', 'discount', 'created_at')
    search_fields = ('name', 'discount__name', 'value', 'description')
    readonly_fields = ('rule_id', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Rule Information', {
            'fields': ('rule_id', 'name', 'description', 'rule_type', 'value', 'active')
        }),
        ('Association', {
            'fields': ('discount',)
        }),
        ('Metadata', {
            'fields': ('added_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_rules', 'deactivate_rules']
    
    def activate_rules(self, request, queryset):
        """Bulk action to activate rules."""
        updated = queryset.update(active=True)
        self.message_user(request, f'{updated} rule(s) activated.')
    activate_rules.short_description = 'Activate selected rules'
    
    def deactivate_rules(self, request, queryset):
        """Bulk action to deactivate rules."""
        updated = queryset.update(active=False)
        self.message_user(request, f'{updated} rule(s) deactivated.')
    deactivate_rules.short_description = 'Deactivate selected rules'


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    """Enhanced admin for PaymentMethod model."""
    
    list_display = (
        'title', 'code', 'method_type', 'is_active', 'event',
        'created_at', 'get_payment_count'
    )
    list_filter = ('method_type', 'is_active', 'event', 'created_at')
    search_fields = ('title', 'code', 'description', 'event__name')
    readonly_fields = ('method_id', 'code', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('method_id', 'title', 'code', 'description', 'method_type', 'is_active', 'event')
        }),
        ('Configuration', {
            'fields': ('provided_details',),
            'description': 'JSON configuration for payment method (bank details, Stripe config, etc.)'
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_methods', 'deactivate_methods']
    
    def get_payment_count(self, obj):
        """Display number of payments using this method."""
        count = obj.payments.count()
        if count > 0:
            return format_html(
                '<a href="{}?method__id__exact={}">{} payments</a>',
                reverse('admin:payments_payment_changelist'),
                obj.id,
                count
            )
        return '0 payments'
    get_payment_count.short_description = 'Payments'
    
    def activate_methods(self, request, queryset):
        """Bulk action to activate payment methods."""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} payment method(s) activated.')
    activate_methods.short_description = 'Activate selected payment methods'
    
    def deactivate_methods(self, request, queryset):
        """Bulk action to deactivate payment methods."""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} payment method(s) deactivated.')
    deactivate_methods.short_description = 'Deactivate selected payment methods'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Enhanced admin for Payment model with comprehensive features."""
    
    list_display = (
        'payment_reference', 'get_target', 'get_payment_amount',
        'status', 'method', 'user', 'event', 'created_at'
    )
    list_filter = ('status', 'method__method_type', 'event', 'created_at', 'updated_at')
    search_fields = (
        'payment_reference', 'bank_transfer_reference', 
        'user__username', 'user__email', 'user__first_name', 'user__last_name'
    )
    readonly_fields = (
        'payment_id', 'payment_reference',
        'created_at', 'updated_at', 'modified_amount',
        'target', 'get_refund_summary', 'get_donation_summary'
    )
    date_hierarchy = 'created_at'
    inlines = [PaymentHistoryActionInline]
    
    fieldsets = (
        ('Payment Information', {
            'fields': (
                'payment_id', 'payment_reference',
                'user', 'event', 'status', 'description'
            )
        }),
        ('Amount Details', {
            'fields': ('base_amount', 'percentage_modifier', 'modified_amount'),
            'description': 'Base amount with any applied modifiers'
        }),
        ('Payment Method', {
            'fields': ('method', 'stripe_payment_intent', 'stripe_charge_id', 'bank_transfer_reference')
        }),
        ('Target', {
            'fields': ('target_type', 'target_id', 'target'),
            'description': 'The object this payment is for (e.g., Booking, Order)'
        }),
        ('Summary', {
            'fields': ('get_refund_summary', 'get_donation_summary'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_completed', 'mark_as_failed']
    
    def get_target(self, obj):
        """Display linked target object."""
        if obj.target:
            return format_html(
                '<a href="{}">{}</a>',
                f'/admin/{obj.target_type.app_label}/{obj.target_type.model}/{obj.target_id}/change/',
                str(obj.target)
            )
        return '-'
    get_target.short_description = 'Target'
    
    def get_payment_amount(self, obj):
        """Display formatted payment amount."""
        amount = obj.modified_amount
        if obj.percentage_modifier != 0:
            return format_html(
                '<strong>{}</strong> <small>({}% mod)</small>',
                amount, obj.percentage_modifier
            )
        return format_html('<strong>{}</strong>', amount)
    get_payment_amount.short_description = 'Amount'
    
    def get_refund_summary(self, obj):
        """Display refund requests summary."""
        refunds = obj.refund_requests.all()
        if not refunds:
            return 'No refund requests'
        
        html = '<ul>'
        for refund in refunds:
            color = {
                'pending': 'orange',
                'verified': 'blue',
                'processed': 'green',
                'rejected': 'red'
            }.get(refund.verification_status, 'gray')
            
            html += f'<li style="color: {color};">{refund.amount} - {refund.verification_status}</li>'
        html += '</ul>'
        return format_html(html)
    get_refund_summary.short_description = 'Refunds'
    
    def get_donation_summary(self, obj):
        """Display donations summary."""
        donations = obj.donations.all()
        if not donations:
            return 'No donations'
        
        total = sum(d.amount.amount for d in donations)
        html = f'<strong>Total: {obj.base_amount.currency} {total}</strong><br>'
        html += f'<small>{donations.count()} donation(s)</small>'
        return format_html(html)
    get_donation_summary.short_description = 'Donations'
    
    def mark_as_completed(self, request, queryset):
        """Bulk action to mark payments as completed."""
        from apps.payments.models.payments import PaymentStatusChoices
        pending = queryset.filter(status=PaymentStatusChoices.PENDING)
        updated = pending.update(status=PaymentStatusChoices.COMPLETED)
        
        # Log actions
        for payment in pending:
            PaymentHistoryAction.objects.create(
                payment=payment,
                action='BULK_MARKED_COMPLETED',
                description='Payment marked as completed via bulk action',
                performed_by=request.user
            )
        
        self.message_user(request, f'{updated} payment(s) marked as completed.')
    mark_as_completed.short_description = 'Mark selected as COMPLETED'
    
    def mark_as_failed(self, request, queryset):
        """Bulk action to mark payments as failed."""
        from apps.payments.models.payments import PaymentStatusChoices
        pending = queryset.filter(status=PaymentStatusChoices.PENDING)
        updated = pending.update(status=PaymentStatusChoices.FAILED)
        
        # Log actions
        for payment in pending:
            PaymentHistoryAction.objects.create(
                payment=payment,
                action='BULK_MARKED_FAILED',
                description='Payment marked as failed via bulk action',
                performed_by=request.user
            )
        
        self.message_user(request, f'{updated} payment(s) marked as failed.')
    mark_as_failed.short_description = 'Mark selected as FAILED'
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related(
            'user', 'event', 'method', 'target_type'
        ).prefetch_related('refund_requests', 'donations', 'history_actions')


@admin.register(RefundRequest)
class RefundRequestAdmin(admin.ModelAdmin):
    """Enhanced admin for RefundRequest model."""
    
    list_display = (
        'tracking_reference', 'get_payment', 'amount', 'verification_status',
        'requested_by', 'requested_at', 'is_active', 'get_refund_type'
    )
    list_filter = ('verification_status', 'is_active', 'requested_at', 'processed_at')
    search_fields = (
        'tracking_reference', 'reason', 'payment__payment_reference',
        'requested_by__username', 'requested_by__email'
    )
    readonly_fields = (
        'refund_id', 'tracking_reference', 'requested_at',
        'verified_updated_at', 'processed_at', 'is_partial', 'is_full'
    )
    date_hierarchy = 'requested_at'
    inlines = [RefundAssociationInline]
    
    fieldsets = (
        ('Refund Information', {
            'fields': ('refund_id', 'tracking_reference', 'payment', 'amount', 'reason')
        }),
        ('Status', {
            'fields': ('verification_status', 'is_active', 'is_partial', 'is_full')
        }),
        ('Request Details', {
            'fields': ('requested_by', 'requested_at')
        }),
        ('Verification', {
            'fields': ('verified_by', 'verified_updated_at'),
            'classes': ('collapse',)
        }),
        ('Processing', {
            'fields': ('processed_by', 'processed_at'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['verify_requests', 'reject_requests', 'process_requests']
    
    def get_payment(self, obj):
        """Display linked payment."""
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:payments_payment_change', args=[obj.payment.id]),
            obj.payment.payment_reference
        )
    get_payment.short_description = 'Payment'
    get_payment.admin_order_field = 'payment__payment_reference'
    
    def get_refund_type(self, obj):
        """Display if refund is full or partial."""
        if obj.is_full:
            return format_html('<span style="color: red;">FULL</span>')
        return format_html('<span style="color: orange;">PARTIAL</span>')
    get_refund_type.short_description = 'Type'
    
    def verify_requests(self, request, queryset):
        """Bulk action to verify refund requests."""
        from apps.payments.models.refunds import VerificationStatus
        pending = queryset.filter(verification_status=VerificationStatus.PENDING)
        
        for refund in pending:
            refund.mark_verified(request.user)
        
        self.message_user(request, f'{pending.count()} refund request(s) verified.')
    verify_requests.short_description = 'Verify selected refund requests'
    
    def reject_requests(self, request, queryset):
        """Bulk action to reject refund requests."""
        from apps.payments.models.refunds import VerificationStatus
        pending = queryset.filter(verification_status=VerificationStatus.PENDING)
        
        for refund in pending:
            refund.mark_rejected(request.user)
        
        self.message_user(request, f'{pending.count()} refund request(s) rejected.')
    reject_requests.short_description = 'Reject selected refund requests'
    
    def process_requests(self, request, queryset):
        """Bulk action to process verified refund requests."""
        from apps.payments.models.refunds import VerificationStatus
        verified = queryset.filter(verification_status=VerificationStatus.VERIFIED)
        
        for refund in verified:
            refund.mark_processed(request.user)
        
        self.message_user(request, f'{verified.count()} refund request(s) processed.')
    process_requests.short_description = 'Process verified refund requests'
    
    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related(
            'payment', 'payment__user', 'payment__event',
            'requested_by', 'verified_by', 'processed_by'
        )


@admin.register(RefundAssociation)
class RefundAssociationAdmin(admin.ModelAdmin):
    """Admin for RefundAssociation model."""
    
    list_display = ('id', 'refund_request', 'get_target', 'amount', 'description')
    list_filter = ('target_type', 'refund_request__verification_status')
    search_fields = ('description', 'refund_request__tracking_reference')
    readonly_fields = ('id', 'target_object')
    
    fieldsets = (
        ('Association', {
            'fields': ('refund_request', 'target_type', 'target_id', 'target_object')
        }),
        ('Amount', {
            'fields': ('amount', 'description')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )
    
    def get_target(self, obj):
        """Display linked target object."""
        if obj.target_object:
            return format_html(
                '<a href="{}">{}</a>',
                f'/admin/{obj.target_type.app_label}/{obj.target_type.model}/{obj.target_id}/change/',
                str(obj.target_object)
            )
        return '-'
    get_target.short_description = 'Target'


@admin.register(RefundPolicy)
class RefundPolicyAdmin(admin.ModelAdmin):
    """Admin for RefundPolicy model."""
    
    list_display = ('event', 'policy_type', 'refundable_within_days', 'percentage_refund')
    list_filter = ('policy_type',)
    search_fields = ('event__name', 'notes')
    
    fieldsets = (
        ('Event', {
            'fields': ('event',)
        }),
        ('Policy Configuration', {
            'fields': ('policy_type', 'refundable_within_days', 'percentage_refund')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    """Enhanced admin for Donation model."""
    
    list_display = (
        'tracking_reference', 'get_payment', 'amount', 'verification_status',
        'donated_by', 'donated_at'
    )
    list_filter = ('verification_status', 'donated_at')
    search_fields = (
        'tracking_reference', 'payment__payment_reference',
        'donated_by__username', 'donated_by__email'
    )
    readonly_fields = (
        'donation_id', 'tracking_reference', 'donated_at',
        'verified_updated_at', 'processed_at', 'auto_processed'
    )
    date_hierarchy = 'donated_at'
    
    fieldsets = (
        ('Donation Information', {
            'fields': ('donation_id', 'tracking_reference', 'payment', 'amount')
        }),
        ('Status', {
            'fields': ('verification_status', 'auto_processed')
        }),
        ('Donation Details', {
            'fields': ('donated_by', 'donated_at')
        }),
        ('Verification', {
            'fields': ('verified_by', 'verified_updated_at'),
            'classes': ('collapse',)
        }),
        ('Processing', {
            'fields': ('processed_by', 'processed_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['verify_donations', 'process_donations']
    
    def get_payment(self, obj):
        """Display linked payment."""
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:payments_payment_change', args=[obj.payment.id]),
            obj.payment.payment_reference
        )
    get_payment.short_description = 'Payment'
    
    def verify_donations(self, request, queryset):
        """Bulk action to verify donations."""
        from apps.payments.models.refunds import VerificationStatus
        pending = queryset.filter(verification_status=VerificationStatus.PENDING)
        
        for donation in pending:
            donation.mark_verified(request.user)
        
        self.message_user(request, f'{pending.count()} donation(s) verified.')
    verify_donations.short_description = 'Verify selected donations'
    
    def process_donations(self, request, queryset):
        """Bulk action to process verified donations."""
        from apps.payments.models.refunds import VerificationStatus
        verified = queryset.filter(verification_status=VerificationStatus.VERIFIED)
        
        for donation in verified:
            donation.mark_processed(request.user)
        
        self.message_user(request, f'{verified.count()} donation(s) processed.')
    process_donations.short_description = 'Process verified donations'
    
    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related(
            'payment', 'donated_by', 'verified_by', 'processed_by'
        )


@admin.register(PaymentHistoryAction)
class PaymentHistoryActionAdmin(admin.ModelAdmin):
    """Admin for PaymentHistoryAction model (read-only)."""
    
    list_display = ('get_payment', 'action', 'description', 'performed_by', 'timestamp')
    list_filter = ('action', 'timestamp')
    search_fields = ('description', 'notes', 'payment__payment_reference', 'action')
    readonly_fields = ('action_id', 'payment', 'action', 'description', 'metadata', 'performed_by', 'timestamp', 'notes')
    date_hierarchy = 'timestamp'
    
    fieldsets = (
        ('Action Information', {
            'fields': ('action_id', 'payment', 'action', 'description')
        }),
        ('Details', {
            'fields': ('performed_by', 'timestamp', 'notes')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )
    
    def get_payment(self, obj):
        """Display linked payment."""
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:payments_payment_change', args=[obj.payment.id]),
            obj.payment.payment_reference
        )
    get_payment.short_description = 'Payment'
    
    def has_add_permission(self, request):
        """History actions are created automatically."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """History actions should not be deleted."""
        return False
    
    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related('payment', 'performed_by')

