from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Event, EventType, EventAuthorization, EventPermission, 
    EventPermissionAssignment, EventReview, EventRole, 
    EventRoleAssignment, EventStaff, EventStaffAvailability
)


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ('title', 'code', 'created_at', 'created_by')
    search_fields = ('title', 'code', 'description')
    list_filter = ('created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'code', 'description')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'display_code', 'status', 'event_type', 'start_datetime', 'end_datetime', 'created_by')
    list_filter = ('status', 'event_type', 'created_at', 'start_datetime')
    search_fields = ('title', 'display_code', 'display_identifier', 'short_description')
    readonly_fields = ('event_id', 'created_at', 'updated_at', 'url_safe_title', 'deleted_at', 'deleted_by')
    date_hierarchy = 'start_datetime'
    
    fieldsets = (
        ('Identifiers', {
            'fields': ('event_id', 'display_code', 'display_identifier')
        }),
        ('Basic Information', {
            'fields': ('title', 'url_safe_title', 'event_type', 'status', 'timezone')
        }),
        ('Descriptions', {
            'fields': ('short_description', 'long_description', 'what_to_bring', 'important_information')
        }),
        ('Event Details', {
            'fields': ('theme', 'anchor_verse', 'expected_attendance', 'maximum_attendance')
        }),
        ('Schedule', {
            'fields': ('start_datetime', 'end_datetime')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Soft Delete', {
            'fields': ('deleted_at', 'deleted_by'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventAuthorization)
class EventAuthorizationAdmin(admin.ModelAdmin):
    list_display = ('event', 'reviewed_by', 'status', 'reviewed_at', 'review_code')
    list_filter = ('status', 'reviewed_at')
    search_fields = ('event__title', 'reviewed_by__email', 'review_code', 'reason')
    readonly_fields = ('review_id', 'review_code', 'reviewed_at')
    
    fieldsets = (
        ('Review Information', {
            'fields': ('review_id', 'review_code', 'event', 'reviewed_by', 'status')
        }),
        ('Details', {
            'fields': ('reason', 'notes')
        }),
        ('Metadata', {
            'fields': ('reviewed_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventPermission)
class EventPermissionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('permission_id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('permission_id', 'name', 'code', 'description', 'category')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventPermissionAssignment)
class EventPermissionAssignmentAdmin(admin.ModelAdmin):
    list_display = ('event', 'user', 'permission', 'assigned_by', 'assigned_at')
    list_filter = ('assigned_at', 'permission__category')
    search_fields = ('event__title', 'user__email', 'permission__name')
    readonly_fields = ('assigned_at',)
    autocomplete_fields = ('event', 'user', 'permission')
    
    fieldsets = (
        ('Assignment', {
            'fields': ('event', 'user', 'permission', 'assigned_by')
        }),
        ('Metadata', {
            'fields': ('assigned_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventReview)
class EventReviewAdmin(admin.ModelAdmin):
    list_display = ('event', 'user', 'rating', 'approved', 'created_at')
    list_filter = ('approved', 'rating', 'created_at')
    search_fields = ('event__title', 'user__email', 'comment')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Review Information', {
            'fields': ('event', 'user', 'rating', 'comment', 'approved')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['approve_reviews', 'reject_reviews']
    
    def approve_reviews(self, request, queryset):
        queryset.update(approved=True)
    approve_reviews.short_description = "Approve selected reviews"
    
    def reject_reviews(self, request, queryset):
        queryset.update(approved=False)
    reject_reviews.short_description = "Reject selected reviews"


@admin.register(EventRole)
class EventRoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'description', 'category')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventRoleAssignment)
class EventRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ('event', 'user', 'role', 'assigned_by', 'assigned_at')
    list_filter = ('assigned_at', 'role__category')
    search_fields = ('event__title', 'user__email', 'role__name')
    readonly_fields = ('assigned_at',)
    autocomplete_fields = ('event', 'user', 'role')
    
    fieldsets = (
        ('Assignment', {
            'fields': ('event', 'user', 'role', 'assigned_by')
        }),
        ('Metadata', {
            'fields': ('assigned_at',),
            'classes': ('collapse',)
        }),
    )


class EventStaffAvailabilityInline(admin.TabularInline):
    model = EventStaffAvailability
    extra = 1
    readonly_fields = ('created_at', 'updated_at')


@admin.register(EventStaff)
class EventStaffAdmin(admin.ModelAdmin):
    list_display = ('staff_id', 'event', 'user', 'assigned_by', 'assigned_at')
    list_filter = ('assigned_at',)
    search_fields = ('event__title', 'user__email', 'notes')
    readonly_fields = ('staff_id', 'assigned_at')
    inlines = [EventStaffAvailabilityInline]
    
    fieldsets = (
        ('Staff Information', {
            'fields': ('staff_id', 'event', 'user', 'assigned_by', 'notes')
        }),
        ('Metadata', {
            'fields': ('assigned_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventStaffAvailability)
class EventStaffAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('staff', 'available_from', 'available_to', 'created_at')
    list_filter = ('created_at', 'available_from')
    search_fields = ('staff__event__title', 'staff__user__email')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Availability', {
            'fields': ('staff', 'available_from', 'available_to')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
