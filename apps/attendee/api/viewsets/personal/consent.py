from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from apps.attendee.models import Consent, AttendeeConsent
from apps.attendee.api.serializers import ConsentSerializer, AttendeeConsentSerializer
from apps.attendee.api.filtersets import ConsentFilterSet, AttendeeConsentFilterSet
from apps.attendee.api.permissions import CanManageAttendeePersonalInfo
from apps.common.pagination import StandardPagination
from .mixins import NestedAttendeeViewSetMixin

@extend_schema_view(
    list=extend_schema(
        summary="List Consents",
        description=(
            "Retrieve a list of available consent types for events. "
            "Consents are legal agreements or permissions required from attendees such as photo/video release, "
            "medical treatment authorization, liability waivers, code of conduct acknowledgment, "
            "and data processing permissions. Each consent type is associated with a specific event."
        ),
        tags=['Consents']
    ),
    retrieve=extend_schema(
        summary="Get Consent Details",
        description=(
            "Retrieve detailed information about a specific consent type including "
            "code, title, description, associated event, and creation timestamp."
        ),
        tags=['Consents']
    ),
    create=extend_schema(
        summary="Create Consent",
        description=(
            "Create a new consent type for an event. "
            "Define legal agreements or permissions required from attendees with unique codes, titles, and descriptions. "
            "Each consent can then be individually granted or declined by attendees."
        ),
        tags=['Consents']
    ),
    update=extend_schema(
        summary="Update Consent",
        description=(
            "Update a consent type's details including title or description. "
            "Used to maintain consent definitions and legal language for compliance."
        ),
        tags=['Consents']
    ),
    partial_update=extend_schema(
        summary="Partially Update Consent",
        description="Partially update a consent type without providing complete payload.",
        tags=['Consents']
    ),
    destroy=extend_schema(
        summary="Delete Consent",
        description="Delete a consent type (use with caution if attendee consent records exist).",
        tags=['Consents']
    )
)
class ConsentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Consent types.
    
    Provides a catalog of consent types required for event participation.
    Supports legal compliance, liability management, and data protection.
    Read-only for non-staff users.
    """
    
    queryset = Consent.objects.select_related('event').all()
    serializer_class = ConsentSerializer
    permission_classes = []
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ConsentFilterSet
    search_fields = ['code', 'title', 'description']
    ordering_fields = ['title', 'created_at']
    ordering = ['title']


@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Consents",
        description=(
            "Retrieve consent records for attendees showing which consents have been granted or declined. "
            "Tracks attendee agreement to event terms, photo releases, liability waivers, and other legal permissions. "
            "Includes consent status (granted/declined), timestamp, and optional consent giver information for minors. "
            "Essential for legal compliance and event liability management."
        ),
        tags=['Attendee Consents']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Consent Details",
        description=(
            "Retrieve detailed information about a specific attendee's consent record including "
            "the consent type, granted status, recording timestamp, when consent was given, and who gave consent (for minors)."
        ),
        tags=['Attendee Consents']
    ),
    create=extend_schema(
        summary="Record Attendee Consent",
        description=(
            "Record a consent grant or decline for an attendee. "
            "Captures whether consent is given, when it was given, and optionally who gave consent (parent/guardian for minors). "
            "Creates an immutable audit trail for legal compliance."
        ),
        tags=['Attendee Consents']
    ),
    update=extend_schema(
        summary="Update Attendee Consent",
        description=(
            "Update an attendee's consent record such as changing consent status or recording withdrawal of consent. "
            "Maintains compliance with data protection regulations and consent management requirements."
        ),
        tags=['Attendee Consents']
    ),
    partial_update=extend_schema(
        summary="Partially Update Attendee Consent",
        description="Partially update consent record details without providing complete payload.",
        tags=['Attendee Consents']
    ),
    destroy=extend_schema(
        summary="Remove Consent Record",
        description=(
            "Remove a consent record from an attendee. "
            "Use with caution as consent records are typically maintained for legal compliance. "
            "Consider marking as declined rather than deleting for audit trail purposes."
        ),
        tags=['Attendee Consents']
    )
)
class AttendeeConsentViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeConsent records.
    
    Handles the recording and management of consent grants/declines for attendees.
    Supports legal compliance, GDPR/data protection, and liability management.
    Maintains audit trail of consent decisions.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeConsent.objects.select_related('attendee', 'consent').all()
    serializer_class = AttendeeConsentSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeConsentFilterSet
    ordering_fields = ['recorded_at', 'given_at']
    ordering = ['-recorded_at']

