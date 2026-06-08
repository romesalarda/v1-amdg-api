from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.attendee.models import DietaryRequirement, AttendeeDietaryRequirement
from apps.attendee.api.serializers import DietaryRequirementSerializer, AttendeeDietaryRequirementSerializer
from apps.attendee.api.filtersets import DietaryRequirementFilterSet, AttendeeDietaryRequirementFilterSet
from apps.attendee.api.permissions import CanManageAttendeePersonalInfo,IsStaffOrReadOnly
from apps.common.pagination import StandardPagination
from .mixins import NestedAttendeeViewSetMixin

@extend_schema_view(
    list=extend_schema(
        summary="List Dietary Requirements",
        description=(
            "Retrieve a list of available dietary requirement types for event meal planning. "
            "Includes common dietary needs such as vegetarian, vegan, halal, kosher, gluten-free, "
            "lactose-free, nut allergies, and other dietary restrictions. "
            "Each requirement can be assigned to attendees for catering purposes."
        ),
        tags=['Dietary Requirements']
    ),
    retrieve=extend_schema(
        summary="Get Dietary Requirement Details",
        description=(
            "Retrieve detailed information about a specific dietary requirement type including "
            "code, label, description, verification status, and active status."
        ),
        tags=['Dietary Requirements']
    ),
    create=extend_schema(
        summary="Create Dietary Requirement",
        description=(
            "Create a new dietary requirement type for meal planning and catering. "
            "Staff can define custom dietary needs with codes, labels, and descriptions. "
            "Supports verification workflows for dietary compliance."
        ),
        tags=['Dietary Requirements']
    ),
    update=extend_schema(
        summary="Update Dietary Requirement",
        description=(
            "Update a dietary requirement type's details including label, description, "
            "verification status, or active status. Used to maintain the dietary catalog."
        ),
        tags=['Dietary Requirements']
    ),
    partial_update=extend_schema(
        summary="Partially Update Dietary Requirement",
        description="Partially update a dietary requirement without providing complete payload.",
        tags=['Dietary Requirements']
    ),
    destroy=extend_schema(
        summary="Delete Dietary Requirement",
        description="Delete a dietary requirement type (use with caution if assignments exist).",
        tags=['Dietary Requirements']
    )
)
class DietaryRequirementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing DietaryRequirement types.
    
    Provides a catalog of dietary restrictions and preferences for event catering.
    Supports meal planning, allergen management, and dietary compliance.
    Read-only for non-staff users.
    """
    
    queryset = DietaryRequirement.objects.all()
    serializer_class = DietaryRequirementSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DietaryRequirementFilterSet
    search_fields = ['code', 'label', 'description']
    ordering_fields = ['label', 'added_at']
    ordering = ['label']


@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Dietary Requirements",
        description=(
            "Retrieve dietary requirements assigned to attendees for meal planning and catering. "
            "Shows which attendees have specific dietary needs with detailed notes and verification status. "
            "Essential for event catering, allergen management, and dietary compliance."
        ),
        tags=['Attendee Dietary']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Dietary Requirement Details",
        description=(
            "Retrieve detailed information about a specific attendee's dietary requirement including "
            "the requirement type, specific details, preparation notes, verification status, and verification history."
        ),
        tags=['Attendee Dietary']
    ),
    create=extend_schema(
        summary="Assign Dietary Requirement",
        description=(
            "Assign a dietary requirement to an attendee with specific details and preparation notes. "
            "Captures attendee-specific dietary needs, allergies, and restrictions for safe meal preparation. "
            "Automatically tracks creation timestamp for audit purposes."
        ),
        tags=['Attendee Dietary']
    ),
    update=extend_schema(
        summary="Update Dietary Requirement Assignment",
        description=(
            "Update an attendee's dietary requirement details, notes, or verification status. "
            "Used to refine meal plans or update verification as dietary needs are confirmed."
        ),
        tags=['Attendee Dietary']
    ),
    partial_update=extend_schema(
        summary="Partially Update Dietary Requirement Assignment",
        description="Partially update dietary requirement details without providing complete payload.",
        tags=['Attendee Dietary']
    ),
    destroy=extend_schema(
        summary="Remove Dietary Requirement",
        description=(
            "Remove a dietary requirement assignment from an attendee when it is no longer applicable. "
            "Does not delete the requirement type, only the assignment to this specific attendee."
        ),
        tags=['Attendee Dietary']
    )
)
class AttendeeDietaryRequirementViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeDietaryRequirement assignments.
    
    Handles the association of dietary requirements with specific attendees,
    including detailed notes, verification status, and meal planning information.
    Critical for safe event catering and allergen management.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeDietaryRequirement.objects.select_related(
        'attendee', 'dietary_requirement'
    ).all()
    serializer_class = AttendeeDietaryRequirementSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeDietaryRequirementFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']