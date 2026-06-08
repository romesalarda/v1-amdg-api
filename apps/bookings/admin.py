from django.contrib import admin
from django.utils.html import format_html
from apps.bookings.models import (
    Booking, BookingIntent, BookingIntentStatusChoices,
    BookingPackage, BookingPackageRule,
    TicketType, Ticket,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
    PackageProduct, Delegation, DelegationType, DelegationHead, DelegationHeadRoleChoices, DelegationHeadInvite
)

from django.utils import timezone
from django.core.exceptions import ValidationError


class BookingPackageRuleInline(admin.TabularInline):
    model = BookingPackageRule
    extra = 0
    fields = ('rule_type', 'name', 'value', 'active')


@admin.register(BookingPackage)
class BookingPackageAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'event', 'ticket_type', 'base_amount',
        'percentage_modifier', 'is_active', 'created_at'
    )
    list_filter = ('is_active', 'event', 'ticket_type', 'created_at')
    search_fields = ('name', 'event__title', 'description')
    readonly_fields = ('created_at', 'updated_at', 'modified_amount')
    inlines = [BookingPackageRuleInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'event', 'ticket_type', 'is_active')
        }),
        ('Pricing', {
            'fields': ('base_amount', 'percentage_modifier', 'modified_amount')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'event', 'ticket_type', 'created_by'
        )


@admin.register(BookingPackageRule)
class BookingPackageRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'booking_package', 'rule_type', 'value', 'active')
    list_filter = ('rule_type', 'active')
    search_fields = ('name', 'booking_package__name', 'value')
    

