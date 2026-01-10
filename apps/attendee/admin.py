from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Attendee, AttendeeGuardian, AttendeeAction,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    EmergencyContact, FamilyGroup, FamilyAttendee,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    Consent, AttendeeConsent, AttendeeMessage, EventAttendance,
    AttendeeOrganisation
)


# Inline admin classes
class AttendeeGuardianInline(admin.StackedInline):
    model = AttendeeGuardian
    extra = 1
    readonly_fields = ('added_at',)
    autocomplete_fields = ('user',)


class AttendeeActionInline(admin.StackedInline):
    model = AttendeeAction
    extra = 0
    readonly_fields = ('performed_at',)
    fields = ('action', 'performed_by', 'performed_at', 'notes')
    fk_name = 'attendee'


class EmergencyContactInline(admin.StackedInline):
    model = EmergencyContact
    extra = 1
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    fields = ('first_name', 'last_name', 'relationship', 'phone_number', 'email', 'primary_contact', 'verification_status')


class AttendeeDietaryRequirementInline(admin.StackedInline):
    model = AttendeeDietaryRequirement
    extra = 1
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    autocomplete_fields = ('dietary_requirement',)


class AttendeeMedicalConditionInline(admin.StackedInline):
    model = AttendeeMedicalCondition
    extra = 1
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    autocomplete_fields = ('medical_condition',)


class AttendeeAccessibilityRequirementInline(admin.StackedInline):
    model = AttendeeAccessibilityRequirement
    extra = 1
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    autocomplete_fields = ('accessibility_requirement',)


class AttendeeConsentInline(admin.StackedInline):
    model = AttendeeConsent
    extra = 0
    readonly_fields = ('recorded_at', 'given_at')
    autocomplete_fields = ('consent',)


