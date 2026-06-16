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

from .statistics import (
    AgeDistributionSerializer,
    GenderDistributionSerializer,
    RelationshipDistributionSerializer,
    AreaDistributionSerializer,
    MedicalConditionsStatsSerializer,
    AccessibilityRequirementsStatsSerializer,
    DietaryRequirementsStatsSerializer,
    EmergencyContactStatsSerializer,
    ConsentStatsSerializer,
    AttendeeRegistrationTrendsSerializer,
    AttendanceStatsSerializer,
    PersonalInfoCombinedSerializer,
    AttendeeOverviewStatsSerializer,
    DemographicsSerializer,
)

from .pre_removal import (
    PaymentBlockerItemSerializer,
    TicketBlockerItemSerializer,
    OrderBlockerItemSerializer,
    AttendeePreRemovalBlockerItemSerializer,
    AttendeePreRemovalBlockerPaginationSerializer,
    AttendeePreRemovalBlockerSerializer,
    AttendeePreRemovalRefundSummarySerializer,
    AttendeePreRemovalSummarySerializer,
)

from .checkin import (
    CheckInCreateSerializer,
    CheckInResponseSerializer,
    CheckInBroadcastSerializer,
    CheckInFilterSerializer,
    CheckInHistoryRequestSerializer,
    BulkDeleteCheckInsSerializer,
    BulkAttendeeStatusUpdateSerializer,
    AttendeeStatusUpdateSerializer,
    AttendeeRosterFilterSerializer,
    AttendeeRosterRequestSerializer,
    AttendeeRosterItemSerializer,
)

from .filter_serializers import (
    AttendeeFilterRequestSerializer,
    AttendeeFilterResponseSerializer,
    AttendeeFiltersSerializer,
    FormConditionSerializer,
    FormsFilterSerializer,
    RegistrationQuestionsFilterSerializer,
    DemographicsFilterSerializer,
    StatusFilterSerializer,
    OrdersFilterSerializer,
    PaymentsFilterSerializer,
    AdvancedFilterSerializer,
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
    # Statistics serializers
    'AgeDistributionSerializer',
    'GenderDistributionSerializer',
    'RelationshipDistributionSerializer',
    'AreaDistributionSerializer',
    'MedicalConditionsStatsSerializer',
    'AccessibilityRequirementsStatsSerializer',
    'DietaryRequirementsStatsSerializer',
    'EmergencyContactStatsSerializer',
    'ConsentStatsSerializer',
    'AttendeeRegistrationTrendsSerializer',
    'AttendanceStatsSerializer',
    'PersonalInfoCombinedSerializer',
    'AttendeeOverviewStatsSerializer',
    'DemographicsSerializer',
    # Pre-removal serializers
    'PaymentBlockerItemSerializer',
    'TicketBlockerItemSerializer',
    'OrderBlockerItemSerializer',
    'AttendeePreRemovalBlockerItemSerializer',
    'AttendeePreRemovalBlockerPaginationSerializer',
    'AttendeePreRemovalBlockerSerializer',
    'AttendeePreRemovalRefundSummarySerializer',
    'AttendeePreRemovalSummarySerializer',
    # Bulk action serializers
    'BulkDeleteCheckInsSerializer',
    'BulkAttendeeStatusUpdateSerializer',
    'AttendeeStatusUpdateSerializer',
]
