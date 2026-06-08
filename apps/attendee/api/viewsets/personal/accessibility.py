from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.attendee.models import AccessibilityRequirement, AttendeeAccessibilityRequirement
from apps.attendee.api.serializers import AccessibilityRequirementSerializer, AttendeeAccessibilityRequirementSerializer
from apps.attendee.api.filtersets import AccessibilityRequirementFilterSet, AttendeeAccessibilityRequirementFilterSet
from apps.attendee.api.permissions import CanManageAttendeePersonalInfo, IsStaffOrReadOnly
from apps.common.pagination import StandardPagination
from .mixins import NestedAttendeeViewSetMixin

@extend_schema_view(
    list=extend_schema(
        summary="List Accessibility Requirements",
        description=(
            "Retrieve a list of available accessibility requirement types that can be assigned to attendees. "
            "These represent various accessibility needs such as wheelchair access, sign language interpretation, "
            "visual aids, hearing assistance, and other accommodations. "
            "Each requirement includes verification status for compliance tracking."
        ),
        tags=['Accessibility Requirements']
    ),
    retrieve=extend_schema(
        summary="Get Accessibility Requirement Details",
        description=(
            "Retrieve detailed information about a specific accessibility requirement type including "
            "code, label, description, verification status, and active status."
        ),
        tags=['Accessibility Requirements']
    ),
    create=extend_schema(
        summary="Create Accessibility Requirement",
        description=(
            "Create a new accessibility requirement type for event accessibility planning. "
            "Staff can define custom accessibility accommodations with codes, labels, and descriptions. "
            "Supports verification workflows for compliance."
        ),
        tags=['Accessibility Requirements']
    ),
    update=extend_schema(
        summary="Update Accessibility Requirement",
        description=(
            "Update an accessibility requirement type's details including label, description, "
            "verification status, or active status. Used to maintain the accessibility catalog."
        ),
        tags=['Accessibility Requirements']
    ),
    partial_update=extend_schema(
        summary="Partially Update Accessibility Requirement",
        description="Partially update an accessibility requirement without providing complete payload.",
        tags=['Accessibility Requirements']
    ),
    destroy=extend_schema(
        summary="Delete Accessibility Requirement",
        description="Delete an accessibility requirement type (use with caution if assignments exist).",
        tags=['Accessibility Requirements']
    )
)
class AccessibilityRequirementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AccessibilityRequirement types.
    
    Provides a catalog of accessibility accommodations that can be assigned to attendees.
    Supports compliance tracking through verification status management.
    Read-only for non-staff users.
    """
    
    queryset = AccessibilityRequirement.objects.all()
    serializer_class = AccessibilityRequirementSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AccessibilityRequirementFilterSet
    search_fields = ['code', 'label', 'description']
    ordering_fields = ['label', 'added_at']
    ordering = ['label']


@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Accessibility Requirements",
        description=(
            "Retrieve accessibility requirements assigned to attendees. "
            "Shows which attendees have specific accessibility needs with detailed notes and verification status. "
            "Supports filtering by attendee, requirement type, and verification status for compliance reporting."
        ),
        tags=['Attendee Accessibility']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Accessibility Requirement Details",
        description=(
            "Retrieve detailed information about a specific attendee's accessibility requirement including "
            "the requirement type, specific details, accommodation notes, verification status, and verification history."
        ),
        tags=['Attendee Accessibility']
    ),
    create=extend_schema(
        summary="Assign Accessibility Requirement",
        description=(
            "Assign an accessibility requirement to an attendee with specific details and accommodation notes. "
            "Captures attendee-specific needs beyond the standard requirement definition. "
            "Automatically tracks creation timestamp for audit purposes."
        ),
        tags=['Attendee Accessibility']
    ),
    update=extend_schema(
        summary="Update Accessibility Requirement Assignment",
        description=(
            "Update an attendee's accessibility requirement details, notes, or verification status. "
            "Used to refine accommodation plans or update verification as accommodations are confirmed."
        ),
        tags=['Attendee Accessibility']
    ),
    partial_update=extend_schema(
        summary="Partially Update Accessibility Requirement Assignment",
        description="Partially update accessibility requirement details without providing complete payload.",
        tags=['Attendee Accessibility']
    ),
    destroy=extend_schema(
        summary="Remove Accessibility Requirement",
        description=(
            "Remove an accessibility requirement assignment from an attendee when it is no longer needed. "
            "Does not delete the requirement type, only the assignment to this specific attendee."
        ),
        tags=['Attendee Accessibility']
    )
)
class AttendeeAccessibilityRequirementViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeAccessibilityRequirement assignments.
    
    Handles the association of accessibility requirements with specific attendees,
    including detailed notes, verification status, and accommodation planning.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeAccessibilityRequirement.objects.select_related(
        'attendee', 'accessibility_requirement'
    ).all()
    serializer_class = AttendeeAccessibilityRequirementSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeAccessibilityRequirementFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']
