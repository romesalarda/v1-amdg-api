from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.attendee.models import MedicalCondition, AttendeeMedicalCondition
from apps.attendee.api.serializers import MedicalConditionSerializer, AttendeeMedicalConditionSerializer
from apps.attendee.api.filtersets import MedicalConditionFilterSet, AttendeeMedicalConditionFilterSet
from apps.attendee.api.permissions import CanManageAttendeePersonalInfo, IsStaffOrReadOnly
from apps.common.pagination import StandardPagination
from .mixins import NestedAttendeeViewSetMixin

@extend_schema_view(
    list=extend_schema(
        summary="List Medical Conditions",
        description=(
            "Retrieve a list of available medical condition types for attendee health management. "
            "Includes common conditions such as asthma, diabetes, epilepsy, heart conditions, "
            "allergies, and other medical concerns requiring monitoring or emergency response. "
            "Each condition can be assigned to attendees with severity levels (mild, moderate, severe)."
        ),
        tags=['Medical Conditions']
    ),
    retrieve=extend_schema(
        summary="Get Medical Condition Details",
        description=(
            "Retrieve detailed information about a specific medical condition type including "
            "code, label, description, verification status, and active status."
        ),
        tags=['Medical Conditions']
    ),
    create=extend_schema(
        summary="Create Medical Condition",
        description=(
            "Create a new medical condition type for health management and emergency response planning. "
            "Staff can define custom medical conditions with codes, labels, and descriptions. "
            "Supports verification workflows for medical compliance."
        ),
        tags=['Medical Conditions']
    ),
    update=extend_schema(
        summary="Update Medical Condition",
        description=(
            "Update a medical condition type's details including label, description, "
            "verification status, or active status. Used to maintain the medical conditions catalog."
        ),
        tags=['Medical Conditions']
    ),
    partial_update=extend_schema(
        summary="Partially Update Medical Condition",
        description="Partially update a medical condition without providing complete payload.",
        tags=['Medical Conditions']
    ),
    destroy=extend_schema(
        summary="Delete Medical Condition",
        description="Delete a medical condition type (use with caution if assignments exist).",
        tags=['Medical Conditions']
    )
)
class MedicalConditionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing MedicalCondition types.
    
    Provides a catalog of medical conditions for attendee health monitoring.
    Supports emergency response planning and medical compliance tracking.
    Read-only for non-staff users.
    """
    
    queryset = MedicalCondition.objects.all()
    serializer_class = MedicalConditionSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = MedicalConditionFilterSet
    search_fields = ['code', 'label', 'description']
    ordering_fields = ['label', 'added_at']
    ordering = ['label']

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Medical Conditions",
        description=(
            "Retrieve medical conditions assigned to attendees for health monitoring and emergency response. "
            "Shows which attendees have specific medical conditions with severity levels (mild, moderate, severe), "
            "detailed notes, and verification status. Critical for event safety and medical preparedness."
        ),
        tags=['Attendee Medical']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Medical Condition Details",
        description=(
            "Retrieve detailed information about a specific attendee's medical condition including "
            "the condition type, severity level, specific details, medical notes, verification status, and verification history."
        ),
        tags=['Attendee Medical']
    ),
    create=extend_schema(
        summary="Assign Medical Condition",
        description=(
            "Assign a medical condition to an attendee with severity level and specific medical details. "
            "Captures attendee-specific medical needs for emergency response planning and health monitoring. "
            "Severity levels: mild, moderate, severe. Automatically tracks creation timestamp for audit purposes."
        ),
        tags=['Attendee Medical']
    ),
    update=extend_schema(
        summary="Update Medical Condition Assignment",
        description=(
            "Update an attendee's medical condition details, severity level, notes, or verification status. "
            "Used to refine emergency response plans or update verification as medical information is confirmed."
        ),
        tags=['Attendee Medical']
    ),
    partial_update=extend_schema(
        summary="Partially Update Medical Condition Assignment",
        description="Partially update medical condition details without providing complete payload.",
        tags=['Attendee Medical']
    ),
    destroy=extend_schema(
        summary="Remove Medical Condition",
        description=(
            "Remove a medical condition assignment from an attendee when it is no longer applicable. "
            "Does not delete the condition type, only the assignment to this specific attendee."
        ),
        tags=['Attendee Medical']
    )
)
class AttendeeMedicalConditionViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeMedicalCondition assignments.
    
    Handles the association of medical conditions with specific attendees,
    including severity levels, detailed medical notes, and verification status.
    Critical for event safety, emergency response, and health management.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeMedicalCondition.objects.select_related(
        'attendee', 'medical_condition'
    ).all()
    serializer_class = AttendeeMedicalConditionSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeMedicalConditionFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']

