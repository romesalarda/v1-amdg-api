from django.contrib import admin

from apps.workshops.models.workshop import Workshop
from apps.workshops.models.registration import WorkshopRegistration
from apps.workshops.models.interest import WorkshopInterestSubmission, WorkshopInterestRank
from apps.workshops.models.staff import WorkshopStaff


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class WorkshopRegistrationInline(admin.TabularInline):
    model = WorkshopRegistration
    extra = 0
    readonly_fields = ('registration_id', 'booking_reference', 'registered_at', 'allocation_method', 'allocated_by')
    fields = ('attendee', 'status', 'allocation_method', 'allocated_by', 'booking_reference', 'registered_at')
    show_change_link = True


class WorkshopStaffInline(admin.TabularInline):
    model = WorkshopStaff
    extra = 0
    readonly_fields = ('added_at', 'added_by')
    fields = ('event_staff', 'role', 'notes', 'added_by', 'added_at')


class WorkshopInterestRankInline(admin.TabularInline):
    model = WorkshopInterestRank
    extra = 0
    fields = ('rank', 'workshop')
    ordering = ('rank',)


# ---------------------------------------------------------------------------
# ModelAdmin registrations
# ---------------------------------------------------------------------------

@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ('title', 'event', 'date', 'status', 'allocation_mode', 'capacity', 'current_registration_count', 'is_full')
    list_filter = ('status', 'allocation_mode', 'event')
    search_fields = ('title', 'description', 'event__title')
    readonly_fields = ('current_registration_count', 'is_full')
    ordering = ('date',)
    inlines = [WorkshopRegistrationInline, WorkshopStaffInline]
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'event', 'date', 'notes'),
        }),
        ('Venue', {
            'fields': ('venue', 'room'),
        }),
        ('Registration & Allocation', {
            'fields': (
                'status', 'allocation_mode', 'capacity',
                'duration_minutes', 'registration_opens_at', 'registration_closes_at',
                'current_registration_count', 'is_full',
            ),
        }),
        ('Verification', {
            'fields': ('verification_status',),
            'classes': ('collapse',),
        }),
    )

    def current_registration_count(self, obj):
        return obj.current_registration_count
    current_registration_count.short_description = 'Confirmed'

    def is_full(self, obj):
        return obj.is_full
    is_full.boolean = True
    is_full.short_description = 'Full?'


@admin.register(WorkshopRegistration)
class WorkshopRegistrationAdmin(admin.ModelAdmin):
    list_display = ('booking_reference', 'workshop', 'attendee', 'status', 'allocation_method', 'registered_at')
    list_filter = ('status', 'allocation_method', 'workshop__event')
    search_fields = ('booking_reference', 'attendee__first_name', 'attendee__last_name', 'workshop__title')
    readonly_fields = ('registration_id', 'booking_reference', 'registered_at')
    ordering = ('-registered_at',)
    fieldsets = (
        (None, {
            'fields': ('registration_id', 'booking_reference', 'workshop', 'attendee', 'registered_at'),
        }),
        ('Allocation', {
            'fields': ('status', 'allocation_method', 'allocated_by', 'notes'),
        }),
        ('Verification', {
            'fields': ('verification_status',),
            'classes': ('collapse',),
        }),
    )


@admin.register(WorkshopInterestSubmission)
class WorkshopInterestSubmissionAdmin(admin.ModelAdmin):
    list_display = ('submission_id', 'event', 'attendee', 'is_finalised', 'submitted_at', 'rank_count')
    list_filter = ('is_finalised', 'event')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'event__title')
    readonly_fields = ('submission_id', 'submitted_at', 'updated_at')
    ordering = ('-submitted_at',)
    inlines = [WorkshopInterestRankInline]

    def rank_count(self, obj):
        return obj.ranks.count()
    rank_count.short_description = 'Ranks'


@admin.register(WorkshopStaff)
class WorkshopStaffAdmin(admin.ModelAdmin):
    list_display = ('workshop', 'event_staff', 'role', 'added_at', 'added_by')
    list_filter = ('role', 'workshop__event')
    search_fields = ('workshop__title', 'event_staff__user__email')
    readonly_fields = ('added_at',)
    ordering = ('-added_at',)
