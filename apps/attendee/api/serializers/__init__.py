"""
Attendee API Serializers.

Export all serializers for easy importing:
    from apps.attendee.api.serializers import AttendeeListSerializer, ...
"""
from .base import (
    AttendeeListSerializer,
    AttendeeDetailSerializer,
    AttendeeCreateSerializer,
    AttendeeUpdateSerializer,
    AttendeeGuardianSerializer,
    AttendeeActionSerializer,
    FamilyGroupListSerializer,
    FamilyGroupDetailSerializer,
    FamilyGroupCreateUpdateSerializer,
    AttendeeMessageListSerializer,
    AttendeeMessageDetailSerializer,
    AttendeeMessageCreateSerializer,
    AttendeeMessageUpdateSerializer,
)

from .personal import (
    AccessibilityRequirementSerializer,
    AttendeeAccessibilityRequirementSerializer,
    DietaryRequirementSerializer,
    AttendeeDietaryRequirementSerializer,
    MedicalConditionSerializer,
    AttendeeMedicalConditionSerializer,
    EmergencyContactSerializer,
    ConsentSerializer,
    AttendeeConsentSerializer,
    EventAttendanceSerializer,
    AttendeeOrganisationSerializer,
    FamilyAttendeeSerializer,
)

__all__ = [
    # Base serializers
    'AttendeeListSerializer',
    'AttendeeDetailSerializer',
    'AttendeeCreateSerializer',
    'AttendeeUpdateSerializer',
    'AttendeeGuardianSerializer',
    'AttendeeActionSerializer',
    'FamilyGroupListSerializer',
    'FamilyGroupDetailSerializer',
    'FamilyGroupCreateUpdateSerializer',
    'AttendeeMessageListSerializer',
    'AttendeeMessageDetailSerializer',
    'AttendeeMessageCreateSerializer',
    'AttendeeMessageUpdateSerializer',
    # Personal serializers
    'AccessibilityRequirementSerializer',
    'AttendeeAccessibilityRequirementSerializer',
    'DietaryRequirementSerializer',
    'AttendeeDietaryRequirementSerializer',
    'MedicalConditionSerializer',
    'AttendeeMedicalConditionSerializer',
    'EmergencyContactSerializer',
    'ConsentSerializer',
    'AttendeeConsentSerializer',
    'EventAttendanceSerializer',
    'AttendeeOrganisationSerializer',
    'FamilyAttendeeSerializer',
]
