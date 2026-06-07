from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from apps.events.models import (
    Event, EventType, EventSettings, EventStatusChoices,
    EventAuthorization, EventAuthorizationStatusChoices,
    EventPermission, EventPermissionAssignment, EventPermissionCategoryChoices,
    EventRole, EventRoleAssignment, EventRoleCategoryChoices,
    EventStaff, EventStaffAvailability, EventStaffInvite,
    EventReview,
    EventQuestion, EventQuestionTypeChoices, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice,
    EventVenue, EventVenueRoom, EventVenueContact, EventVenueMetadata,
    EventNotification, NotificationTypeChoices, NotificationPriorityChoices,
)
from apps.common.models import AvailabilityWindow, Resource
from apps.common.api.serializers import (
    AvailabilityWindowSerializer, 
    ResourceSerializer
)
from apps.bookings.api.serializers.serializers import BookingDetailSerializer
from core.utils.currency import format_price

from urllib.parse import urlparse
import posixpath
import pytz
import uuid
User = get_user_model()


def get_event_by_identifier(identifier):
    """Resolve event by UUID event_id or URL-safe title."""
    if not identifier:
        raise Event.DoesNotExist

    try:
        uuid.UUID(str(identifier))
        return Event.objects.get(event_id=identifier)
    except (ValueError, TypeError, Event.DoesNotExist):
        return Event.objects.get(url_safe_title=identifier)


class EventTypeSerializer(serializers.ModelSerializer):
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventType
        fields = ('id', 'title', 'code', 'description', 'created_at', 'created_by', 'updated_at', '_links')
        read_only_fields = ('id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event type'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event type'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/types/{obj.id}/"
            )
        }
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )
        
        return links


class EventSettingsSerializer(serializers.ModelSerializer):
    default_timezone = serializers.ChoiceField(
        choices=[(tz, tz) for tz in pytz.all_timezones],
        help_text="Default timezone for event"
    )
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventSettings
        fields = (
            'id', 'event', 'payment_enabled', 'product_publication_requires_verification',
            'product_selling_enabled', 'donation_enabled', 'refunds_enabled',
            'accepting_sponsorships_enabled', 'participants_registration_require_verification',
            'requires_verified_sponsors_for_checkout', 'requires_invite_acceptance_for_checkout',
            'sponsor_checkout_policy_notes', 'max_attendees_per_booking', 'max_attendees_per_user',
    
            'default_timezone', '_links'
        )
        read_only_fields = ('id',)
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to these event settings'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/settings/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        return links


class EventListSerializer(serializers.ModelSerializer):
    event_type_name = serializers.CharField(source='event_type.title', read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    landing_images = ResourceSerializer(many=True, read_only=True)
    main_landing_image = ResourceSerializer(read_only=True)
    attendee_overview = serializers.SerializerMethodField(read_only=True)
    location = serializers.CharField(source='location.area_name', read_only=True)
    # TODO: field that shows if a user can register - check available windows and registration settings, show details with how many days until registration opens/closes if applicable

    timezone = serializers.CharField()
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = (
            'id','event_id', 'display_code', 'display_identifier', 'title', 'url_safe_title', 
            'landing_images', 'main_landing_image',
            'status', 'status_display', 'event_type', 'event_type_name', 'organisation', 
            'organisation_name', 'short_description', 'start_datetime', 'end_datetime', 'attendee_overview', 'location',
            'external_link', 'external_event', 'last_opened', 'last_closed',
            'timezone', 'created_at', 'created_by', '_links'
        )
        read_only_fields = ('event_id', 'url_safe_title', 'created_at')

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'total_attendees': {'type': 'integer', 'description': 'Total number of attendees'},
            'confirmed_attendees': {'type': 'integer', 'description': 'Number of confirmed attendees'},
            'pending_attendees': {'type': 'integer', 'description': 'Number of pending attendees'},
            'cancelled_attendees': {'type': 'integer', 'description': 'Number of cancelled attendees'},
            'max_attendance': {'type': 'integer', 'description': 'Maximum attendance for the event'},
            'percentage_full': {'type': 'number', 'format': 'float', 'description': 'Percentage of confirmed attendees relative to maximum attendance'}
        },
        'required': ['total_attendees', 'confirmed_attendees', 'pending_attendees', 'cancelled_attendees', 'max_attendance']
    })
    def get_attendee_overview(self, obj):
        """Return a summary of attendee counts by status for this event."""
        from apps.attendee.models import AttendeeStatus
        attendees = obj.attendees.all() 
        overview = {
            'total_attendees': attendees.count(),
            'confirmed_attendees': attendees.filter(status=AttendeeStatus.REGISTERED).count(),
            'pending_attendees': attendees.filter(status=AttendeeStatus.PENDING_PAYMENT).count(),
            'cancelled_attendees': attendees.filter(status=AttendeeStatus.CANCELLED).count(),
            'max_attendance': obj.maximum_attendance,
            'percentage_full': (attendees.filter(status=AttendeeStatus.REGISTERED).count() / obj.maximum_attendance * 100) if obj.maximum_attendance else None
        }
        return overview

    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event'},
            'event_type': {'type': 'string', 'format': 'uri', 'description': 'Link to the event type'},
            'organisation': {'type': 'string', 'format': 'uri', 'description': 'Link to the organisation'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event'},
            'settings': {'type': 'string', 'format': 'uri', 'description': 'Link to event settings'}
        },
        'required': ['self', 'settings']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{obj.url_safe_title}/"
            )
        }
        
        if obj.event_type:
            links['event_type'] = request.build_absolute_uri(
                f"/api/event/types/{obj.event_type.id}/"
            )
        
        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/{obj.organisation.id}/"
            )
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )
        
        links['settings'] = request.build_absolute_uri(
            f"/api/event/list/{obj.event_id}/settings/"
        )
        
        return links


class SponsorableEventListSerializer(EventListSerializer):
    """List serializer for organisation-facing sponsorable event discovery."""

    accepting_sponsorships_enabled = serializers.BooleanField(
        source='settings.accepting_sponsorships_enabled',
        read_only=True,
    )
    requires_invite_acceptance_for_checkout = serializers.BooleanField(
        source='settings.requires_invite_acceptance_for_checkout',
        read_only=True,
    )
    requires_verified_sponsors_for_checkout = serializers.BooleanField(
        source='settings.requires_verified_sponsors_for_checkout',
        read_only=True,
    )
    sponsor_checkout_policy_notes = serializers.CharField(
        source='settings.sponsor_checkout_policy_notes',
        read_only=True,
        allow_null=True,
    )
    active_sponsorship_packages_count = serializers.IntegerField(read_only=True)
    can_checkout = serializers.SerializerMethodField()

    class Meta(EventListSerializer.Meta):
        fields = EventListSerializer.Meta.fields + (
            'accepting_sponsorships_enabled',
            'requires_invite_acceptance_for_checkout',
            'requires_verified_sponsors_for_checkout',
            'sponsor_checkout_policy_notes',
            'active_sponsorship_packages_count',
            'can_checkout',
        )

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_checkout(self, obj):
        settings_obj = getattr(obj, 'settings', None)
        if not settings_obj:
            return False
        return bool(
            settings_obj.accepting_sponsorships_enabled
            and getattr(obj, 'active_sponsorship_packages_count', 0) > 0
        )


class EventOutstandingTaskSerializer(serializers.Serializer):
    title = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    hint = serializers.CharField(read_only=True)
    code = serializers.CharField(read_only=True)

