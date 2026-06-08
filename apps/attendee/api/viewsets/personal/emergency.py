from rest_framework import viewsets,filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from apps.attendee.models import EmergencyContact
from apps.attendee.api.serializers import EmergencyContactSerializer
from apps.attendee.api.filtersets import EmergencyContactFilterSet
from apps.attendee.api.permissions import CanManageAttendeePersonalInfo
from apps.common.pagination import StandardPagination
from .mixins import NestedAttendeeViewSetMixin

@extend_schema_view(
    list=extend_schema(
        summary="List Emergency Contacts",
        description=(
            "Retrieve a list of emergency contacts for attendees. "
            "Emergency contacts are individuals to be notified in case of medical emergencies, accidents, or urgent situations. "
            "Each attendee can have multiple contacts with one designated as primary. "
            "Essential for event safety and emergency response protocols."
        ),
        tags=['Emergency Contacts']
    ),
    retrieve=extend_schema(
        summary="Get Emergency Contact Details",
        description=(
            "Retrieve detailed information about a specific emergency contact including "
            "name, relationship to attendee, phone numbers, email, and primary contact designation."
        ),
        tags=['Emergency Contacts']
    ),
    create=extend_schema(
        summary="Create Emergency Contact",
        description=(
            "Create a new emergency contact for an attendee. "
            "Requires contact name, relationship, and at least one contact method (phone or email). "
            "Designate as primary contact if this is the first or most important contact for emergencies."
        ),
        tags=['Emergency Contacts']
    ),
    update=extend_schema(
        summary="Update Emergency Contact",
        description=(
            "Update emergency contact information including contact details, relationship, or primary designation. "
            "Ensures attendee emergency information remains current for safety purposes."
        ),
        tags=['Emergency Contacts']
    ),
    partial_update=extend_schema(
        summary="Partially Update Emergency Contact",
        description="Partially update emergency contact details without providing complete payload.",
        tags=['Emergency Contacts']
    ),
    destroy=extend_schema(
        summary="Delete Emergency Contact",
        description=(
            "Remove an emergency contact from an attendee's record. "
            "Use caution when removing primary contacts to ensure attendee always has emergency contact information."
        ),
        tags=['Emergency Contacts']
    )
)
class EmergencyContactViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing EmergencyContact records.
    
    Handles emergency contact information for attendees including multiple contacts per attendee,
    primary contact designation, and comprehensive contact information.
    Critical for event safety and emergency response.
    Supports nested access under attendee resources.
    """
    
    queryset = EmergencyContact.objects.select_related('attendee').all()
    serializer_class = EmergencyContactSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EmergencyContactFilterSet
    search_fields = ['first_name', 'last_name', 'phone_number', 'email']
    ordering_fields = ['added_at', 'primary_contact']
    ordering = ['-primary_contact', '-added_at']

