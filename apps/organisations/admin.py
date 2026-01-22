from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Organisation, OrganisationContact, OrganisationControl, Leader,
    InvolvedEventOrganisation, EventSponsor, EventSponsorPackage,
    UserOrganisationMembership, OrganisationInvite, OrganisationAcceptanceCode
)


class OrganisationContactInline(admin.TabularInline):
    model = OrganisationContact
    extra = 1
    readonly_fields = ('added_at', 'updated_at')


class OrganisationControlInline(admin.TabularInline):
    model = OrganisationControl
    extra = 1
    readonly_fields = ('added_at',)
    autocomplete_fields = ('user',)


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ('title', 'external_website', 'required_acceptance_code', 'requires_manual_verification', 'created_by', 'added_at')
    list_filter = ('required_acceptance_code', 'requires_manual_verification', 'added_at', 'updated_at')
    search_fields = ('title', 'description')
    readonly_fields = ('added_at', 'updated_at', 'landing_image_uploaded_at', 'logo_uploaded_at', 'landing_image_preview', 'logo_preview')
    inlines = [OrganisationContactInline, OrganisationControlInline]
    autocomplete_fields = ('created_by',)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'external_website')
        }),
        ('Verification Settings', {
            'fields': ('required_acceptance_code', 'requires_manual_verification')
        }),
        ('Images', {
            'fields': ('landing_image', 'landing_image_preview', 'landing_image_uploaded_at', 'logo', 'logo_preview', 'logo_uploaded_at')
        }),
        ('Metadata', {
            'fields': ('created_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def landing_image_preview(self, obj):
        if obj.landing_image:
            return format_html('<img src="{}" width="100" height="100" />', obj.landing_image.url)
        return '-'
    landing_image_preview.short_description = 'Landing Image Preview'
    
    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" width="50" height="50" />', obj.logo.url)
        return '-'
    logo_preview.short_description = 'Logo Preview'


@admin.register(OrganisationContact)
class OrganisationContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'organisation', 'email', 'phone', 'label', 'added_at')
    list_filter = ('added_at', 'updated_at')
    search_fields = ('name', 'email', 'phone', 'organisation__title')
    readonly_fields = ('added_at', 'updated_at')
    
    fieldsets = (
        ('Contact Information', {
            'fields': ('organisation', 'name', 'email', 'phone', 'label')
        }),
        ('Metadata', {
            'fields': ('added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(OrganisationControl)
class OrganisationControlAdmin(admin.ModelAdmin):
    list_display = ('organisation', 'user', 'added_by', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('organisation__title', 'user__email')
    readonly_fields = ('added_at',)
    autocomplete_fields = ('organisation', 'user')
    
    fieldsets = (
        ('Control Information', {
            'fields': ('organisation', 'user', 'added_by')
        }),
        ('Metadata', {
            'fields': ('added_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(Leader)
class LeaderAdmin(admin.ModelAdmin):
    list_display = ('user', 'organisation', 'get_authority_object', 'target_type', 'added_by', 'added_at')
    list_filter = ('target_type', 'organisation', 'added_at')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'organisation__title', 'notes')
    readonly_fields = ('added_at', 'updated_at')
    autocomplete_fields = ('user', 'organisation', 'added_by')
    list_select_related = ('user', 'organisation', 'added_by', 'target_type')
    
    fieldsets = (
        ('Leadership Information', {
            'fields': ('user', 'organisation', 'target_type', 'target_id', 'notes')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_authority_object(self, obj):
        return str(obj.authority_object) if obj.authority_object else '-'
    get_authority_object.short_description = 'Authority Object'


@admin.register(InvolvedEventOrganisation)
class InvolvedEventOrganisationAdmin(admin.ModelAdmin):
    list_display = ('organisation', 'event', 'role', 'added_by', 'added_at')
    list_filter = ('role', 'added_at')
    search_fields = ('organisation__title', 'event__title', 'event__display_code')
    readonly_fields = ('added_at',)
    autocomplete_fields = ('organisation', 'event')
    
    fieldsets = (
        ('Involvement Information', {
            'fields': ('organisation', 'event', 'role')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at'),
            'classes': ('collapse',)
        }),
    )


class EventSponsorPackageInline(admin.StackedInline):
    model = EventSponsorPackage
    extra = 1
    readonly_fields = ('added_at', 'updated_at')
    fields = ('event', 'package_name', 'package_description', 'base_amount', 'percentage_modifier', 'added_at', 'updated_at')


@admin.register(EventSponsor)
class EventSponsorAdmin(admin.ModelAdmin):
    list_display = ('name', 'organisation', 'event', 'added_by', 'added_at')
    list_filter = ('added_at', 'updated_at')
    search_fields = ('name', 'organisation__title', 'event__title', 'event__display_code', 'description')
    readonly_fields = ('added_at', 'updated_at')
    autocomplete_fields = ('organisation', 'event')
    inlines = [EventSponsorPackageInline]
    
    fieldsets = (
        ('Sponsor Information', {
            'fields': ('name', 'description', 'organisation', 'event')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventSponsorPackage)
class EventSponsorPackageAdmin(admin.ModelAdmin):
    list_display = ('package_name', 'sponsor', 'event', 'base_amount', 'added_at')
    list_filter = ('added_at', 'updated_at', 'base_amount')
    search_fields = ('package_name', 'sponsor__name', 'event__title', 'package_description')
    readonly_fields = ('added_at', 'updated_at')
    autocomplete_fields = ('sponsor', 'event')
    
    fieldsets = (
        ('Package Information', {
            'fields': ('package_name', 'package_description', 'sponsor', 'event')
        }),
        ('Payment Details', {
            'fields': ('base_amount', 'percentage_modifier')
        }),
        ('Metadata', {
            'fields': ('added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserOrganisationMembership)
class UserOrganisationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organisation', 'verified_at', 'added_by', 'added_at')
    list_filter = ('added_at', 'verified_at', 'organisation')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'organisation__title')
    readonly_fields = ('added_at', 'verified_at', 'requires_verification')
    autocomplete_fields = ('organisation', 'user', 'added_by')
    
    fieldsets = (
        ('Membership Information', {
            'fields': ('organisation', 'user', 'added_by')
        }),
        ('Verification', {
            'fields': ('verified_at', 'requires_verification')
        }),
        ('Metadata', {
            'fields': ('added_at',),
            'classes': ('collapse',)
        }),
    )
    
    def requires_verification(self, obj):
        return obj.requires_verification
    requires_verification.short_description = 'Requires Verification'
    requires_verification.boolean = True


@admin.register(OrganisationInvite)
class OrganisationInviteAdmin(admin.ModelAdmin):
    list_display = ('id', 'organisation', 'target_user', 'invited_by', 'accepted', 'is_valid_status', 'added_at', 'expires_at')
    list_filter = ('accepted', 'is_active', 'added_at', 'accepted_at', 'expires_at')
    search_fields = ('organisation__title', 'target_user__email', 'target_user__first_name', 'target_user__last_name')
    readonly_fields = ('id', 'added_at', 'accepted_at', 'is_valid_status')
    autocomplete_fields = ('organisation', 'target_user', 'invited_by')
    
    fieldsets = (
        ('Invite Information', {
            'fields': ('id', 'organisation', 'target_user', 'invited_by')
        }),
        ('Status', {
            'fields': ('accepted', 'accepted_at', 'is_active', 'is_valid_status', 'expires_at')
        }),
        ('Metadata', {
            'fields': ('added_at',),
            'classes': ('collapse',)
        }),
    )
    
    def is_valid_status(self, obj):
        return obj.is_valid
    is_valid_status.short_description = 'Is Valid'
    is_valid_status.boolean = True


@admin.register(OrganisationAcceptanceCode)
class OrganisationAcceptanceCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'organisation', 'uses', 'max_uses', 'is_active', 'is_valid_status', 'expires_at', 'added_at')
    list_filter = ('is_active', 'added_at', 'expires_at')
    search_fields = ('code', 'organisation__title')
    readonly_fields = ('added_at', 'uses', 'is_valid_status', 'is_single_use_display')
    autocomplete_fields = ('organisation', 'added_by')
    
    fieldsets = (
        ('Code Information', {
            'fields': ('code', 'organisation', 'added_by')
        }),
        ('Usage & Status', {
            'fields': ('uses', 'max_uses', 'is_single_use_display', 'is_active', 'is_valid_status', 'expires_at')
        }),
        ('Metadata', {
            'fields': ('added_at',),
            'classes': ('collapse',)
        }),
    )
    
    def is_valid_status(self, obj):
        return obj.is_valid
    is_valid_status.short_description = 'Is Valid'
    is_valid_status.boolean = True
    
    def is_single_use_display(self, obj):
        return obj.is_single_use
    is_single_use_display.short_description = 'Single Use'
    is_single_use_display.boolean = True