class EventDetailSerializer(serializers.ModelSerializer):
    event_type_details = EventTypeSerializer(source='event_type', read_only=True)
    settings = EventSettingsSerializer(read_only=True)
    organisation_name = serializers.CharField(source='organisation.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    timezone = serializers.ChoiceField(choices=[(tz, tz) for tz in pytz.all_timezones], required=False)
    duration_days = serializers.IntegerField(read_only=True)
    is_ongoing = serializers.BooleanField(read_only=True)
    is_approved = serializers.BooleanField(read_only=True)
    can_participants_register = serializers.BooleanField(read_only=True)
    can_event_be_published = serializers.BooleanField(read_only=True)
    number_of_attendees = serializers.IntegerField(read_only=True)
    outstanding_tasks = serializers.SerializerMethodField(read_only=True)
    
    # New fields for availability, resources, and landing images
    availability_windows = AvailabilityWindowSerializer(many=True, read_only=True)
    # resources = ResourceSerializer(many=True, read_only=True)
    resources = serializers.SerializerMethodField(read_only=True)
    landing_images = ResourceSerializer(many=True, read_only=True)
    main_landing_image = ResourceSerializer(read_only=True)
    is_deleted = serializers.SerializerMethodField()
    general_price = serializers.SerializerMethodField(read_only=True)

    registration_open_date = serializers.SerializerMethodField(read_only=True)
    registration_close_date = serializers.SerializerMethodField(read_only=True)

    location = serializers.SlugRelatedField(slug_field='area_id', read_only=True)
    
    # User permissions context
    user_permissions = serializers.SerializerMethodField()
    user_registered_attendee_count = serializers.SerializerMethodField(read_only=True)
    user_remaining_registration_slots = serializers.SerializerMethodField(read_only=True)
    user_self_registered = serializers.SerializerMethodField(read_only=True)
    # TODO: return a field in which we can see the registration availability dates
    
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = (
            'id', 'event_id', 'display_code', 'display_identifier', 'title', 'url_safe_title',
            'status', 'status_display', 'event_type', 'event_type_details', 'timezone',
            'short_description', 'long_description', 'what_to_bring', 'important_information',
            'theme', 'anchor_verse', 'expected_attendance', 'maximum_attendance',
            'start_datetime', 'end_datetime', 'organisation', 'organisation_name',
            'created_by', 'created_by_email', 'created_at', 'updated_at', 'location',
            'settings', 'duration_days', 'is_ongoing', 'is_approved', 
            'can_participants_register', 'number_of_attendees',
            'availability_windows', 'resources', 'landing_images', 'main_landing_image',
            'deleted_at', 'deleted_by', 'is_deleted', 'user_permissions', 'general_price', 'outstanding_tasks',
            'can_event_be_published', 'registration_open_date', 'registration_close_date', 'uptime',
            'user_registered_attendee_count', 'user_remaining_registration_slots', 'user_self_registered',
            'external_link', 'external_event', 'last_opened', 'last_closed',
            '_links'
        )
        read_only_fields = (
            'event_id', 'display_identifier', 'url_safe_title', 'created_at', 
            'updated_at', 'duration_days', 'is_ongoing', 'is_approved', 
            'can_participants_register', 'number_of_attendees', 'deleted_at', 'deleted_by',
            'last_opened', 'last_closed', 'uptime',
        )
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
            'deleted_at': {'default': None},
            'start_datetime': {'default': None},
            'end_datetime': {'default': None},
            'timezone': {'source': '*'},  # Prevent auto-generation from TimeZoneField
        }


    @extend_schema_field(ResourceSerializer(many=True))
    def get_resources(self, obj):

        request = self.context.get("request")

        base_qs = obj.resources.exclude(tag__in=Resource.EXCLUDE_TAGS + ["LANDING_PHOTO_SECONDARY", "LANDING_PHOTO_MAIN"])

        if not obj.is_staff(request.user):
            base_qs = base_qs.filter(public=True)

        return ResourceSerializer(base_qs, many=True).data

    @extend_schema_field(EventOutstandingTaskSerializer(many=True))
    def get_outstanding_tasks(self, obj):
        return obj.outstanding_tasks
    
    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_registration_open_date(self, obj):
        return obj.registration_open_date
    
    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_registration_close_date(self, obj):
        return obj.registration_close_date

    @extend_schema_field(OpenApiTypes.STR)
    def get_general_price(self, obj):
        '''Returns price range from value_x - value_y if multiple packages, or single value if only one package.'''
        packages = obj.booking_packages.order_by('base_amount').values("base_amount", "base_amount_currency")
        if not packages.exists():
            return None
        elif packages.count() == 1:
            return format_price(packages.first()['base_amount'], packages.first()['base_amount_currency'])
        else:
            min_price = packages.first()
            max_price = packages.last()
            if min_price["base_amount"] == max_price["base_amount"]:
                return format_price(min_price["base_amount"], min_price["base_amount_currency"])
            else:
                return f"{format_price(min_price['base_amount'], min_price['base_amount_currency'])} - {format_price(max_price['base_amount'], max_price['base_amount_currency'])}"

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_deleted(self, obj):
        """Check if the event is soft-deleted."""
        return obj.deleted_at is not None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'is_creator': {
                'type': 'boolean',
                'description': 'Whether the current user is the event creator'
            },
            'is_staff_member': {
                'type': 'boolean',
                'description': 'Whether the current user is an event staff member'
            },
            'is_admin': {
                'type': 'boolean',
                'description': 'Whether the current user is a Django staff/superuser'
            },
            'can_manage_event': {
                'type': 'boolean',
                'description': 'Whether the user can edit event details (creator, staff, or admin)'
            },
            'can_manage_staff': {
                'type': 'boolean',
                'description': 'Whether the user can add/remove staff members'
            },
            'can_manage_invites': {
                'type': 'boolean',
                'description': 'Whether the user can create/manage staff invites'
            },
            'can_manage_resources': {
                'type': 'boolean',
                'description': 'Whether the user can add/remove resources'
            },
            'can_delete_event': {
                'type': 'boolean',
                'description': 'Whether the user can soft delete the event'
            },
            'assigned_permissions': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': 'List of permission codes explicitly assigned to the user for this event'
            },
            'assigned_roles': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': 'List of role names assigned to the user for this event'
            }
        },
        'required': [
            'is_creator', 'is_staff_member', 'is_admin', 'can_manage_event',
            'can_manage_staff', 'can_manage_invites', 'can_manage_resources',
            'can_delete_event', 'assigned_permissions', 'assigned_roles'
        ]
    })
    def get_user_permissions(self, obj):
        """
        Return comprehensive permission information for the current user.
        
        This includes:
        - User's relationship to the event (creator, staff, admin)
        - Computed permissions based on those relationships
        - Explicitly assigned permissions and roles with CRUD details
        """
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return {
                'is_creator': False,
                'is_staff_member': False,
                'is_admin': False,
                'can_manage_event': False,
                'can_manage_staff': False,
                'can_manage_invites': False,
                'can_manage_resources': False,
                'can_delete_event': False,
                'assigned_permissions': [],
                'assigned_roles': []
            }
        
        user = request.user
        
        # Check basic relationships
        is_creator = user == obj.created_by
        is_admin = user.is_staff or user.is_superuser
        is_staff_member = obj.staff_members.filter(user=user).exists() if not is_creator else True
        
        # Compute derived permissions
        can_manage = is_creator or is_staff_member or is_admin
        
        # Get explicitly assigned permissions with CRUD details
        permission_assignments = EventPermissionAssignment.objects.filter(
            event=obj,
            user=user
        ).select_related('permission')
        
        assigned_permissions = []
        for assignment in permission_assignments:
            # Determine effective permissions based on read_only flag
            if assignment.read_only:
                # read_only takes precedence - only read access
                effective_access = {
                    'can_read': True,
                    'can_create': False,
                    'can_update': False,
                    'can_delete': False
                }
            else:
                # Use individual CRUD flags
                effective_access = {
                    'can_read': assignment.allow_update or assignment.allow_delete or assignment.allow_create,  # Implicit read if any write
                    'can_create': assignment.allow_create,
                    'can_update': assignment.allow_update,
                    'can_delete': assignment.allow_delete
                }
            
            assigned_permissions.append({
                'permission_code': assignment.permission.code,
                'permission_name': assignment.permission.name,
                'permission_category': assignment.permission.category,
                'read_only': assignment.read_only,
                'allow_update': assignment.allow_update,
                'allow_delete': assignment.allow_delete,
                'allow_create': assignment.allow_create,
                'effective_access': effective_access,
                'has_full_access': assignment.has_full_access
            })
        
        # Get assigned roles
        assigned_roles = list(
            EventRoleAssignment.objects.filter(
                event=obj,
                user=user
            ).values_list('role__name', flat=True)
        )
        
        return {
            'is_creator': is_creator,
            'is_staff_member': is_staff_member,
            'is_admin': is_admin,
            'can_manage_event': can_manage,
            'can_manage_staff': can_manage,
            'can_manage_invites': can_manage,
            'can_manage_resources': can_manage,
            'can_delete_event': can_manage,
            'assigned_permissions': assigned_permissions,
            'assigned_roles': assigned_roles
        }

    @extend_schema_field(OpenApiTypes.INT)
    def get_user_registered_attendee_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None

        from apps.attendee.models import AttendeeStatus
        return obj.attendees.filter(
            booking__made_by=request.user,
            status__in=[AttendeeStatus.REGISTERED, AttendeeStatus.CHECKED_IN], # TODO: remove this
            deleted_at__isnull=True,
        ).count()
    

    @extend_schema_field(OpenApiTypes.INT)
    def get_user_remaining_registration_slots(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None

        settings_obj = getattr(obj, 'settings', None)
        if not settings_obj:
            return None

        max_per_user = settings_obj.max_attendees_per_user
        if max_per_user is None:
            return None

        current_count = self.get_user_registered_attendee_count(obj) or 0
        return max(0, max_per_user - current_count)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_user_self_registered(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False

        from apps.attendee.models import AttendeeRelationship, AttendeeStatus

        return obj.attendees.filter(
            user=request.user,
            relationship_to_user=AttendeeRelationship.SELF,
            status__in=[
                AttendeeStatus.PENDING_PAYMENT,
                AttendeeStatus.REGISTERED,
                AttendeeStatus.CHECKED_IN,
                AttendeeStatus.WHITELISTED,
            ],
            deleted_at__isnull=True,
        ).exists()
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event'},
            'settings': {'type': 'string', 'format': 'uri', 'description': 'Link to event settings'},
            'staff': {'type': 'string', 'format': 'uri', 'description': 'Link to event staff list'},
            'availability_windows': {'type': 'string', 'format': 'uri', 'description': 'Link to manage availability windows'},
            'resources': {'type': 'string', 'format': 'uri', 'description': 'Link to manage resources'},
            'event_type': {'type': 'string', 'format': 'uri', 'description': 'Link to the event type'},
            'organisation': {'type': 'string', 'format': 'uri', 'description': 'Link to the organisation'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event'}
        },
        'required': ['self', 'settings', 'staff']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/"
            ),
            'settings': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/settings/"
            ),
            'staff': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/staff-list/"
            ),
            'availability_windows': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/availability-windows/"
            ),
            'resources': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/resources/"
            )
        }
        
        if obj.event_type:
            links['event_type'] = request.build_absolute_uri(
                f"/api/event/types/{obj.event_type.id}/"
            )
        
        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/{obj.organisation.id}/"
            )
        
        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )
        
        return links


