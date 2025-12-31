from django.contrib import admin
from django.utils.html import format_html
from .models import AvailabilityWindow, Resource, AccessRule


@admin.register(AvailabilityWindow)
class AvailabilityWindowAdmin(admin.ModelAdmin):
    list_display = ('name', 'availability_type', 'get_target', 'available_from', 'available_to', 'timezone')
    list_filter = ('availability_type', 'timezone', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('availability_id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('availability_id', 'name', 'description', 'availability_type')
        }),
        ('Target', {
            'fields': ('target_type', 'target_id')
        }),
        ('Availability Period', {
            'fields': ('available_from', 'available_to', 'timezone')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_target(self, obj):
        return str(obj.target) if obj.target else '-'
    get_target.short_description = 'Target'


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'resource_type', 'get_target', 'public', 'added_by', 'created_at')
    list_filter = ('resource_type', 'public', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'resource_type', 'public')
        }),
        ('Target', {
            'fields': ('target_type', 'target_id', 'protected')
        }),
        ('Resource Content', {
            'fields': ('file', 'link', 'image')
        }),
        ('Metadata', {
            'fields': ('added_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_target(self, obj):
        return str(obj.target) if obj.target else '-'
    get_target.short_description = 'Target'
    
    def resource_preview(self, obj):
        if obj.resource_type == 'IMAGE' and obj.image:
            return format_html('<img src="{}" width="100" height="100" />', obj.image.url)
        elif obj.resource_type == 'LINK' and obj.link:
            return format_html('<a href="{}" target="_blank">{}</a>', obj.link, obj.link)
        elif obj.file:
            return format_html('<a href="{}" target="_blank">Download File</a>', obj.file.url)
        return '-'
    resource_preview.short_description = 'Preview'


@admin.register(AccessRule)
class AccessRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'rule_type', 'get_target', 'value', 'active', 'added_by', 'created_at')
    list_filter = ('rule_type', 'active', 'created_at', 'target_type')
    search_fields = ('name', 'description', 'value', 'rule_id')
    readonly_fields = ('rule_id', 'created_at', 'updated_at')
    autocomplete_fields = ('added_by',)
    
    fieldsets = (
        ('Rule Information', {
            'fields': ('rule_id', 'name', 'description', 'rule_type', 'value', 'active')
        }),
        ('Target', {
            'fields': ('target_type', 'target_id'),
            'description': 'The target object this rule applies to (e.g., Event, Product, Discount)'
        }),
        ('Metadata', {
            'fields': ('added_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_target(self, obj):
        return str(obj.target) if obj.target else '-'
    get_target.short_description = 'Target'
    
    actions = ['activate_rules', 'deactivate_rules']
    
    def activate_rules(self, request, queryset):
        updated = queryset.update(active=True)
        self.message_user(request, f"Successfully activated {updated} rule(s)")
    activate_rules.short_description = "Activate selected rules"
    
    def deactivate_rules(self, request, queryset):
        updated = queryset.update(active=False)
        self.message_user(request, f"Successfully deactivated {updated} rule(s)")
    deactivate_rules.short_description = "Deactivate selected rules"