@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'code', 'event', 'scope', 'valid_from',
        'valid_until', 'is_active', 'max_entries'
    )
    list_filter = ('scope', 'is_active', 'event', 'valid_from')
    search_fields = ('title', 'code', 'event__title')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'code', 'event', 'is_active')
        }),
        ('Scope & Validity', {
            'fields': ('scope', 'valid_from', 'valid_until', 'max_entries')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'event', 'created_by'
        )


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_code', 'attendee', 'ticket_type',
        'status', 'package', 'issued_at'
    )
    list_filter = ('status', 'ticket_type', 'issued_at')
    search_fields = (
        'ticket_code', 'attendee__first_name', 'attendee__last_name'
    )
    readonly_fields = ('ticket_id', 'ticket_code', 'issued_at')
    
    fieldsets = (
        ('Ticket Information', {
            'fields': ('ticket_id', 'ticket_code', 'attendee')
        }),
        ('Type & Package', {
            'fields': ('ticket_type', 'package', 'payment', 'status')
        }),
        ('Metadata', {
            'fields': ('issued_at', 'uses'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'attendee', 'ticket_type', 'package', 'payment'
        )


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'booking_reference', 'event', 'made_by', 'attendee_count',
        'booked_at'
    )
    list_filter = ('event', 'booked_at')
    search_fields = (
        'booking_reference', 'made_by__username', 'made_by__email',
        'event__title'
    )
    readonly_fields = ('booking_reference', 'booked_at')
    
    fieldsets = (
        ('Booking Information', {
            'fields': ('booking_reference', 'event', 'made_by')
        }),
        ('Metadata', {
            'fields': ('booked_at',),
            'classes': ('collapse',)
        }),
    )
    
    def attendee_count(self, obj):
        return obj.attendees.count()
    attendee_count.short_description = 'Attendees'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'event', 'made_by'
        ).prefetch_related('attendees')


@admin.register(BookingIntent)
class BookingIntentAdmin(admin.ModelAdmin):
    list_display = (
        'booking_intent_id', 'event', 'made_by', 'intended_ticket_count',
        'status', 'is_active_status', 'created_at', 'expires_at'
    )
    list_filter = ('status', 'event', 'created_at', 'expires_at')
    search_fields = (
        'booking_intent_id', 'made_by__username', 'made_by__email',
        'event__title', 'event__display_code'
    )
    readonly_fields = (
        'booking_intent_id', 'created_at', 'expires_at', 'complete_delete_at',
        'deleted_at', 'is_expired', 'is_active'
    )
    
    fieldsets = (
        ('Intent Information', {
            'fields': ('booking_intent_id', 'event', 'made_by', 'intended_ticket_count')
        }),
        ('Status', {
            'fields': ('status', 'is_expired', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'expires_at', 'complete_delete_at', 'deleted_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_expired', 'mark_as_cancelled', 'soft_delete_intents']
    
    def is_active_status(self, obj):
        """Display active status with color indicator."""
        if obj.is_active:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: red;">✗ Inactive</span>'
        )
    is_active_status.short_description = 'Active'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('event', 'made_by')
    
    @admin.action(description='Mark selected intents as expired')
    def mark_as_expired(self, request, queryset):
        """Admin action to mark intents as expired."""
        count = 0
        for intent in queryset.filter(status=BookingIntentStatusChoices.PENDING):
            intent.mark_expired(save=True)
            count += 1
        self.message_user(request, f'{count} intent(s) marked as expired.')
    
    @admin.action(description='Cancel selected intents')
    def mark_as_cancelled(self, request, queryset):
        """Admin action to cancel intents."""
        count = 0
        for intent in queryset.filter(status=BookingIntentStatusChoices.PENDING):
            intent.cancel(save=True)
            count += 1
        self.message_user(request, f'{count} intent(s) cancelled.')
    
    @admin.action(description='Soft delete selected intents')
    def soft_delete_intents(self, request, queryset):
        """Admin action to soft delete intents."""
        from django.utils import timezone
        count = queryset.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
        self.message_user(request, f'{count} intent(s) soft deleted.')


class AttendeeAlternativeSigninInline(admin.TabularInline):
    model = AttendeeAlternativeSigninIdentifier
    extra = 0
    fields = ('identifier', 'event_alternative_signin', 'ticket', 'uses', 'defined_by', 'defined_at')
    readonly_fields = ('sign_id', 'defined_at', 'updated_at', 'uses')
    autocomplete_fields = ['ticket', 'event_alternative_signin', 'defined_by']


@admin.register(EventAlternativeSigninIdentifier)
class EventAlternativeSigninIdentifierAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'event', 'is_active', 'verification_status',
        'max_uses_per_signin', 'created_at'
    )
    list_filter = (
        'is_active', 'verification_status', 'event', 'created_at'
    )
    search_fields = ('title', 'description', 'event__title', 'event__display_code')
    readonly_fields = (
        'id', 'created_at', 'updated_at', 'verified_updated_at',
        'processed_at'
    )
    inlines = [AttendeeAlternativeSigninInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'title', 'description', 'event')
        }),
        ('Configuration', {
            'fields': ('format_match', 'max_uses_per_signin', 'is_active')
        }),
        ('Verification Status', {
            'fields': (
                'verification_status', 'verified_by', 'verified_updated_at',
                'processed_by', 'processed_at', 'auto_processed'
            ),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'event', 'verified_by', 'processed_by'
        )


@admin.register(AttendeeAlternativeSigninIdentifier)
class AttendeeAlternativeSigninIdentifierAdmin(admin.ModelAdmin):
    list_display = (
        'identifier', 'attendee', 'event_alternative_signin',
        'uses', 'has_ticket', 'is_valid_status', 'defined_at'
    )
    list_filter = (
        'event_alternative_signin__event',
        'event_alternative_signin',
        'defined_at'
    )
    search_fields = (
        'identifier', 'attendee__first_name', 'attendee__last_name',
        'attendee__attendee_display_id', 'ticket__ticket_code',
        'event_alternative_signin__title'
    )
    readonly_fields = (
        'sign_id', 'defined_at', 'updated_at', 'uses'
    )
    autocomplete_fields = ['attendee', 'ticket', 'event_alternative_signin', 'defined_by']
    
    fieldsets = (
        ('Identifier Information', {
            'fields': ('sign_id', 'identifier', 'event_alternative_signin')
        }),
        ('Associated Records', {
            'fields': ('attendee', 'ticket')
        }),
        ('Usage Tracking', {
            'fields': ('uses',)
        }),
        ('Metadata', {
            'fields': ('defined_by', 'defined_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_ticket(self, obj):
        return obj.has_ticket
    has_ticket.boolean = True
    has_ticket.short_description = 'Has Ticket'
    
    def is_valid_status(self, obj):
        return obj.is_valid
    is_valid_status.boolean = True
    is_valid_status.short_description = 'Valid'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'attendee', 'ticket', 'event_alternative_signin',
            'event_alternative_signin__event', 'defined_by'
        )


@admin.register(PackageProduct)
class PackageProductAdmin(admin.ModelAdmin):
    list_display = (
        'booking_package', 'product', 'quantity_per_attendee',
        'base_amount', 'percentage_modifier', 'modified_amount',
        'added_at'
    )
    list_filter = (
        'booking_package__event', 'booking_package', 'added_at'
    )
    search_fields = (
        'booking_package__name', 'product__name',
        'booking_package__event__title'
    )
    readonly_fields = (
        'base_amount', 'modified_amount', 'added_at', 'updated_at'
    )
    autocomplete_fields = ['booking_package', 'product', 'added_by']
    
    fieldsets = (
        ('Package Product Information', {
            'fields': ('booking_package', 'product', 'quantity_per_attendee')
        }),
        ('Pricing', {
            'fields': ('base_amount', 'percentage_modifier', 'modified_amount')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'booking_package', 'product', 'booking_package__event', 'added_by'
        )

class DelegationHeadInline(admin.TabularInline):
    model = DelegationHead
    extra = 0
    fields = ('attendee', 'user', 'role', 'added_by', 'added_at')
    readonly_fields = ('added_at',)
    autocomplete_fields = ['attendee', 'user', 'added_by']

@admin.register(Delegation)
class DelegationAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'contact_email', 'contact_phone', 'is_location_based', 'created_at')
    list_filter = ('type', 'created_at')
    search_fields = ('name', 'description', 'contact_email', 'contact_phone')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [DelegationHeadInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'type')
        }),
        ('Contact Information', {
            'fields': ('contact_email', 'contact_phone')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by')
    

@admin.register(DelegationHead)
class DelegationHeadAdmin(admin.ModelAdmin):
    list_display = ('user', 'attendee', 'delegation', 'role', 'added_at')
    list_filter = ('role', 'added_at', 'delegation__type')
    search_fields = (
        'user__username', 'user__email',
        'attendee__first_name', 'attendee__last_name',
        'delegation__name'
    )
    readonly_fields = ('added_at',)
    autocomplete_fields = ['user', 'attendee', 'delegation', 'added_by']
    
    fieldsets = (
        ('Delegation Head Information', {
            'fields': ('user', 'attendee', 'delegation', 'role')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'attendee', 'delegation', 'added_by'
        )
    
@admin.register(DelegationHeadInvite)
class DelegationHeadInviteAdmin(admin.ModelAdmin):
    list_display = ('email', 'delegation', 'role', 'status', 'expires_at', 'invited_at')
    list_filter = ('role', 'invited_at', 'expires_at')
    search_fields = ('email', 'delegation__name')
    readonly_fields = ('invite_id', 'invited_at', 'accepted_at')
    autocomplete_fields = ['delegation', 'user', 'invited_by', 'accepted_by']
    
    fieldsets = (
        ('Invitation Information', {
            'fields': ('invite_id', 'delegation', 'email', 'role')
        }),
        ('Status & Expiry', {
            'fields': ('status', 'expires_at')
        }),
        ('Metadata', {
            'fields': ('invited_by', 'invited_at', 'accepted_by', 'accepted_at'),
            'classes': ('collapse',)
        }),
    )
    
    def status(self, obj):
        if obj.accepted_at:
            return format_html('<span style="color: green; font-weight: bold;">✓ Accepted</span>')
        elif obj.expires_at and obj.expires_at < timezone.now():
            return format_html('<span style="color: red;">✗ Expired</span>')
        else:
            return format_html('<span style="color: orange;">⏳ Pending</span>')
    status.short_description = 'Status'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'delegation', 'user', 'invited_by', 'accepted_by'
        )