class EventMyBookingEventSerializer(serializers.ModelSerializer):

    timezone = serializers.CharField()

    class Meta:
        model = Event
        fields = (
            'event_id',
            'display_identifier',
            'title',
            'status',
            'start_datetime',
            'end_datetime',
            'timezone',
        )
        read_only_fields = fields
        extra_kwargs = {
            'timezone': {'source': '*'},  # Prevent auto-generation from TimeZoneField
        }


class EventMyBookingBookingSerializer(serializers.Serializer):
    booking = BookingDetailSerializer(read_only=True)
    is_booking_owner = serializers.BooleanField(read_only=True)
    selection_reason = serializers.ChoiceField(
        choices=['made_by', 'attendee_linked'],
        read_only=True,
    )
    can_manage_all_attendees = serializers.BooleanField(read_only=True)


class EventMyBookingResponseSerializer(serializers.Serializer):
    event = EventMyBookingEventSerializer(read_only=True)
    primary_booking_reference = serializers.CharField(read_only=True)
    bookings = EventMyBookingBookingSerializer(many=True, read_only=True)


class EventMyOutstandingPaymentSerializer(serializers.Serializer):
    """
    Serializer for outstanding payments with associated booking details.

    Represents a payment that is pending/unpaid with full booking information,
    including attendees and tickets.
    """
    # Payment fields
    payment_reference = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    amount = serializers.SerializerMethodField()
    currency = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text='When the payment was created'
    )
    payment_method = serializers.SerializerMethodField(
        help_text='Payment method type (e.g., stripe, bank, cash, free)'
    )
    payment_method_title = serializers.SerializerMethodField(
        help_text='Configured payment method title'
    )
    payment_instructions = serializers.SerializerMethodField(
        help_text='Human-readable payment instructions for the attendee'
    )
    payment_method_details = serializers.SerializerMethodField(
        help_text='Method-specific details payload (e.g., bank transfer details)'
    )

    # Booking fields (from associated booking or intent)
    booking = EventMyBookingBookingSerializer(read_only=True)
    has_booking = serializers.SerializerMethodField(
        help_text='Whether this payment is already linked to a booking'
    )
    checkout_intent_id = serializers.SerializerMethodField(
        help_text='Checkout intent ID if payment is pending checkout completion'
    )
    metadata_attendees = serializers.SerializerMethodField(
        help_text='Attendee preview extracted from checkout metadata when no booking exists'
    )

    def get_amount(self, obj):
        """Format amount as string with currency (e.g., '100.00 GBP')."""
        if hasattr(obj, 'base_amount') and obj.base_amount:
            amount_value = obj.base_amount.amount
            currency = obj.base_amount.currency if hasattr(obj.base_amount, 'currency') else 'GBP'
            return f"{amount_value} {currency}"
        return None

    def get_payment_method(self, obj):
        """Get the payment method type."""
        if obj.method:
            if hasattr(obj.method, 'method_type'):
                return obj.method.method_type
            return str(obj.method)
        return None

    def get_payment_method_title(self, obj):
        """Get payment method title if configured."""
        if obj.method and getattr(obj.method, 'title', None):
            return obj.method.title
        return None

    def get_payment_method_details(self, obj):
        """Expose method-provided details to frontend for actionable payment guidance."""
        details = {}
        if obj.method and isinstance(getattr(obj.method, 'provided_details', None), dict):
            details.update(obj.method.provided_details)

        if obj.bank_transfer_reference:
            details['bank_transfer_reference'] = obj.bank_transfer_reference

        return details or None

    def get_payment_instructions(self, obj):
        """Provide human-readable instructions based on payment method type."""
        method = getattr(obj, 'method', None)
        if not method:
            return 'Complete payment to finalize your booking.'

        method_type = getattr(method, 'method_type', None)

        if method_type == 'BANK_TRANSFER':
            reference = obj.bank_transfer_reference or 'N/A'
            return (
                f"Use bank transfer and include reference {reference}. "
                f"Your booking will finalize once payment is verified."
            )

        if method_type == 'STRIPE':
            return 'Complete card payment to finalize your booking immediately.'

        if method_type == 'CASH':
            return 'Follow event instructions for cash payment confirmation.'

        return 'Follow the selected payment method instructions to finalize your booking.'

    def get_has_booking(self, obj):
        """Check if this payment is linked to a booking."""
        return obj.target_id is not None and obj.target_type and obj.target_type.model == 'booking'

    def get_checkout_intent_id(self, obj):
        """Get the checkout intent ID from metadata if present."""
        if obj.metadata and isinstance(obj.metadata, dict):
            return obj.metadata.get('checkout_intent_id')
        return None

    def get_metadata_attendees(self, obj):
        """Return attendee names from payment metadata for intent-based checkouts."""
        if not obj.metadata or not isinstance(obj.metadata, dict):
            return []

        attendees = obj.metadata.get('attendees')
        checkout_attendees = obj.metadata.get('checkout_attendees')

        names = []

        if isinstance(attendees, list):
            for attendee in attendees:
                if not isinstance(attendee, dict):
                    continue
                first_name = (attendee.get('first_name') or '').strip()
                last_name = (attendee.get('last_name') or '').strip()
                full_name = f"{first_name} {last_name}".strip()
                if full_name:
                    names.append(full_name)

        if isinstance(checkout_attendees, list):
            for checkout_attendee in checkout_attendees:
                if not isinstance(checkout_attendee, dict):
                    continue

                attendee_draft = checkout_attendee.get('attendee_draft')
                if not isinstance(attendee_draft, dict):
                    continue

                first_name = (attendee_draft.get('first_name') or '').strip()
                last_name = (attendee_draft.get('last_name') or '').strip()
                full_name = f"{first_name} {last_name}".strip()
                if full_name:
                    names.append(full_name)

        # De-duplicate while preserving order
        deduped = []
        for name in names:
            if name and name not in deduped:
                deduped.append(name)
        return deduped

    def to_representation(self, instance):
        """
        Customize representation to include booking data if available.
        """
        data = super().to_representation(instance)

        # If this payment is linked to a booking, serialize it
        if instance.target_id and instance.target_type and instance.target_type.model == 'booking':
            booking = instance.target
            if booking is not None:
                request = self.context.get('request')
                is_owner = bool(request and booking.made_by_id == request.user.id)
                booking_item = {
                    'booking': booking,
                    'is_booking_owner': is_owner,
                    'selection_reason': 'made_by' if is_owner else 'attendee_linked',
                    'can_manage_all_attendees': is_owner,
                }
                serializer = EventMyBookingBookingSerializer(booking_item)
                data['booking'] = serializer.data

        return data


class EventMyPaymentSummaryItemSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField(read_only=True)
    payment_reference = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    amount = serializers.CharField(read_only=True)
    amount_value = serializers.CharField(read_only=True, allow_null=True)
    original_amount = serializers.CharField(read_only=True, allow_null=True)
    total_refunded_amount = serializers.CharField(read_only=True, allow_null=True)
    currency = serializers.CharField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    method_type = serializers.CharField(read_only=True, allow_null=True)
    method_title = serializers.CharField(read_only=True, allow_null=True)
    provided_details = serializers.JSONField(read_only=True, allow_null=True)
    bank_reference = serializers.CharField(read_only=True, allow_null=True)
    source = serializers.ChoiceField(choices=['BOOKING', 'SHOP_ORDER'], read_only=True)
    is_outstanding = serializers.BooleanField(read_only=True)
    descriptor = serializers.CharField(read_only=True, allow_null=True)
    target_type = serializers.CharField(read_only=True, allow_null=True)
    target_id = serializers.CharField(read_only=True, allow_null=True)
    booking_id = serializers.UUIDField(read_only=True, allow_null=True)
    booking_reference = serializers.CharField(read_only=True, allow_null=True)

    order_id = serializers.UUIDField(read_only=True, allow_null=True)
    order_reference = serializers.CharField(read_only=True, allow_null=True)
    order_status = serializers.CharField(read_only=True, allow_null=True)

    attendee_id = serializers.UUIDField(read_only=True, allow_null=True)
    attendee_display_id = serializers.CharField(read_only=True, allow_null=True)
    attendee_name = serializers.CharField(read_only=True, allow_null=True)
    related_orders = serializers.JSONField(read_only=True, allow_null=True)
    summary_context = serializers.JSONField(read_only=True, allow_null=True)