# Main admin classes
@admin.register(Attendee)
class AttendeeAdmin(admin.ModelAdmin):
    list_display = ('attendee_display_id', 'full_name', 'event', 'email', 'phone_number', 'age', 'relationship_to_user', 'created_at')
    list_filter = ('relationship_to_user', 'gender', 'event', 'created_at')
    search_fields = ('attendee_display_id', 'first_name', 'last_name', 'email', 'phone_number')
    readonly_fields = ('attendee_id', 'created_at', 'updated_at', 'age', 'is_minor', 'deleted_at', 'deleted_by')
    autocomplete_fields = ('user', 'event')
    date_hierarchy = 'created_at'
    
    inlines = [
        EmergencyContactInline,
        AttendeeDietaryRequirementInline,
        AttendeeMedicalConditionInline,
        AttendeeAccessibilityRequirementInline,
        AttendeeConsentInline,
        AttendeeGuardianInline,
        AttendeeActionInline,
    ]
    
    fieldsets = (
        ('Identifiers', {
            'fields': ('attendee_id', 'attendee_display_id')
        }),
        ('Personal Information', {
            'fields': ('user', 'first_name', 'last_name', 'date_of_birth', 'gender', 'age', 'is_minor')
        }),
        ('Contact Information', {
            'fields': ('email', 'phone_number')
        }),
        ('Event & Location', {
            'fields': ('event', 'area_from')
        }),
        ('Relationship', {
            'fields': ('relationship_to_user',)
        }),
        ('Metadata', {
            'fields': ('defined_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Soft Delete', {
            'fields': ('deleted_at', 'deleted_by'),
            'classes': ('collapse',)
        }),
    )
    
    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Full Name'
    
    def age(self, obj):
        return obj.age if obj.age is not None else '-'
    age.short_description = 'Age'


@admin.register(AttendeeGuardian)
class AttendeeGuardianAdmin(admin.ModelAdmin):
    list_display = ('user', 'attendee', 'relationship', 'added_at')
    list_filter = ('relationship', 'added_at')
    search_fields = ('user__email', 'attendee__first_name', 'attendee__last_name', 'attendee__attendee_display_id')
    readonly_fields = ('added_at',)
    autocomplete_fields = ('user', 'attendee')
    
    fieldsets = (
        ('Guardian Information', {
            'fields': ('user', 'attendee', 'relationship')
        }),
        ('Metadata', {
            'fields': ('added_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(AttendeeAction)
class AttendeeActionAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'action', 'performed_by', 'performed_at')
    list_filter = ('action', 'performed_at')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'attendee__attendee_display_id', 'notes')
    readonly_fields = ('performed_at',)
    autocomplete_fields = ('attendee', 'performed_by')
    date_hierarchy = 'performed_at'
    
    fieldsets = (
        ('Action Information', {
            'fields': ('action', 'attendee', 'performed_by', 'notes')
        }),
        ('Metadata', {
            'fields': ('performed_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(DietaryRequirement)
class DietaryRequirementAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'active', 'verification_status', 'added_at')
    list_filter = ('active', 'verification_status', 'added_at')
    search_fields = ('code', 'label', 'description')
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    
    fieldsets = (
        ('Requirement Information', {
            'fields': ('code', 'label', 'description', 'active')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_by', 'verified_updated_at')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_verified', 'mark_pending']
    
    def mark_verified(self, request, queryset):
        for obj in queryset:
            obj.mark_verified(request.user)
    mark_verified.short_description = "Mark selected as verified"
    
    def mark_pending(self, request, queryset):
        for obj in queryset:
            obj.mark_pending()
    mark_pending.short_description = "Mark selected as pending"


@admin.register(AttendeeDietaryRequirement)
class AttendeeDietaryRequirementAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'dietary_requirement', 'verification_status', 'added_at')
    list_filter = ('verification_status', 'added_at')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'dietary_requirement__label', 'details')
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    autocomplete_fields = ('attendee', 'dietary_requirement')
    
    fieldsets = (
        ('Assignment', {
            'fields': ('attendee', 'dietary_requirement', 'details')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_by', 'verified_updated_at')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(MedicalCondition)
class MedicalConditionAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'active', 'verification_status', 'added_at')
    list_filter = ('active', 'verification_status', 'added_at')
    search_fields = ('code', 'label', 'description')
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    
    fieldsets = (
        ('Condition Information', {
            'fields': ('code', 'label', 'description', 'active')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_by', 'verified_updated_at')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_verified', 'mark_pending']
    
    def mark_verified(self, request, queryset):
        for obj in queryset:
            obj.mark_verified(request.user)
    mark_verified.short_description = "Mark selected as verified"
    
    def mark_pending(self, request, queryset):
        for obj in queryset:
            obj.mark_pending()
    mark_pending.short_description = "Mark selected as pending"


@admin.register(AttendeeMedicalCondition)
class AttendeeMedicalConditionAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'medical_condition', 'verification_status', 'added_at')
    list_filter = ('verification_status', 'added_at')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'medical_condition__label', 'details')
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    autocomplete_fields = ('attendee', 'medical_condition')
    
    fieldsets = (
        ('Assignment', {
            'fields': ('attendee', 'medical_condition', 'details')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_by', 'verified_updated_at')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'attendee', 'relationship', 'phone_number', 'email', 'primary_contact', 'verification_status')
    list_filter = ('relationship', 'primary_contact', 'verification_status', 'added_at')
    search_fields = ('first_name', 'last_name', 'phone_number', 'email', 'attendee__first_name', 'attendee__last_name')
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at', 'full_name')
    autocomplete_fields = ('attendee',)
    
    fieldsets = (
        ('Contact Information', {
            'fields': ('attendee', 'first_name', 'last_name', 'full_name', 'relationship')
        }),
        ('Contact Details', {
            'fields': ('phone_number', 'email', 'primary_contact')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_by', 'verified_updated_at')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_verified', 'mark_pending', 'set_as_primary']
    
    def mark_verified(self, request, queryset):
        for obj in queryset:
            obj.mark_verified(request.user)
    mark_verified.short_description = "Mark selected as verified"
    
    def mark_pending(self, request, queryset):
        for obj in queryset:
            obj.mark_pending()
    mark_pending.short_description = "Mark selected as pending"
    
    def set_as_primary(self, request, queryset):
        queryset.update(primary_contact=True)
    set_as_primary.short_description = "Set as primary contact"


@admin.register(AccessibilityRequirement)
class AccessibilityRequirementAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'active', 'verification_status', 'added_at')
    list_filter = ('active', 'verification_status', 'added_at')
    search_fields = ('code', 'label', 'description')
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    
    fieldsets = (
        ('Requirement Information', {
            'fields': ('code', 'label', 'description', 'active')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_by', 'verified_updated_at')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_verified', 'mark_pending']
    
    def mark_verified(self, request, queryset):
        for obj in queryset:
            obj.mark_verified(request.user)
    mark_verified.short_description = "Mark selected as verified"
    
    def mark_pending(self, request, queryset):
        for obj in queryset:
            obj.mark_pending()
    mark_pending.short_description = "Mark selected as pending"


@admin.register(AttendeeAccessibilityRequirement)
class AttendeeAccessibilityRequirementAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'accessibility_requirement', 'verification_status', 'added_at')
    list_filter = ('verification_status', 'added_at')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'accessibility_requirement__label', 'details')
    readonly_fields = ('added_at', 'updated_at', 'verified_updated_at')
    autocomplete_fields = ('attendee', 'accessibility_requirement')
    
    fieldsets = (
        ('Assignment', {
            'fields': ('attendee', 'accessibility_requirement', 'details')
        }),
        ('Verification', {
            'fields': ('verification_status', 'verified_by', 'verified_updated_at')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class FamilyAttendeeInline(admin.StackedInline):
    model = FamilyAttendee
    extra = 1
    readonly_fields = ('added_at',)
    autocomplete_fields = ('attendee',)


@admin.register(FamilyGroup)
class FamilyGroupAdmin(admin.ModelAdmin):
    list_display = ('family_name', 'created_by', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('family_name',)
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('created_by',)
    inlines = [FamilyAttendeeInline]
    
    fieldsets = (
        ('Family Information', {
            'fields': ('family_name', 'created_by')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(FamilyAttendee)
class FamilyAttendeeAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'family_group', 'relationship', 'is_primary_guardian', 'added_at')
    list_filter = ('relationship', 'is_primary_guardian', 'added_at')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'family_group__family_name')
    readonly_fields = ('added_at',)
    autocomplete_fields = ('family_group', 'attendee')
    
    fieldsets = (
        ('Family Assignment', {
            'fields': ('family_group', 'attendee', 'relationship', 'is_primary_guardian')
        }),
        ('Metadata', {
            'fields': ('added_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'event', 'version', 'required', 'active', 'created_at')
    list_filter = ('required', 'active', 'created_at', 'event')
    search_fields = ('code', 'title', 'description')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('event',)
    
    fieldsets = (
        ('Consent Information', {
            'fields': ('code', 'title', 'description', 'external_link', 'version')
        }),
        ('Configuration', {
            'fields': ('event', 'required', 'active')
        }),
        ('Metadata', {
            'fields': ('defined_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AttendeeConsent)
class AttendeeConsentAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'consent', 'consent_given', 'given_at', 'given_by', 'recorded_at')
    list_filter = ('consent_given', 'given_at', 'recorded_at')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'consent__title', 'consent__code')
    readonly_fields = ('recorded_at', 'given_at')
    autocomplete_fields = ('attendee', 'consent')
    
    fieldsets = (
        ('Consent Record', {
            'fields': ('attendee', 'consent', 'consent_given')
        }),
        ('Given Information', {
            'fields': ('given_at', 'given_by')
        }),
        ('Recorded Information', {
            'fields': ('recorded_at', 'recorded_by'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_consent_given']
    
    def mark_consent_given(self, request, queryset):
        from django.utils import timezone
        queryset.update(consent_given=True, given_at=timezone.now(), given_by=request.user)
    mark_consent_given.short_description = "Mark consent as given"


@admin.register(AttendeeMessage)
class AttendeeMessageAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'subject', 'priority', 'submitted_at', 'responsed_at', 'responsed_by')
    list_filter = ('priority', 'submitted_at', 'responsed_at')
    search_fields = ('subject', 'message', 'attendee__first_name', 'attendee__last_name', 'attendee__attendee_display_id')
    readonly_fields = ('submitted_at', 'sent_at')
    autocomplete_fields = ('attendee', 'responsed_by')
    date_hierarchy = 'submitted_at'
    
    fieldsets = (
        ('Message Information', {
            'fields': ('attendee', 'subject', 'message', 'priority')
        }),
        ('Response', {
            'fields': ('response', 'responsed_at', 'responsed_by')
        }),
        ('Admin Notes', {
            'fields': ('admin_notes',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('submitted_at', 'sent_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_responded']
    
    def mark_as_responded(self, request, queryset):
        from django.utils import timezone
        queryset.update(responsed_at=timezone.now(), responsed_by=request.user)
    mark_as_responded.short_description = "Mark as responded"


@admin.register(EventAttendance)
class EventAttendanceAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'event', 'is_checked_in', 'check_in_time', 'check_out_time', 'check_in_by')
    list_filter = ('event', 'check_in_time', 'check_out_time')
    search_fields = ('attendee__first_name', 'attendee__last_name', 'attendee__attendee_display_id', 'event__title')
    readonly_fields = ('check_in_time', 'check_out_time')
    autocomplete_fields = ('event', 'attendee', 'check_in_by', 'check_out_by')
    date_hierarchy = 'check_in_time'
    
    fieldsets = (
        ('Attendance Information', {
            'fields': ('event', 'attendee')
        }),
        ('Check-in', {
            'fields': ('check_in_time', 'check_in_by')
        }),
        ('Check-out', {
            'fields': ('check_out_time', 'check_out_by')
        }),
    )
    
    actions = ['mark_checked_in', 'mark_checked_out']
    
    def mark_checked_in(self, request, queryset):
        from django.utils import timezone
        queryset.update(check_in_time=timezone.now(), check_in_by=request.user)
    mark_checked_in.short_description = "Mark as checked in"
    
    def mark_checked_out(self, request, queryset):
        from django.utils import timezone
        queryset.update(check_out_time=timezone.now(), check_out_by=request.user)
    mark_checked_out.short_description = "Mark as checked out"

@admin.register(AttendeeOrganisation)
class AttendeeOrganisationAdmin(admin.ModelAdmin):
    list_display = ('attendee', 'organisation', 'added_at', 'added_by')
    list_filter = ('added_at',)
    search_fields = ('attendee__first_name', 'attendee__last_name', 'attendee__attendee_display_id', 'organisation__title')
    readonly_fields = ('added_at',)
    autocomplete_fields = ('attendee', 'organisation', 'added_by')
    
    fieldsets = (
        ('Organisation Information', {
            'fields': ('attendee', 'organisation')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at'),
            'classes': ('collapse',)
        }),
    )