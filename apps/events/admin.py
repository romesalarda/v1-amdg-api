from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Event, EventType, EventAuthorization, EventPermission, 
    EventPermissionAssignment, EventReview, EventRole, 
    EventRoleAssignment, EventStaff, EventStaffAvailability, EventStaffInvite,
    EventQuestion, EventQuestionOption, EventQuestionAnswer, EventQuestionAnswerChoice,
    EventSettings, EventVenue, EventVenueRoom, EventVenueContact, EventVenueMetadata,
    EventNotification, EventTransportOption, EventTransportSchedule, EventTransportStop
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

@admin.register(EventNotification)
class EventNotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'event', 'notification_type', 'priority',
        'is_read', 'created_by', 'created_at', 'read_at',
    )
    list_filter = ('notification_type', 'priority', 'is_read', 'created_at')
    search_fields = ('event__title', 'event__display_code')
    readonly_fields = ('created_at', 'read_at', 'created_by')
    list_select_related = ('event', 'created_by', 'related_payment', 'related_order', 'related_booking')
    date_hierarchy = 'created_at'
    actions = ['mark_as_read', 'mark_as_unread']

    fieldsets = (
        ('Notification', {
            'fields': ('event', 'notification_type', 'priority', 'metadata'),
        }),
        ('Related Objects', {
            'fields': ('related_payment', 'related_order', 'related_booking'),
        }),
        ('State', {
            'fields': ('is_read', 'read_at'),
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.action(description='Mark selected notifications as read')
    def mark_as_read(self, request, queryset):
        from django.utils import timezone
        count = queryset.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        self.message_user(request, f'{count} notification(s) marked as read.')

    @admin.action(description='Mark selected notifications as unread')
    def mark_as_unread(self, request, queryset):
        count = queryset.filter(is_read=True).update(is_read=False, read_at=None)
        self.message_user(request, f'{count} notification(s) marked as unread.')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'display_code', 'status', 'event_type', 'organisation', 'start_datetime', 'end_datetime', 'created_by')
    list_filter = ('status', 'event_type', 'organisation', 'created_at', 'start_datetime')
    search_fields = ('title', 'display_code', 'display_identifier', 'short_description', 'organisation__title')
    readonly_fields = ('event_id', 'created_at', 'updated_at', 'url_safe_title', 'deleted_at', 'deleted_by')
    date_hierarchy = 'start_datetime'
    autocomplete_fields = ('organisation', 'created_by')
    list_select_related = ('event_type', 'organisation', 'created_by')
    
    fieldsets = (
        ('Identifiers', {
            'fields': ('event_id', 'display_code', 'display_identifier')
        }),
        ('Basic Information', {
            'fields': ('title', 'url_safe_title', 'event_type', 'status', 'timezone', 'organisation')
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
    list_display = ('event', 'user', 'permission', 'read_only', 'allow_update', 'allow_delete', 'allow_create', 'assigned_by', 'assigned_at')
    list_filter = ('assigned_at', 'permission__category', 'read_only', 'allow_update', 'allow_delete', 'allow_create')
    search_fields = ('event__title', 'user__email', 'permission__name')
    readonly_fields = ('assigned_at',)
    autocomplete_fields = ('event', 'user', 'permission')
    
    fieldsets = (
        ('Assignment', {
            'fields': ('event', 'user', 'permission', 'assigned_by')
        }),
        ('CRUD Permissions', {
            'fields': ('read_only', 'allow_update', 'allow_delete', 'allow_create'),
            'description': 'If read_only is True, other permissions are ignored and user can only READ. Otherwise, specific CRUD flags control access.'
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


class EventQuestionOptionInline(admin.TabularInline):
    model = EventQuestionOption
    extra = 1
    readonly_fields = ('created_at', 'updated_at')
    fields = ('option_text', 'order', 'created_at')
    ordering = ('order',)


class EventQuestionAnswerInline(admin.TabularInline):
    model = EventQuestionAnswer
    extra = 0
    readonly_fields = ('submitted_at', 'updated_at')
    fields = ('attendee', 'answer_text', 'submitted_at')
    autocomplete_fields = ('attendee',)


@admin.register(EventQuestion)
class EventQuestionAdmin(admin.ModelAdmin):
    list_display = ('question_title', 'event', 'question_type', 'required', 'public', 'order', 'created_at')
    list_filter = ('question_type', 'required', 'public', 'event', 'created_at')
    search_fields = ('question_title', 'question_body', 'event__title')
    readonly_fields = ('id', 'created_at', 'updated_at')
    autocomplete_fields = ('event',)
    list_editable = ('order',)
    ordering = ('event', 'order')
    inlines = [EventQuestionOptionInline, EventQuestionAnswerInline]
    
    fieldsets = (
        ('Question Information', {
            'fields': ('id', 'event', 'question_title', 'question_body', 'question_type')
        }),
        ('Configuration', {
            'fields': ('required', 'public', 'order')
        }),
        ('Value Constraints', {
            'fields': ('min_value', 'max_value'),
            'classes': ('collapse',),
            'description': 'Only applicable for slider questions'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventQuestionOption)
class EventQuestionOptionAdmin(admin.ModelAdmin):
    list_display = ('option_text', 'question', 'order', 'created_at')
    list_filter = ('question__event', 'created_at')
    search_fields = ('option_text', 'question__question_title')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('question',)
    list_editable = ('order',)
    ordering = ('question', 'order')
    
    fieldsets = (
        ('Option Information', {
            'fields': ('question', 'option_text', 'order')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class EventQuestionAnswerChoiceInline(admin.TabularInline):
    model = EventQuestionAnswerChoice
    extra = 0
    readonly_fields = ('selected_at',)
    autocomplete_fields = ('option',)


@admin.register(EventQuestionAnswer)
class EventQuestionAnswerAdmin(admin.ModelAdmin):
    list_display = ('question', 'attendee', 'get_answer_preview', 'submitted_at')
    list_filter = ('question__event', 'question__question_type', 'submitted_at')
    search_fields = ('question__question_title', 'attendee__first_name', 'attendee__last_name', 'answer_text')
    readonly_fields = ('submitted_at', 'updated_at')
    autocomplete_fields = ('question', 'attendee')
    date_hierarchy = 'submitted_at'
    inlines = [EventQuestionAnswerChoiceInline]
    
    fieldsets = (
        ('Answer Information', {
            'fields': ('question', 'attendee', 'answer_text')
        }),
        ('Metadata', {
            'fields': ('submitted_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_answer_preview(self, obj):
        if len(obj.answer_text) > 50:
            return obj.answer_text[:50] + '...'
        return obj.answer_text
    get_answer_preview.short_description = 'Answer Preview'


@admin.register(EventQuestionAnswerChoice)
class EventQuestionAnswerChoiceAdmin(admin.ModelAdmin):
    list_display = ('answer', 'option', 'get_question', 'get_attendee', 'selected_at')
    list_filter = ('selected_at',)
    search_fields = ('answer__attendee__first_name', 'answer__attendee__last_name', 'option__option_text')
    readonly_fields = ('selected_at',)
    autocomplete_fields = ('answer', 'option')
    
    fieldsets = (
        ('Choice Information', {
            'fields': ('answer', 'option')
        }),
        ('Metadata', {
            'fields': ('selected_at',),
            'classes': ('collapse',)
        }),
    )
    
    def get_question(self, obj):
        return obj.option.question.question_title
    get_question.short_description = 'Question'
    
    def get_attendee(self, obj):
        return obj.answer.attendee
    get_attendee.short_description = 'Attendee'


@admin.register(EventSettings)
class EventSettingsAdmin(admin.ModelAdmin):
    list_display = ('event', 'payment_enabled', 'product_selling_enabled', 'donation_enabled', 
                    'refunds_enabled', 'participants_registration_require_verification')
    list_filter = ('payment_enabled', 'product_selling_enabled', 'donation_enabled', 
                   'refunds_enabled', 'participants_registration_require_verification',
                   'product_publication_requires_verification', 'accepting_sponsorships_enabled')
    search_fields = ('event__title', 'event__display_code', 'event__display_identifier')
    readonly_fields = ('get_event_details',)
    autocomplete_fields = ('event',)
    
    fieldsets = (
        ('Event', {
            'fields': ('event', 'get_event_details', 'default_timezone')
        }),
        ('Payment Settings', {
            'fields': ('payment_enabled', 'refunds_enabled'),
            'description': 'Payment must be enabled for products, donations, and refunds to work.'
        }),
        ('Product Settings', {
            'fields': ('product_selling_enabled', 'product_publication_requires_verification')
        }),
        ('Donation & Sponsorship Settings', {
            'fields': ('donation_enabled', 'accepting_sponsorships_enabled')
        }),
        ('Registration Settings', {
            'fields': ('participants_registration_require_verification',)
        }),
    )
    
    def get_event_details(self, obj):
        if obj.event:
            return format_html(
                '<strong>Title:</strong> {}<br>'
                '<strong>Code:</strong> {}<br>'
                '<strong>Status:</strong> {}<br>'
                '<strong>Start:</strong> {}<br>'
                '<strong>End:</strong> {}',
                obj.event.title,
                obj.event.display_code,
                obj.event.get_status_display(),
                obj.event.start_datetime.strftime('%Y-%m-%d %H:%M'),
                obj.event.end_datetime.strftime('%Y-%m-%d %H:%M')
            )
        return '-'
    get_event_details.short_description = 'Event Details'
    
    def has_delete_permission(self, request, obj=None):
        # EventSettings should not be deleted independently from Event
        return False


@admin.register(EventStaffInvite)
class EventStaffInviteAdmin(admin.ModelAdmin):
    list_display = ('id', 'event', 'target_user', 'invited_by', 'accepted', 'is_active', 'is_valid_status', 'added_at', 'expires_at')
    list_filter = ('accepted', 'is_active', 'added_at', 'expires_at', 'event__status')
    search_fields = ('event__title', 'target_user__email', 'target_user__first_name', 'target_user__last_name', 'invited_by__email')
    readonly_fields = ('id', 'added_at', 'accepted_at', 'is_valid_status')
    autocomplete_fields = ('event', 'target_user', 'invited_by')
    date_hierarchy = 'added_at'
    list_select_related = ('event', 'target_user', 'invited_by')
    
    fieldsets = (
        ('Invite Information', {
            'fields': ('id', 'event', 'target_user', 'invited_by')
        }),
        ('Status', {
            'fields': ('accepted', 'accepted_at', 'is_active', 'is_valid_status')
        }),
        ('Timing', {
            'fields': ('added_at', 'expires_at')
        }),
    )
    
    actions = ['accept_invites', 'deactivate_invites']
    
    def is_valid_status(self, obj):
        return obj.is_valid
    is_valid_status.short_description = 'Valid'
    is_valid_status.boolean = True
    
    def accept_invites(self, request, queryset):
        """Accept selected invites"""
        count = 0
        for invite in queryset:
            if invite.is_valid:
                try:
                    invite.accept_invite()
                    count += 1
                except Exception:
                    pass
        self.message_user(request, f'{count} invite(s) accepted successfully.')
    accept_invites.short_description = "Accept selected invites"
    
    def deactivate_invites(self, request, queryset):
        """Deactivate selected invites"""
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count} invite(s) deactivated.')
    deactivate_invites.short_description = "Deactivate selected invites"


@admin.register(EventVenue)
class EventVenueAdmin(admin.ModelAdmin):
    list_display = ('event_venue_id', 'event', 'name', 'city', 'source_venue_id')
    list_filter = ('event__event_type', 'event__status', 'poi_type')
    search_fields = ('event__title', 'name', 'city', 'address', 'event__display_code')
    readonly_fields = ('event_venue_id', 'added_at', 'updated_at')
    autocomplete_fields = ('event',)
    list_select_related = ('event',)

    fieldsets = (
        ('Association', {
            'fields': ('event_venue_id', 'event', 'source_venue_id', 'is_primary'),
        }),
        ('Location', {
            'fields': ('name', 'address', 'postcode', 'city', 'poi_type', 'latitude', 'longitude'),
        }),
        ('Venue Details', {
            'fields': ('description', 'instructions', 'notes', 'capacity'),
        }),
        ('Timestamps', {
            'fields': ('added_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


class EventVenueRoomInline(admin.TabularInline):
    model = EventVenueRoom
    extra = 0
    readonly_fields = ('added_at', 'updated_at')
    fields = ('room_name', 'description', 'capacity', 'added_at')


class EventVenueContactInline(admin.TabularInline):
    model = EventVenueContact
    extra = 0
    readonly_fields = ('added_at', 'updated_at')
    fields = ('contact_name', 'phone_number', 'email', 'role', 'added_at')


class EventVenueMetadataInline(admin.TabularInline):
    model = EventVenueMetadata
    extra = 0
    readonly_fields = ('added_at', 'updated_at')
    fields = ('label', 'value', 'added_at')


@admin.register(EventVenueRoom)
class EventVenueRoomAdmin(admin.ModelAdmin):
    list_display = ('room_name', 'event_venue', 'capacity', 'added_at')
    search_fields = ('room_name', 'event_venue__name')
    readonly_fields = ('added_at', 'updated_at')


@admin.register(EventVenueContact)
class EventVenueContactAdmin(admin.ModelAdmin):
    list_display = ('contact_name', 'event_venue', 'role', 'phone_number', 'email')
    search_fields = ('contact_name', 'event_venue__name')
    readonly_fields = ('added_at', 'updated_at')


@admin.register(EventVenueMetadata)
class EventVenueMetadataAdmin(admin.ModelAdmin):
    list_display = ('label', 'event_venue', 'value')
    search_fields = ('label', 'event_venue__name')
    readonly_fields = ('added_at', 'updated_at')

    
@admin.register(EventTransportOption)
class EventTransportOptionAdmin(admin.ModelAdmin):
    list_display = ('transport_type', 'event', 'is_provided_by_event', 'contact_info', 'created_at', 'base_amount',)
    list_filter = ('transport_type', 'is_provided_by_event', 'created_at'),
    search_fields = ('event__title', 'description', 'contact_info')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('event',)
    
    fieldsets = (
        ('Transport Information', {
            'fields': ('transport_type', 'event', 'description', 'is_provided_by_event', 'contact_info')
        }),
        ('Payment Information', {
            'fields': ('base_amount','percentage_modifier', 'original_amount'),
            'description': 'Any discounts associated with this transport option will be applied to the total price of the event booking when this transport option is selected.'
        }),

        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)    
        }),
    )

@admin.register(EventTransportSchedule)
class EventTransportScheduleAdmin(admin.ModelAdmin):
    list_display = ('transport_option', 'start_datetime', 'end_datetime', 'frequency_minutes')
    list_filter = ('transport_option__transport_type', 'start_datetime')
    search_fields = ('transport_option__event__title', 'transport_option__description')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('transport_option',)
    
    fieldsets = (
        ('Schedule Information', {
            'fields': ('transport_option', 'start_datetime', 'end_datetime', 'frequency_minutes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(EventTransportStop)
class EventTransportStopAdmin(admin.ModelAdmin):
    list_display = ('transport_option', 'stop_name', 'arrival_datetime', 'departure_datetime')
    list_filter = ('transport_option__transport_type', 'arrival_datetime')
    search_fields = ('transport_option__event__title', 'stop_name')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('transport_option',)
    
    fieldsets = (
        ('Stop Information', {
            'fields': ('transport_option', 'stop_name', 'arrival_datetime', 'departure_datetime')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
