from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Organisation, OrganisationContact, OrganisationControl, Leader,
    InvolvedEventOrganisation, EventSponsor, EventSponsorPackage
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
    list_display = ('title', 'external_website', 'created_by', 'added_at')
    list_filter = ('added_at', 'updated_at')
    search_fields = ('title', 'description')
    readonly_fields = ('added_at', 'updated_at', 'landing_image_uploaded_at', 'logo_uploaded_at')
    inlines = [OrganisationContactInline, OrganisationControlInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'external_website')
        }),
        ('Images', {
            'fields': ('landing_image', 'landing_image_uploaded_at', 'logo', 'logo_uploaded_at')
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
    list_display = ('user', 'get_authority_object', 'target_type', 'added_by', 'added_at')
    list_filter = ('target_type', 'added_at')
    search_fields = ('user__email', 'notes')
    readonly_fields = ('added_at', 'updated_at')
    autocomplete_fields = ('user',)
    
    fieldsets = (
        ('Leadership Information', {
            'fields': ('user', 'target_type', 'target_id', 'notes')
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


class EventSponsorPackageInline(admin.TabularInline):
    model = EventSponsorPackage
    extra = 1
    readonly_fields = ('added_at', 'updated_at')
    fields = ('event', 'package_name', 'package_description', 'price', 'currency')


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
    list_display = ('package_name', 'sponsor', 'event', 'amount', 'added_at')
    list_filter = ('added_at', 'updated_at', 'amount')
    search_fields = ('package_name', 'sponsor__name', 'event__title', 'package_description')
    readonly_fields = ('added_at', 'updated_at')
    autocomplete_fields = ('sponsor', 'event')
    
    fieldsets = (
        ('Package Information', {
            'fields': ('package_name', 'package_description', 'sponsor', 'event')
        }),
        ('Payment Details', {
            'fields': ('amount',)
        }),
        ('Metadata', {
            'fields': ('added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