class EventMyPaymentSummaryTotalsSerializer(serializers.Serializer):
    total_payments = serializers.IntegerField(read_only=True)
    outstanding_payments = serializers.IntegerField(read_only=True)
    booking_outstanding_payments = serializers.IntegerField(read_only=True)
    shop_outstanding_payments = serializers.IntegerField(read_only=True)
    booking_payments_count = serializers.IntegerField(read_only=True)
    shop_payments_count = serializers.IntegerField(read_only=True)
    attendee_payments_count = serializers.IntegerField(read_only=True)
    total_outstanding_amount = serializers.CharField(read_only=True)


class EventMyPaymentSummarySerializer(serializers.Serializer):
    booking_reference = serializers.CharField(read_only=True)
    attendee_filter = serializers.CharField(read_only=True, allow_null=True)
    totals = EventMyPaymentSummaryTotalsSerializer(read_only=True)
    booking_payments = EventMyPaymentSummaryItemSerializer(many=True, read_only=True)
    shop_payments = EventMyPaymentSummaryItemSerializer(many=True, read_only=True)
    attendee_payments = EventMyPaymentSummaryItemSerializer(many=True, read_only=True)
    outstanding_payments = EventMyPaymentSummaryItemSerializer(many=True, read_only=True)

class EventCreateUpdateSerializer(serializers.ModelSerializer):
    timezone = serializers.CharField()
    _links = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Event
        fields = (
            'event_id', 'display_code', 'title', 'status', 'event_type', 'timezone',
            'short_description', 'long_description', 'what_to_bring', 'important_information',
            'theme', 'anchor_verse', 'expected_attendance', 'maximum_attendance', 'url_safe_title',
            'external_link', 'external_event',
            'start_datetime', 'end_datetime', 'organisation', 'created_by', '_links'
        )
        read_only_fields = ('event_id', 'created_by', '_links')
        extra_kwargs = {
            'timezone': {'source': '*'},  # Prevent auto-generation from TimeZoneField
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event'},
            'organisation': {'type': 'string', 'format': 'uri', 'description': 'Link to the organisation'},
            'created_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who created this event'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request or not obj.pk:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{obj.event_id}/"
            )
        }
        if obj.organisation:
            links['organisation'] = request.build_absolute_uri(
                f"/api/organisations/{obj.organisation.id}/"
            )

        if obj.created_by:
            links['created_by'] = request.build_absolute_uri(
                f"/api/users/{obj.created_by.id}/"
            )

        return links
    
    def validate_title(self, value):
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError("Title must be at least 3 characters long")
        if len(value) > 255:
            raise serializers.ValidationError("Title must not exceed 255 characters")
        return value.strip()
    
    def validate_expected_attendance(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Expected attendance cannot be negative")
        return value
    
    def validate_maximum_attendance(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Maximum attendance cannot be negative")
        return value
    
    def validate(self, data):
        # Validate datetime ranges
        if 'start_datetime' in data and 'end_datetime' in data:
            if data['start_datetime'] >= data['end_datetime']:
                raise serializers.ValidationError({
                    "end_datetime": "End datetime must be after start datetime"
                })
        
        # Validate attendance limits
        expected = data.get('expected_attendance') or (self.instance.expected_attendance if self.instance else None)
        maximum = data.get('maximum_attendance') or (self.instance.maximum_attendance if self.instance else None)
        
        if expected and maximum and expected > maximum:
            raise serializers.ValidationError({
                "expected_attendance": "Expected attendance cannot exceed maximum attendance"
            })
        
        # Validate timezone
        timezone_str = data.get('timezone')
        if timezone_str:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(timezone_str)
            except Exception:
                raise serializers.ValidationError({
                    "timezone": f"Invalid timezone: {timezone_str}"
                })
        
        return data
    
    def create(self, validated_data):
        timezone_str = validated_data.pop('timezone', None)
        try:
            instance = Event.objects.create(**validated_data)
            if timezone_str:
                instance.timezone = timezone_str
                instance.save(update_fields=['timezone'])

            # add user as staff with full permissions

            EventStaff.objects.create(
                event=instance,
                user=self.context['request'].user,
                assigned_at=timezone.now(),
                assigned_by=self.context['request'].user,
            )

            # try:
            #     role = EventRole.objects.get(category=EventRoleCategoryChoices.ADMINISTRATIVE)
            #     EventRoleAssignment.objects.create(
            #         event=instance,
            #         user=self.context['request'].user,
            #         role=role,
            #         assigned_at=timezone.now(),
            #         assigned_by=self.context['request'].user,
            #     )

            # except EventRole.DoesNotExist:
            #     role = EventRole.objects.create(
            #         name=EventRoleCategoryChoices.ADMINISTRATIVE,
            #         code='ADMIN',
            #         category=EventRoleCategoryChoices.ADMINISTRATIVE,
            #         description='Administrative role with full access'
            #     )

            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error creating event: {str(e)}")
    
    def update(self, instance, validated_data):
        timezone_str = validated_data.pop('timezone', None)
        try:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            if timezone_str:
                instance.timezone = timezone_str
            instance.save()
            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error updating event: {str(e)}")


class EventAuthorizationSerializer(serializers.ModelSerializer):

    event = serializers.UUIDField(source='event.event_id')
    event_title = serializers.CharField(source='event.title', read_only=True)
    reviewed_by_email = serializers.EmailField(source='reviewed_by.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventAuthorization
        fields = (
            'id', 'review_id', 'review_code', 'event', 'event_title', 'reviewed_by',
            'reviewed_by_email', 'reviewed_at', 'status', 'status_display', 'reason', 'notes', '_links'
        )
        read_only_fields = ('id', 'review_id', 'review_code', 'reviewed_by', 'reviewed_at')
        extra_kwargs = {
            'reviewed_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this authorization'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'reviewed_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who reviewed'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/authorizations/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        if obj.reviewed_by:
            links['reviewed_by'] = request.build_absolute_uri(
                f"/api/users/{obj.reviewed_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        if self.instance is None:
            event = data.get('event')
            event = Event.objects.get(event_id=event["event_id"])  # Ensure event exists
            user = self.context['request'].user
            if EventAuthorization.objects.filter(event=event, reviewed_by=user).exists():
                raise serializers.ValidationError("You have already created an authorization for this event.")
            data['event'] = event
        return data


class EventPermissionSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventPermission
        fields = (
            'id', 'permission_id', 'name', 'code', 'description', 'category',
            'category_display', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'permission_id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this permission'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/event/permissions/{obj.id}/"
            )
        }


class EventPermissionAssignmentSerializer(serializers.ModelSerializer):
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    permission_name = serializers.CharField(source='permission.name', read_only=True)
    permission_code = serializers.CharField(source='permission.code', read_only=True)
    permission_category = serializers.CharField(source='permission.category', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    has_full_access = serializers.BooleanField(read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventPermissionAssignment
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'permission',
            'permission_name', 'permission_code', 'permission_category',
            'read_only', 'allow_update', 'allow_delete', 'allow_create', 'has_full_access',
            'assigned_at', 'assigned_by', 'assigned_by_email', '_links'
        )
        read_only_fields = ('id', 'assigned_at', 'assigned_by', 'has_full_access')
        extra_kwargs = {
            'assigned_at': {'default': None},
            'read_only': {'default': False},
            'allow_update': {'default': False},
            'allow_delete': {'default': False},
            'allow_create': {'default': False},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this permission assignment'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the user'},
            'permission': {'type': 'string', 'format': 'uri', 'description': 'Link to the permission'},
            'assigned_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who assigned'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/permission-assignments/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        if obj.permission:
            links['permission'] = request.build_absolute_uri(
                f"/api/event/permissions/{obj.permission.id}/"
            )
        
        if obj.assigned_by:
            links['assigned_by'] = request.build_absolute_uri(
                f"/api/users/{obj.assigned_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        # Check for duplicate permission assignment
        if self.instance is None:
            if EventPermissionAssignment.objects.filter(
                event=data.get('event'),
                user=data.get('user'),
                permission=data.get('permission')
            ).exists():
                raise serializers.ValidationError("This permission is already assigned to this user for this event.")
        
        # Validate CRUD flags logic: if read_only is True, warn about other flags
        if data.get('read_only', False):
            if data.get('allow_update') or data.get('allow_delete') or data.get('allow_create'):
                # We'll allow it but the read_only will take precedence
                pass
        else:
            # If not read_only and all other flags are False, user has no access
            if not any([data.get('allow_update'), data.get('allow_delete'), data.get('allow_create')]):
                # This is valid - it means the permission is assigned but grants no access
                # Useful for explicitly denying access
                pass
        
        return data


class EventReviewSerializer(serializers.ModelSerializer):
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.SerializerMethodField()
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventReview
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'user_full_name',
            'rating', 'comment', 'approved', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'user', 'approved', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this review'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the reviewing user'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/reviews/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        return links
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_user_full_name(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.full_name
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
    
    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def validate_comment(self, value):
        if value and len(value) < 10:
            raise serializers.ValidationError("Comment must be at least 10 characters long")
        if value and len(value) > 2000:
            raise serializers.ValidationError("Comment must not exceed 2000 characters")
        return value
    
    def validate_event(self, value):
        if not value:
            raise serializers.ValidationError("Event is required")
        
        # Check if event exists and is in appropriate status for reviews
        if value.status not in [EventStatusChoices.COMPLETED, EventStatusChoices.PUBLISHED, 
                                EventStatusChoices.OPEN, EventStatusChoices.IN_PROGRESS]:
            raise serializers.ValidationError("Reviews can only be submitted for active or completed events")
        
        return value
    
    def validate(self, data):
        # Prevent duplicate reviews
        if self.instance is None:
            event = data.get('event')
            user = self.context['request'].user
            
            if EventReview.objects.filter(event=event, user=user).exists():
                raise serializers.ValidationError("You have already submitted a review for this event")
        
        return data


class EventRoleSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventRole
        fields = (
            'id', 'name', 'description', 'code', 'category', 'category_display',
            'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this role'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        return {
            'self': request.build_absolute_uri(
                f"/api/event/roles/{obj.id}/"
            )
        }


class EventRoleAssignmentSerializer(serializers.ModelSerializer):
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventRoleAssignment
        fields = (
            'id', 'event', 'event_title', 'user', 'user_email', 'role', 'role_name',
            'assigned_at', 'assigned_by', 'assigned_by_email', '_links'
        )
        read_only_fields = ('id', 'assigned_at', 'assigned_by')
        extra_kwargs = {
            'assigned_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this role assignment'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the user'},
            'role': {'type': 'string', 'format': 'uri', 'description': 'Link to the role'},
            'assigned_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who assigned'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/role-assignments/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        if obj.role:
            links['role'] = request.build_absolute_uri(
                f"/api/event/roles/{obj.role.id}/"
            )
        
        if obj.assigned_by:
            links['assigned_by'] = request.build_absolute_uri(
                f"/api/users/{obj.assigned_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        if self.instance is None:
            if EventRoleAssignment.objects.filter(
                event=data.get('event'),
                user=data.get('user'),
                role=data.get('role')
            ).exists():
                raise serializers.ValidationError("This role is already assigned to this user for this event.")
        return data


class EventStaffAvailabilitySerializer(serializers.ModelSerializer):
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventStaffAvailability
        fields = (
            'id', 'staff', 'available_from', 'available_to', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
            'available_from': {'default': None},
            'available_to': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this availability record'},
            'staff': {'type': 'string', 'format': 'uri', 'description': 'Link to the staff member'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/staff-availability/{obj.id}/"
            )
        }
        
        if obj.staff:
            links['staff'] = request.build_absolute_uri(
                f"/api/event/staff/{obj.staff.staff_id}/"
            )
        
        return links
    
    def validate(self, data):
        if 'available_from' in data and 'available_to' in data:
            if data['available_from'] >= data['available_to']:
                raise serializers.ValidationError("available_from must be before available_to")
        return data


class EventStaffSerializer(serializers.ModelSerializer):
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    event_title = serializers.CharField(source='event.title', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    assigned_by_email = serializers.EmailField(source='assigned_by.email', read_only=True)
    availabilities = EventStaffAvailabilitySerializer(many=True, read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventStaff
        fields = (
            'staff_id', 'event', 'event_title', 'user', 'user_email',
            'assigned_at', 'assigned_by', 'assigned_by_email', 'notes', 'availabilities', '_links'
        )
        read_only_fields = ('staff_id', 'assigned_at', 'assigned_by')
        extra_kwargs = {
            'assigned_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this staff member'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'user': {'type': 'string', 'format': 'uri', 'description': 'Link to the user'},
            'assigned_by': {'type': 'string', 'format': 'uri', 'description': 'Link to user who assigned'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/staff/{obj.staff_id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        if obj.user:
            links['user'] = request.build_absolute_uri(
                f"/api/users/{obj.user.id}/"
            )
        
        if obj.assigned_by:
            links['assigned_by'] = request.build_absolute_uri(
                f"/api/users/{obj.assigned_by.id}/"
            )
        
        return links
    
    def validate(self, data):
        if self.instance is None:
            event = data.get('event')
            user = data.get('user')
            
            if not event:
                raise serializers.ValidationError({"event": "Event is required"})
            
            if not user:
                raise serializers.ValidationError({"user": "User is required"})
            
            if EventStaff.objects.filter(event=event, user=user).exists():
                raise serializers.ValidationError(
                    "This user is already assigned as staff for this event"
                )
        
        return data


class EventQuestionOptionSerializer(serializers.ModelSerializer):
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestionOption
        fields = ('id', 'question', 'option_text', 'order', 'created_at', 'updated_at', '_links')
        read_only_fields = ('id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
            'question': {'required': False},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this question option'},
            'question': {'type': 'string', 'format': 'uri', 'description': 'Link to the question'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/question-options/{obj.id}/"
            )
        }
        
        if obj.question:
            links['question'] = request.build_absolute_uri(
                f"/api/event/questions/{obj.question.id}/"
            )
        
        return links
    
    def validate_option_text(self, value):
        if not value or len(value.strip()) < 1:
            raise serializers.ValidationError("Option text cannot be empty")
        if len(value) > 255:
            raise serializers.ValidationError("Option text must not exceed 255 characters")
        return value.strip()


class EventQuestionNestedOptionSerializer(serializers.ModelSerializer):
    """Nested option serializer used for create/update question payloads."""

    class Meta:
        model = EventQuestionOption
        fields = ('id', 'option_text', 'order')
        read_only_fields = ('id',)


class EventQuestionSerializer(serializers.ModelSerializer):
    """
    Serializer for EventQuestion with nested writable options.
    
    Supports creating and updating questions with nested options in a single request.
    Options can be provided as an array of objects with option_text and order.
    
    For updates:
    - Options with 'id' field: update existing
    - Options without 'id': create new
    - Existing options not in payload: deleted
    """
    question_type_display = serializers.CharField(source='get_question_type_display', read_only=True)
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    event_title = serializers.CharField(source='event.title', read_only=True)
    options = EventQuestionNestedOptionSerializer(many=True, read_only=False, required=False)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestion
        fields = (
            'id', 'event', 'event_title', 'question_title', 'question_body',
            'question_type', 'question_type_display', 'required', 'public', 'order',
            'max_value', 'min_value', 'options', 'created_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
        extra_kwargs = {
            'created_at': {'default': None},
            'updated_at': {'default': None},
        }
        # Remove unique constraint validation at serializer level
        # Let the database-level deferrable constraint handle it during transaction commit
        # validators = []
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this question'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/questions/{obj.id}/"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        return links
    
    def validate_question_title(self, value):
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError("Question title must be at least 3 characters long")
        if len(value) > 255:
            raise serializers.ValidationError("Question title must not exceed 255 characters")
        return value.strip()
    
    def validate(self, data):
        question_type = data.get('question_type', self.instance.question_type if self.instance else None)
        min_value = data.get('min_value')
        max_value = data.get('max_value')
        options = data.get('options', [])
        
        # Validate slider questions
        if question_type == EventQuestionTypeChoices.SLIDER:
            if min_value is None or max_value is None:
                raise serializers.ValidationError({
                    "min_value": "Slider questions require both min_value and max_value"
                })
            if min_value >= max_value:
                raise serializers.ValidationError({
                    "max_value": "max_value must be greater than min_value"
                })
        
        # Ensure non-slider questions don't have min/max values
        if question_type in [EventQuestionTypeChoices.SHORT_ANSWER, EventQuestionTypeChoices.LONG_ANSWER,
                             EventQuestionTypeChoices.UPLOAD]:
            if min_value is not None or max_value is not None:
                raise serializers.ValidationError(
                    "This question type does not support min_value or max_value"
                )
        
        # Validate choice questions have at least one option
        if question_type in [EventQuestionTypeChoices.MULTIPLE_CHOICE, EventQuestionTypeChoices.SINGLE_CHOICE]:
            # For create: check options in data
            if not self.instance and len(options) < 1:
                raise serializers.ValidationError({
                    "options": "Choice questions must have at least one option"
                })
        else:
            # Non-choice questions should not have options
            if len(options) > 0:
                raise serializers.ValidationError({
                    "options": "This question type does not support options"
                })
        
        # Validate option_text uniqueness within this question
        option_texts = [opt.get('option_text', '').strip() for opt in options]
        if len(option_texts) != len(set(option_texts)):
            raise serializers.ValidationError({
                "options": "Option texts must be unique within a question"
            })
        
        return data
    
    def create(self, validated_data):
        """
        Create question with nested options atomically.
        
        Args:
            validated_data: Validated serializer data including options
            
        Returns:
            Created EventQuestion instance with nested options
        """
        from django.db import transaction
        
        options_data = validated_data.pop('options', [])
        
        with transaction.atomic():
            # Create the question
            question = EventQuestion(**validated_data)
            question.save()
            
            # Bulk create options if provided
            if options_data:
                options_to_create = [
                    EventQuestionOption(
                        question=question,
                        option_text=opt_data['option_text'],
                        order=opt_data.get('order', idx)
                    )
                    for idx, opt_data in enumerate(options_data)
                ]
                EventQuestionOption.objects.bulk_create(options_to_create)
        
        return question
    
    def update(self, instance, validated_data):
        """
        Update question with smart option merging and order management.
        
        Strategy:
        - Options with 'id': update existing
        - Options without 'id': create new
        - Existing options not in payload: delete
        - Order changes: shift other questions to prevent conflicts
        
        Args:
            instance: Existing EventQuestion instance
            validated_data: Validated serializer data
            
        Returns:
            Updated EventQuestion instance
        """
        from django.db import transaction
        from django.db.models import F
        
        options_data = validated_data.pop('options', None)
        new_order = validated_data.get('order')
        
        with transaction.atomic():
            # Handle order changes to prevent unique constraint violations and deadlocks
            if new_order is not None and new_order != instance.order:
                old_order = instance.order
                event = instance.event
                
                # Use select_for_update to prevent deadlocks by locking rows in consistent order
                # Lock all questions in this event ordered by PK to ensure consistent lock acquisition
                EventQuestion.objects.filter(event=event).select_for_update().order_by('id').exists()
                
                # Step 1: Move current question to high temporary order to avoid conflicts
                temp_order = 999999
                instance.order = temp_order
                instance.save(update_fields=['order'])
                
                # Step 2: Shift other questions
                questions = EventQuestion.objects.filter(event=event).exclude(id=instance.id)
                
                if new_order < old_order:
                    # Moving up: shift questions [new_order, old_order) down by 1
                    questions.filter(
                        order__gte=new_order,
                        order__lt=old_order
                    ).update(order=F('order') + 1)
                else:
                    # Moving down: shift questions (old_order, new_order] up by 1
                    questions.filter(
                        order__gt=old_order,
                        order__lte=new_order
                    ).update(order=F('order') - 1)
                
                # Step 3: Set current question to final position
                instance.order = new_order
            
            # Update question fields
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save() # deadlock occurs here
            
            # Handle options if provided
            if options_data is not None:
                # Get existing option IDs
                existing_option_ids = set(instance.options.values_list('id', flat=True))
                provided_option_ids = set()
                options_to_update = []
                options_to_create = []
                
                for opt_data in options_data:
                    opt_id = opt_data.get('id')
                    
                    if opt_id:
                        # Update existing option
                        provided_option_ids.add(opt_id)
                        try:
                            option = EventQuestionOption.objects.get(id=opt_id, question=instance)
                            option.option_text = opt_data.get('option_text', option.option_text)
                            option.order = opt_data.get('order', option.order)
                            options_to_update.append(option)
                        except EventQuestionOption.DoesNotExist:
                            # Option doesn't belong to this question - ignore
                            pass
                    else:
                        # Create new option
                        options_to_create.append(
                            EventQuestionOption(
                                question=instance,
                                option_text=opt_data['option_text'],
                                order=opt_data.get('order', 0)
                            )
                        )
                
                # Delete options not in payload FIRST to avoid constraint violations
                options_to_delete = existing_option_ids - provided_option_ids
                if options_to_delete:
                    EventQuestionOption.objects.filter(id__in=options_to_delete).delete()
                
                # Bulk update existing options
                if options_to_update:
                    EventQuestionOption.objects.bulk_update(
                        options_to_update,
                        ['option_text', 'order']
                    )
                
                # Bulk create new options
                if options_to_create:
                    EventQuestionOption.objects.bulk_create(options_to_create)
        
        return instance


class EventQuestionAnswerChoiceSerializer(serializers.ModelSerializer):
    option_text = serializers.CharField(source='option.option_text', read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestionAnswerChoice
        fields = ('id', 'answer', 'option', 'option_text', 'selected_at', '_links')
        read_only_fields = ('id', 'selected_at')
        extra_kwargs = {
            'selected_at': {'default': None},
        }
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this answer choice'},
            'answer': {'type': 'string', 'format': 'uri', 'description': 'Link to the answer'},
            'option': {'type': 'string', 'format': 'uri', 'description': 'Link to the option'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/answer-choices/{obj.id}/"
            )
        }
        
        if obj.answer:
            links['answer'] = request.build_absolute_uri(
                f"/api/event/question-answers/{obj.answer.id}/"
            )
        
        if obj.option:
            links['option'] = request.build_absolute_uri(
                f"/api/event/question-options/{obj.option.id}/"
            )
        
        return links
    
def get_attendee_qs():
    from apps.attendee.models import Attendee
    return Attendee.objects.all()   


class EventQuestionAnswerSerializer(serializers.ModelSerializer):
    """
    Serializer for EventQuestionAnswer with nested writable selected options.
    
    Supports creating and updating answers with option selections.
    Validates option selections against question constraints.
    """
    question_title = serializers.CharField(source='question.question_title', read_only=True)
    attendee = serializers.SlugRelatedField(slug_field='attendee_id', queryset=get_attendee_qs())
    attendee_name = serializers.SerializerMethodField()
    selected_options = EventQuestionAnswerChoiceSerializer(many=True, read_only=True)
    selected_option_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="List of option IDs to select for choice questions"
    )
    upload_resource_id = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="ID of uploaded Resource for upload-type questions"
    )
    upload_url = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Direct URL/path to uploaded file (alternative to upload_resource_id)"
    )
    resource_info = serializers.SerializerMethodField()

    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventQuestionAnswer
        fields = (
            'id', 'question', 'question_title', 'attendee', 'attendee_name',
            'answer_text', 'selected_options', 'selected_option_ids',
            'upload_resource_id', 'upload_url', 'resource_info',
            'submitted_at', 'updated_at', '_links'
        )
        read_only_fields = ('id', 'submitted_at', 'updated_at')
        extra_kwargs = {
            'submitted_at': {'default': None},
            'updated_at': {'default': None},
        }
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'resource_url': {'type': 'string', 'format': 'uri', 'description': 'URL of the resource'},
            'resource_type': {'type': 'string', 'description': 'Type of the resource (file, link, image)'},
            'resource_id': {'type': 'integer', 'description': 'ID of the resource'}
        },
    })
    def get_resource_info(self, obj):
        request = self.context.get('request')
        resource = self._resolve_resource_from_answer_text(obj.answer_text)
        if not resource:
            return None

        resource_url = resource.resource_url
        if request and resource_url and not str(resource_url).startswith(('http://', 'https://')):
            resource_url = request.build_absolute_uri(resource_url)

        return {
            "resource_url": resource_url,
            "resource_type": resource.resource_type,
            "resource_id": resource.id
        }

    def _resolve_resource_from_answer_text(self, answer_text):
        if answer_text is None:
            return None

        raw_answer = str(answer_text).strip()
        if not raw_answer:
            return None

        if raw_answer.isdigit():
            return Resource.objects.filter(pk=int(raw_answer)).first()

        parsed = urlparse(raw_answer)
        parsed_path = parsed.path or raw_answer
        normalized_path = parsed_path.strip().lstrip('/')

        if normalized_path.startswith('media/'):
            normalized_path = normalized_path[len('media/'):]

        file_name = posixpath.basename(normalized_path)

        exact_match = Resource.objects.filter(
            Q(file=normalized_path) |
            Q(image=normalized_path) |
            Q(link=raw_answer) |
            Q(link=parsed_path)
        ).first()
        if exact_match:
            return exact_match

        lookup = Q()
        lookup |= Q(file__icontains=raw_answer) | Q(image__icontains=raw_answer) | Q(link__icontains=raw_answer)

        if normalized_path:
            lookup |= Q(file__iendswith=normalized_path) | Q(image__iendswith=normalized_path) | Q(link__icontains=normalized_path)

        if file_name:
            lookup |= Q(file__iendswith=file_name) | Q(image__iendswith=file_name) | Q(link__icontains=file_name)

        return Resource.objects.filter(lookup).first()
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_attendee_name(self, obj):
        return obj.attendee.full_name
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this answer'},
            'question': {'type': 'string', 'format': 'uri', 'description': 'Link to the question'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/question-answers/{obj.id}/"
            )
        }
        
        if obj.question:
            links['question'] = request.build_absolute_uri(
                f"/api/event/questions/{obj.question.id}/"
            )
        
        return links
    
    def validate(self, data):
        """
        Validate answer data including option selections.
        
        Validates:
        - Options belong to the question
        - Single choice questions have exactly 1 selection
        - Multiple choice questions have at least 1 selection
        """
        question = data.get('question', self.instance.question if self.instance else None)
        selected_option_ids = data.get('selected_option_ids', [])
        upload_resource_id = data.get('upload_resource_id')
        upload_url = (data.get('upload_url') or '').strip()
        
        if not question:
            raise serializers.ValidationError("Question is required")

        if upload_resource_id is not None:
            upload_resource = Resource.objects.filter(pk=upload_resource_id).first()
            if not upload_resource:
                raise serializers.ValidationError({
                    "upload_resource_id": "Upload resource not found"
                })

            event_content_type = ContentType.objects.get_for_model(Event)
            if upload_resource.target_type_id != event_content_type.id or str(upload_resource.target_id) != str(question.event_id):
                raise serializers.ValidationError({
                    "upload_resource_id": "Upload resource does not belong to this question's event"
                })

            if not upload_resource.resource_url:
                raise serializers.ValidationError({
                    "upload_resource_id": "Upload resource does not have a valid URL"
                })

            data['_resolved_upload_resource'] = upload_resource
            data['answer_text'] = upload_resource.resource_url

        elif upload_url:
            data['answer_text'] = upload_url
        
        # Validate option selections for choice questions
        if question.question_type in [EventQuestionTypeChoices.SINGLE_CHOICE, EventQuestionTypeChoices.MULTIPLE_CHOICE]:
            if not selected_option_ids and not data.get('answer_text'):
                raise serializers.ValidationError({
                    "selected_option_ids": "At least one option must be selected for choice questions"
                })
            
            if selected_option_ids:
                # Verify all options belong to this question
                valid_option_ids = set(question.options.values_list('id', flat=True))
                invalid_options = set(selected_option_ids) - valid_option_ids
                
                if invalid_options:
                    raise serializers.ValidationError({
                        "selected_option_ids": f"Options {invalid_options} do not belong to this question"
                    })
                
                # Single choice can only have 1 selection
                if question.question_type == EventQuestionTypeChoices.SINGLE_CHOICE:
                    if len(selected_option_ids) > 1:
                        raise serializers.ValidationError({
                            "selected_option_ids": "Single choice questions can only have one selected option"
                        })

        if question.question_type == EventQuestionTypeChoices.UPLOAD:
            has_text = bool((data.get('answer_text') or '').strip())
            has_upload = upload_resource_id is not None or bool(upload_url)
            if not has_text and not has_upload:
                raise serializers.ValidationError({
                    "answer_text": "Upload questions require upload_resource_id, upload_url, or answer_text"
                })
        
        return data
    
    def create(self, validated_data):
        """
        Create answer with selected options atomically.
        
        Args:
            validated_data: Validated data including selected_option_ids
            
        Returns:
            Created EventQuestionAnswer with nested selections
        """
        from django.db import transaction
        
        selected_option_ids = validated_data.pop('selected_option_ids', [])
        validated_data.pop('upload_resource_id', None)
        validated_data.pop('upload_url', None)
        validated_data.pop('_resolved_upload_resource', None)
        
        with transaction.atomic():
            # Create the answer
            answer = EventQuestionAnswer.objects.create(**validated_data)
            
            # Bulk create answer choices
            if selected_option_ids:
                choices_to_create = [
                    EventQuestionAnswerChoice(
                        answer=answer,
                        option_id=option_id
                    )
                    for option_id in selected_option_ids
                ]
                EventQuestionAnswerChoice.objects.bulk_create(choices_to_create)
        
        return answer
    
    def update(self, instance, validated_data):
        """
        Update answer and replace all selected options atomically.
        
        Args:
            instance: Existing EventQuestionAnswer
            validated_data: Validated data
            
        Returns:
            Updated EventQuestionAnswer
        """
        from django.db import transaction
        
        selected_option_ids = validated_data.pop('selected_option_ids', None)
        new_upload_resource = validated_data.pop('_resolved_upload_resource', None)
        validated_data.pop('upload_resource_id', None)
        validated_data.pop('upload_url', None)
        old_upload_resource = self._resolve_resource_from_answer_text(instance.answer_text)
        
        with transaction.atomic():
            # Update answer fields
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if (
                new_upload_resource
                and old_upload_resource
                and old_upload_resource.id != new_upload_resource.id
                and not old_upload_resource.protected
            ):
                old_upload_resource.delete()
            
            # Replace all selected options if provided
            if selected_option_ids is not None:
                # Delete existing selections
                instance.selected_options.all().delete()
                
                # Create new selections
                if selected_option_ids:
                    choices_to_create = [
                        EventQuestionAnswerChoice(
                            answer=instance,
                            option_id=option_id
                        )
                        for option_id in selected_option_ids
                    ]
                    EventQuestionAnswerChoice.objects.bulk_create(choices_to_create)
        
        return instance


class EventVenueRoomSerializer(serializers.ModelSerializer):
    """Serializer for EventVenueRoom — rooms scoped to an EventVenue snapshot."""

    class Meta:
        model = EventVenueRoom
        fields = ('id', 'event_venue', 'room_name', 'description', 'capacity', 'added_at', 'updated_at')
        read_only_fields = ('id', 'added_at', 'updated_at')


class EventVenueContactSerializer(serializers.ModelSerializer):
    """Serializer for EventVenueContact — contacts scoped to an EventVenue snapshot."""

    class Meta:
        model = EventVenueContact
        fields = ('id', 'event_venue', 'contact_name', 'phone_number', 'email', 'role', 'added_at', 'updated_at')
        read_only_fields = ('id', 'added_at', 'updated_at')


class EventVenueMetadataSerializer(serializers.ModelSerializer):
    """Serializer for EventVenueMetadata — metadata entries scoped to an EventVenue snapshot."""

    class Meta:
        model = EventVenueMetadata
        fields = ('id', 'event_venue', 'label', 'value', 'added_at', 'updated_at')
        read_only_fields = ('id', 'added_at', 'updated_at')


class EventVenueSerializer(serializers.ModelSerializer):
    """
    Serializer for EventVenue — event-scoped venue snapshot.

    On create, pass ``source_venue_id`` to clone all fields (including rooms,
    contacts and metadata) from the matching global Venue.  If omitted the
    caller must supply the inline venue fields directly.

    Reads return fully-embedded sub-resource lists so that clients can render
    all venue data from a single API call.
    """
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_display_code = serializers.CharField(source='event.display_code', read_only=True)

    # Make name/address/source_venue_id optional at serializer level;
    # validate() enforces that one of source_venue_id OR (name + address) is supplied.
    source_venue_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(max_length=255, required=False, allow_blank=False)
    address = serializers.CharField(max_length=500, required=False, allow_blank=False)

    rooms = EventVenueRoomSerializer(many=True, read_only=True)
    contacts = EventVenueContactSerializer(many=True, read_only=True)
    metadata = EventVenueMetadataSerializer(many=True, read_only=True)

    _links = serializers.SerializerMethodField()

    class Meta:
        model = EventVenue
        fields = (
            'event_venue_id',
            'event',
            'event_title',
            'event_display_code',
            'source_venue_id',
            'name',
            'address',
            'postcode',
            'city',
            'poi_type',
            'latitude',
            'longitude',
            'description',
            'instructions',
            'notes',
            'capacity',
            'added_at',
            'updated_at',
            'rooms',
            'contacts',
            'metadata',
            'is_primary',   
            '_links',
        )
        read_only_fields = ('event_venue_id', 'added_at', 'updated_at')
        extra_kwargs = {
            'source_venue_id': {'required': False, 'allow_null': True},
        }
        validators = []

    def validate(self, attrs):
        # On create (no instance), require either source_venue_id or inline name+address.
        if self.instance is None:
            source_venue_id = attrs.get('source_venue_id')
            event = attrs.get('event')
            if source_venue_id and event:
                if EventVenue.objects.filter(event=event, source_venue_id=source_venue_id).exists():
                    raise serializers.ValidationError(
                        {'source_venue_id': 'This venue is already linked to this event.'}
                    )
                
            has_source = bool(attrs.get('source_venue_id'))
            has_inline = bool(attrs.get('name')) and bool(attrs.get('address'))
            if not has_source and not has_inline:
                raise serializers.ValidationError(
                    'Provide either source_venue_id (to clone a global venue) '
                    'or both name and address (for a direct snapshot).'
                )
        return attrs

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this event venue'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
        },
        'required': ['self'],
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        links = {
            'self': request.build_absolute_uri(f"/api/event/venues/{obj.event_venue_id}/")
        }
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        return links


class EventStaffInviteSerializer(serializers.ModelSerializer):
    """Serializer for EventStaffInvite model with HATEOAS support."""

    event = serializers.CharField(source='event.url_safe_title', read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_display_code = serializers.CharField(source='event.display_code', read_only=True)
    target_user_email = serializers.EmailField(source='target_user.email', read_only=True)
    target_user_name = serializers.SerializerMethodField()
    invited_by_email = serializers.EmailField(source='invited_by.email', read_only=True)
    invited_by_name = serializers.SerializerMethodField()
    is_valid = serializers.BooleanField(read_only=True)
    permission_template_name = serializers.SerializerMethodField()
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventStaffInvite
        fields = (
            'id', 'event', 'event_title', 'event_display_code',
            'target_user', 'target_user_email', 'target_user_name',
            'invited_by', 'invited_by_email', 'invited_by_name',
            'permission_template', 'permission_template_name',
            'accepted', 'accepted_at', 'expires_at', 'added_at',
            'is_active', 'is_valid', '_links'
        )
        read_only_fields = ('id', 'added_at', 'accepted_at', 'is_valid', 'event', 'invited_by')
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_target_user_name(self, obj):
        """Get full name of the target user."""
        if obj.target_user:
            return obj.target_user.get_full_name() or obj.target_user.email
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_invited_by_name(self, obj):
        """Get full name of the user who sent the invite."""
        if obj.invited_by:
            return obj.invited_by.get_full_name() or obj.invited_by.email
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_permission_template_name(self, obj):
        """Get the name of the permission template if one is set."""
        if obj.permission_template:
            from apps.events.services.permission_templates import get_template
            template = get_template(obj.permission_template)
            return template['name'] if template else obj.permission_template
        return None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this invite'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'target_user': {'type': 'string', 'format': 'uri', 'description': 'Link to the target user'},
            'invited_by': {'type': 'string', 'format': 'uri', 'description': 'Link to the user who sent the invite'},
            'accept': {'type': 'string', 'format': 'uri', 'description': 'Link to accept this invite'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        event_id = self.context.get('event') or self.context.get('event_id') or (obj.event.url_safe_title if obj.event else None)
        if not request or not event_id:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{event_id}/staff-invites/{obj.id}"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        if obj.target_user:
            links['target_user'] = request.build_absolute_uri(
                f"/api/users/{obj.target_user.id}/"
            )
        
        if obj.invited_by:
            links['invited_by'] = request.build_absolute_uri(
                f"/api/users/{obj.invited_by.id}/"
            )
        
        # Add accept action link if invite is valid
        if obj.is_valid:
            links['accept'] = request.build_absolute_uri(
                f"/api/event/list/{event_id}/staff-invites/{obj.id}/accept"
            )
        
        return links
    
    def validate_target_user(self, value):
        """Validate that the target user exists."""
        if not value:
            raise serializers.ValidationError("Target user is required.")
        return value
    
    def validate_expires_at(self, value):
        """Validate that expiry date is in the future."""
        if value and value < timezone.now():
            raise serializers.ValidationError("Expiry date must be in the future.")
        return value
    
    def validate_permission_template(self, value):
        """Validate that the permission template code is valid."""
        if value:
            from apps.events.services.permission_templates import is_valid_template
            if not is_valid_template(value):
                raise serializers.ValidationError(
                    f"Invalid permission template code: {value}. "
                    "Use GET /api/event/permission-templates to see available templates."
                )
        return value
    
    def validate(self, data):
        """Validate the entire invite creation/update."""
        # Get event from context (set by viewset)
        event_id = self.context.get('event') or self.context.get('event_id')
        if not event_id and self.instance:
            event_id = self.instance.event.url_safe_title
        
        if not event_id:
            raise serializers.ValidationError("Event context is required.")
        
        try:
            event = get_event_by_identifier(event_id)
        except Event.DoesNotExist:
            raise serializers.ValidationError("Event with this ID does not exist.")
        
        # Check if user already has an active invite for this event (only on create)
        if self.instance is None:
            target_user = data.get('target_user')
            
            if target_user:
                # Validate user is in the organization (if event has one)
                if event.organisation:
                    from apps.events.services.staff_service import validate_user_in_organization
                    try:
                        validate_user_in_organization(target_user, event)
                    except serializers.ValidationError as e:
                        raise serializers.ValidationError(str(e))
                
                existing_invite = EventStaffInvite.objects.filter(
                    event=event,
                    target_user=target_user,
                    is_active=True
                ).first()
                
                if existing_invite:
                    raise serializers.ValidationError(
                        "An active invite already exists for this user and event."
                    )
                
                # Check if user is already event staff
                existing_staff = EventStaff.objects.filter(
                    event=event,
                    user=target_user
                ).first()
                
                if existing_staff:
                    raise serializers.ValidationError(
                        "This user is already a staff member for this event."
                    )
        
        # Store event for create method
        data['_event'] = event
        
        return data
    
    def create(self, validated_data):
        """Create a new staff invite with the authenticated user as invited_by."""
        # Get event from validated data
        event = validated_data.pop('_event')
        
        # Set invited_by to the current user
        request = self.context.get('request')
        if request and request.user:
            validated_data['invited_by'] = request.user
        
        validated_data['event'] = event
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Update a staff invite."""
        # Remove _event if present
        validated_data.pop('_event', None)
        
        # Don't allow changing event or invited_by
        validated_data.pop('event', None)
        validated_data.pop('invited_by', None)
        
        return super().update(instance, validated_data)


class EventStaffInviteListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing staff invites."""
    
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_display_code = serializers.CharField(source='event.display_code', read_only=True)
    event = serializers.CharField(source='event.url_safe_title', read_only=True)

    target_user_email = serializers.EmailField(source='target_user.email', read_only=True)
    target_user_name = serializers.SerializerMethodField()
    invited_by_email = serializers.EmailField(source='invited_by.email', read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    _links = serializers.SerializerMethodField()
    
    class Meta:
        model = EventStaffInvite
        fields = (
            'id', 'event_title', 'event_display_code', 'event',
            'target_user_email', 'target_user_name', 
            'invited_by_email', 'accepted', 'added_at', 'expires_at',
            'is_active', 'is_valid', '_links'
        )
        read_only_fields = fields
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_target_user_name(self, obj):
        """Get full name of the target user."""
        if obj.target_user:
            return obj.target_user.get_full_name() or obj.target_user.email
        return None
    
    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this invite'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'accept': {'type': 'string', 'format': 'uri', 'description': 'Link to accept this invite'}
        },
        'required': ['self']
    })
    def get__links(self, obj):
        request = self.context.get('request')
        event_id = self.context.get('event') or self.context.get('event_id') or (obj.event.url_safe_title if obj.event else None)
        if not request or not event_id:
            return {}
        
        links = {
            'self': request.build_absolute_uri(
                f"/api/event/list/{event_id}/staff-invites/{obj.id}"
            )
        }
        
        if obj.event:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        
        if obj.is_valid:
            links['accept'] = request.build_absolute_uri(
                f"/api/event/list/{event_id}/staff-invites/{obj.id}/accept"
            )
        
        return links


class EventNotificationSerializer(serializers.ModelSerializer):
    """Read-only serializer for EventNotification. Mutations are internal-only."""

    notification_type_display = serializers.CharField(
        source='get_notification_type_display', read_only=True
    )
    related_payment = serializers.CharField(source='related_payment.payment_id', read_only=True)
    related_order = serializers.CharField(source='related_order.order_id', read_only=True)
    related_booking = serializers.CharField(source='related_booking.booking_reference', read_only=True)
    priority_display = serializers.CharField(
        source='get_priority_display', read_only=True
    )
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_display_code = serializers.CharField(source='event.display_code', read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True, allow_null=True)

    _links = serializers.SerializerMethodField()

    class Meta:
        model = EventNotification
        fields = (
            'id',
            'event',
            'event_title',
            'event_display_code',
            'notification_type',
            'notification_type_display',
            'priority',
            'priority_display',
            'related_payment',
            'related_order',
            'related_booking',
            'is_read',
            'metadata',
            'created_by',
            'created_by_email',
            'created_at',
            'read_at',
            '_links',
        )
        read_only_fields = fields

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri', 'description': 'Link to this notification'},
            'event': {'type': 'string', 'format': 'uri', 'description': 'Link to the event'},
            'mark_read': {'type': 'string', 'format': 'uri', 'description': 'Action URL to mark notification as read'},
        },
        'required': ['self'],
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        base = f"/api/event/notifications/{obj.id}"
        links = {
            'self': request.build_absolute_uri(f"{base}/"),
            'mark_read': request.build_absolute_uri(f"{base}/mark-read/"),
        }
        if obj.event_id:
            links['event'] = request.build_absolute_uri(
                f"/api/event/list/{obj.event.url_safe_title}/"
            )
        return links
