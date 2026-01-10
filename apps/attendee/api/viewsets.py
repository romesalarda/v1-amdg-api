"""
ViewSets for the attendee app.

Provides comprehensive API endpoints for attendee management with HATEOAS,
nested resources, and proper schema documentation.
"""
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from django.utils import timezone

from apps.attendee.models import (
    Attendee, AttendeeGuardian, AttendeeAction,
    FamilyGroup, FamilyAttendee, AttendeeMessage,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    EmergencyContact, Consent, AttendeeConsent,
    EventAttendance, AttendeeOrganisation
)

from .serializers import (
    AttendeeListSerializer, AttendeeDetailSerializer,
    AttendeeCreateSerializer, AttendeeUpdateSerializer,
    AttendeeGuardianSerializer, AttendeeActionSerializer,
    FamilyGroupListSerializer, FamilyGroupDetailSerializer,
    FamilyGroupCreateUpdateSerializer, FamilyAttendeeSerializer,
    AttendeeMessageListSerializer, AttendeeMessageDetailSerializer,
    AttendeeMessageCreateSerializer, AttendeeMessageUpdateSerializer,
    AccessibilityRequirementSerializer, AttendeeAccessibilityRequirementSerializer,
    DietaryRequirementSerializer, AttendeeDietaryRequirementSerializer,
    MedicalConditionSerializer, AttendeeMedicalConditionSerializer,
    EmergencyContactSerializer, ConsentSerializer, AttendeeConsentSerializer,
    EventAttendanceSerializer, AttendeeOrganisationSerializer,
)

from .filtersets import (
    AttendeeFilterSet, AttendeeGuardianFilterSet, AttendeeActionFilterSet,
    FamilyGroupFilterSet, FamilyAttendeeFilterSet, AttendeeMessageFilterSet,
    AccessibilityRequirementFilterSet, AttendeeAccessibilityRequirementFilterSet,
    DietaryRequirementFilterSet, AttendeeDietaryRequirementFilterSet,
    MedicalConditionFilterSet, AttendeeMedicalConditionFilterSet,
    EmergencyContactFilterSet, ConsentFilterSet, AttendeeConsentFilterSet,
    EventAttendanceFilterSet, AttendeeOrganisationFilterSet,
)

from .permissions import (
    IsAttendeeOwnerOrStaff, IsAttendeeOwnerOrReadOnly,
    IsEventStaffOrReadOnly, CanManageAttendeePersonalInfo,
    CanAccessMessages, IsStaffOrReadOnly
)


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class NestedAttendeeViewSetMixin:
    """
    Mixin to filter queryset by attendee_id from nested URL.
    
    For use with nested URLs like: /attendees/{attendee_id}/resource/
    """
    
    def get_attendee(self):
        """Get the parent attendee from the URL."""
        attendee_id = self.kwargs.get('attendee_id')
        if attendee_id:
            return get_object_or_404(Attendee, attendee_id=attendee_id, deleted_at__isnull=True)
        return None
    
    def get_queryset(self):
        """Filter queryset by attendee from URL parameters."""
        queryset = super().get_queryset()
        attendee = self.get_attendee()
        if attendee:
            queryset = queryset.filter(attendee=attendee)
        return queryset
    
    def perform_create(self, serializer):
        """Automatically set attendee on create."""
        attendee = self.get_attendee()
        if attendee:
            serializer.save(attendee=attendee)
        else:
            serializer.save()


# ============================================================================
# ATTENDEE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List attendees",
        description="Retrieve a paginated list of attendees with advanced filtering and search",
        parameters=[
            OpenApiParameter('search', OpenApiTypes.STR, description='Search by name, email, phone, or ID'),
            OpenApiParameter('event', OpenApiTypes.UUID, description='Filter by event ID'),
            OpenApiParameter('age_min', OpenApiTypes.INT, description='Minimum age'),
            OpenApiParameter('age_max', OpenApiTypes.INT, description='Maximum age'),
            OpenApiParameter('is_minor', OpenApiTypes.BOOL, description='Filter minors (under 18)'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get attendee details",
        description="Retrieve detailed information about a specific attendee"
    ),
    create=extend_schema(
        summary="Create attendee",
        description="Create a new attendee record"
    ),
    update=extend_schema(
        summary="Update attendee",
        description="Update an existing attendee record"
    ),
    partial_update=extend_schema(
        summary="Partially update attendee",
        description="Partially update an existing attendee record"
    ),
    destroy=extend_schema(
        summary="Delete attendee",
        description="Soft delete an attendee record"
    )
)
class AttendeeViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Attendee records with nested resource support."""
    
    queryset = Attendee.objects.select_related(
        'event', 'user', 'area_from', 'booking', 'defined_by'
    ).prefetch_related(
        'emergency_contacts', 'organisations',
        'attendeedietaryrequirement__dietary_requirement',
        'attendeemedicalcondition__medical_condition',
        'attendeeaccessibilityrequirement__accessibility_requirement'
    )
    permission_classes = [IsAttendeeOwnerOrStaff]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AttendeeFilterSet
    search_fields = ['first_name', 'last_name', 'email', 'attendee_display_id']
    ordering_fields = ['created_at', 'first_name', 'last_name', 'date_of_birth']
    ordering = ['-created_at']
    lookup_field = 'attendee_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AttendeeListSerializer
        elif self.action in ['create']:
            return AttendeeCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AttendeeUpdateSerializer
        return AttendeeDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions and exclude soft-deleted by default."""
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()
        
        # Filter out soft-deleted attendees unless explicitly requested
        if not self.request.query_params.get('include_deleted'):
            queryset = queryset.filter(deleted_at__isnull=True)
        
        # Superusers and staff see all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see their own attendees and those they guard
        return queryset.filter(
            Q(user=user) |
            Q(guardians__user=user) |
            Q(event__staff_members__user=user)
        ).distinct()
    
    def perform_create(self, serializer):
        """Handle attendee creation with automatic user assignment for SELF relationship."""
        from apps.attendee.models import AttendeeRelationship
        
        relationship = serializer.validated_data.get('relationship_to_user')
        user_in_data = serializer.validated_data.get('user')
        
        # If creating a SELF attendee without explicit user (regular user flow)
        # Auto-assign the authenticated user
        if relationship == AttendeeRelationship.SELF and not user_in_data:
            if not (self.request.user.is_staff or self.request.user.is_superuser):
                # Regular users creating SELF attendees get auto-assigned
                serializer.save(user=self.request.user)
                return
        
        # Otherwise save normally (admin can specify user, or non-SELF relationships)
        serializer.save()
    
    def perform_destroy(self, instance):
        """Perform soft delete by setting deleted_at and deleted_by instead of hard delete."""
        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save(update_fields=['deleted_at', 'deleted_by'])


# ============================================================================
# ATTENDEE GUARDIAN VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List attendee guardians",
        description="Retrieve a list of guardian relationships"
    ),
    retrieve=extend_schema(
        summary="Get guardian details",
        description="Retrieve details of a specific guardian relationship"
    ),
    create=extend_schema(
        summary="Create guardian relationship",
        description="Create a new guardian relationship for an attendee"
    ),
    update=extend_schema(
        summary="Update guardian relationship",
        description="Update an existing guardian relationship"
    ),
    destroy=extend_schema(
        summary="Delete guardian relationship",
        description="Remove a guardian relationship"
    )
)
class AttendeeGuardianViewSet(viewsets.ModelViewSet):
    """ViewSet for managing AttendeeGuardian relationships."""
    
    queryset = AttendeeGuardian.objects.select_related('user', 'attendee').all()
    serializer_class = AttendeeGuardianSerializer
    permission_classes = [IsAttendeeOwnerOrStaff]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeGuardianFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']


# ============================================================================
# ATTENDEE ACTION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List attendee actions",
        description="Retrieve a list of actions performed on attendees"
    ),
    retrieve=extend_schema(
        summary="Get action details",
        description="Retrieve details of a specific attendee action"
    ),
    create=extend_schema(
        summary="Create attendee action",
        description="Log a new action performed on an attendee"
    )
)
class AttendeeActionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing AttendeeAction records."""
    
    queryset = AttendeeAction.objects.select_related('attendee', 'performed_by').all()
    serializer_class = AttendeeActionSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeActionFilterSet
    ordering_fields = ['performed_at']
    ordering = ['-performed_at']
    http_method_names = ['get', 'post', 'head', 'options']  # No update/delete


# ============================================================================
# FAMILY GROUP VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List family groups",
        description="Retrieve a list of family groups"
    ),
    retrieve=extend_schema(
        summary="Get family group details",
        description="Retrieve detailed information about a family group including members"
    ),
    create=extend_schema(
        summary="Create family group",
        description="Create a new family group"
    ),
    update=extend_schema(
        summary="Update family group",
        description="Update an existing family group"
    ),
    destroy=extend_schema(
        summary="Delete family group",
        description="Delete a family group"
    )
)
class FamilyGroupViewSet(viewsets.ModelViewSet):
    """ViewSet for managing FamilyGroup records."""
    
    queryset = FamilyGroup.objects.prefetch_related('family_attendees__attendee').all()
    permission_classes = [IsAttendeeOwnerOrStaff]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = FamilyGroupFilterSet
    search_fields = ['family_name']
    ordering_fields = ['created_at', 'family_name']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return FamilyGroupListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return FamilyGroupCreateUpdateSerializer
        return FamilyGroupDetailSerializer
    
    @extend_schema(
        summary="Get family group members",
        description="Retrieve all members of a family group",
        responses={200: FamilyAttendeeSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='members')
    def members(self, request, pk=None):
        """Get all members of a family group."""
        family_group = self.get_object()
        members = family_group.family_attendees.select_related('attendee').all()
        serializer = FamilyAttendeeSerializer(members, many=True, context={'request': request})
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="List family attendee relationships",
        description="Retrieve a list of family attendee memberships"
    ),
    retrieve=extend_schema(
        summary="Get family attendee details",
        description="Retrieve details of a specific family attendee membership"
    ),
    create=extend_schema(
        summary="Add attendee to family",
        description="Add an attendee to a family group"
    ),
    update=extend_schema(
        summary="Update family membership",
        description="Update a family attendee membership"
    ),
    destroy=extend_schema(
        summary="Remove attendee from family",
        description="Remove an attendee from a family group"
    )
)
class FamilyAttendeeViewSet(viewsets.ModelViewSet):
    """ViewSet for managing FamilyAttendee relationships."""
    
    queryset = FamilyAttendee.objects.select_related('family_group', 'attendee').all()
    serializer_class = FamilyAttendeeSerializer
    permission_classes = [IsAttendeeOwnerOrStaff]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = FamilyAttendeeFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']


# ============================================================================
# MESSAGE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List attendee messages",
        description="Retrieve a list of attendee messages"
    ),
    retrieve=extend_schema(
        summary="Get message details",
        description="Retrieve full details of a specific message"
    ),
    create=extend_schema(
        summary="Create message",
        description="Create a new attendee message"
    ),
    update=extend_schema(
        summary="Update message",
        description="Update a message (primarily for staff responses)"
    ),
    partial_update=extend_schema(
        summary="Partially update message",
        description="Partially update a message"
    )
)
class AttendeeMessageViewSet(viewsets.ModelViewSet):
    """ViewSet for managing AttendeeMessage records."""
    
    queryset = AttendeeMessage.objects.select_related('attendee', 'responsed_by').all()
    permission_classes = [CanAccessMessages]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeMessageFilterSet
    ordering_fields = ['submitted_at', 'priority']
    ordering = ['-submitted_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AttendeeMessageListSerializer
        elif self.action == 'create':
            return AttendeeMessageCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AttendeeMessageUpdateSerializer
        return AttendeeMessageDetailSerializer


# ============================================================================
# ACCESSIBILITY REQUIREMENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List accessibility requirements",
        description="Retrieve a list of available accessibility requirements"
    ),
    retrieve=extend_schema(
        summary="Get accessibility requirement details",
        description="Retrieve details of a specific accessibility requirement"
    ),
    create=extend_schema(
        summary="Create accessibility requirement",
        description="Create a new accessibility requirement type"
    ),
    update=extend_schema(
        summary="Update accessibility requirement",
        description="Update an existing accessibility requirement"
    )
)
class AccessibilityRequirementViewSet(viewsets.ModelViewSet):
    """ViewSet for managing AccessibilityRequirement types."""
    
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
        summary="List attendee accessibility requirements",
        description="Retrieve accessibility requirements assigned to attendees"
    ),
    retrieve=extend_schema(
        summary="Get attendee accessibility requirement details",
        description="Retrieve details of a specific attendee accessibility requirement"
    ),
    create=extend_schema(
        summary="Assign accessibility requirement",
        description="Assign an accessibility requirement to an attendee"
    ),
    update=extend_schema(
        summary="Update accessibility requirement assignment",
        description="Update an attendee's accessibility requirement"
    ),
    destroy=extend_schema(
        summary="Remove accessibility requirement",
        description="Remove an accessibility requirement from an attendee"
    )
)
class AttendeeAccessibilityRequirementViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """ViewSet for managing AttendeeAccessibilityRequirement assignments (nested under attendee)."""
    
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


# ============================================================================
# DIETARY REQUIREMENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List dietary requirements",
        description="Retrieve a list of available dietary requirements"
    ),
    retrieve=extend_schema(
        summary="Get dietary requirement details",
        description="Retrieve details of a specific dietary requirement"
    ),
    create=extend_schema(
        summary="Create dietary requirement",
        description="Create a new dietary requirement type"
    ),
    update=extend_schema(
        summary="Update dietary requirement",
        description="Update an existing dietary requirement"
    )
)
class DietaryRequirementViewSet(viewsets.ModelViewSet):
    """ViewSet for managing DietaryRequirement types."""
    
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
        summary="List attendee dietary requirements",
        description="Retrieve dietary requirements assigned to attendees"
    ),
    retrieve=extend_schema(
        summary="Get attendee dietary requirement details",
        description="Retrieve details of a specific attendee dietary requirement"
    ),
    create=extend_schema(
        summary="Assign dietary requirement",
        description="Assign a dietary requirement to an attendee"
    ),
    update=extend_schema(
        summary="Update dietary requirement assignment",
        description="Update an attendee's dietary requirement"
    ),
    destroy=extend_schema(
        summary="Remove dietary requirement",
        description="Remove a dietary requirement from an attendee"
    )
)
class AttendeeDietaryRequirementViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """ViewSet for managing AttendeeDietaryRequirement assignments (nested under attendee)."""
    
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


# ============================================================================
# MEDICAL CONDITION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List medical conditions",
        description="Retrieve a list of available medical conditions"
    ),
    retrieve=extend_schema(
        summary="Get medical condition details",
        description="Retrieve details of a specific medical condition"
    ),
    create=extend_schema(
        summary="Create medical condition",
        description="Create a new medical condition type"
    ),
    update=extend_schema(
        summary="Update medical condition",
        description="Update an existing medical condition"
    )
)
class MedicalConditionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing MedicalCondition types."""
    
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
        summary="List attendee medical conditions",
        description="Retrieve medical conditions assigned to attendees"
    ),
    retrieve=extend_schema(
        summary="Get attendee medical condition details",
        description="Retrieve details of a specific attendee medical condition"
    ),
    create=extend_schema(
        summary="Assign medical condition",
        description="Assign a medical condition to an attendee"
    ),
    update=extend_schema(
        summary="Update medical condition assignment",
        description="Update an attendee's medical condition"
    ),
    destroy=extend_schema(
        summary="Remove medical condition",
        description="Remove a medical condition from an attendee"
    )
)
class AttendeeMedicalConditionViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """ViewSet for managing AttendeeMedicalCondition assignments (nested under attendee)."""
    
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


# ============================================================================
# EMERGENCY CONTACT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List emergency contacts",
        description="Retrieve a list of emergency contacts"
    ),
    retrieve=extend_schema(
        summary="Get emergency contact details",
        description="Retrieve details of a specific emergency contact"
    ),
    create=extend_schema(
        summary="Create emergency contact",
        description="Create a new emergency contact for an attendee"
    ),
    update=extend_schema(
        summary="Update emergency contact",
        description="Update an existing emergency contact"
    ),
    destroy=extend_schema(
        summary="Delete emergency contact",
        description="Remove an emergency contact"
    )
)
class EmergencyContactViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """ViewSet for managing EmergencyContact records (nested under attendee)."""
    
    queryset = EmergencyContact.objects.select_related('attendee').all()
    serializer_class = EmergencyContactSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EmergencyContactFilterSet
    search_fields = ['first_name', 'last_name', 'phone_number', 'email']
    ordering_fields = ['added_at', 'primary_contact']
    ordering = ['-primary_contact', '-added_at']


# ============================================================================
# CONSENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List consents",
        description="Retrieve a list of available consents for events"
    ),
    retrieve=extend_schema(
        summary="Get consent details",
        description="Retrieve details of a specific consent"
    ),
    create=extend_schema(
        summary="Create consent",
        description="Create a new consent type for an event"
    ),
    update=extend_schema(
        summary="Update consent",
        description="Update an existing consent"
    )
)
class ConsentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Consent types."""
    
    queryset = Consent.objects.select_related('event').all()
    serializer_class = ConsentSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ConsentFilterSet
    search_fields = ['code', 'title', 'description']
    ordering_fields = ['title', 'created_at']
    ordering = ['title']


@extend_schema_view(
    list=extend_schema(
        summary="List attendee consents",
        description="Retrieve consent records for attendees"
    ),
    retrieve=extend_schema(
        summary="Get attendee consent details",
        description="Retrieve details of a specific attendee consent"
    ),
    create=extend_schema(
        summary="Record attendee consent",
        description="Record a consent for an attendee"
    ),
    update=extend_schema(
        summary="Update attendee consent",
        description="Update an attendee's consent record"
    ),
    destroy=extend_schema(
        summary="Remove consent record",
        description="Remove a consent record"
    )
)
class AttendeeConsentViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """ViewSet for managing AttendeeConsent records (nested under attendee)."""
    
    queryset = AttendeeConsent.objects.select_related('attendee', 'consent').all()
    serializer_class = AttendeeConsentSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeConsentFilterSet
    ordering_fields = ['recorded_at', 'given_at']
    ordering = ['-recorded_at']


# ============================================================================
# EVENT ATTENDANCE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List event attendances",
        description="Retrieve a list of event attendance records"
    ),
    retrieve=extend_schema(
        summary="Get attendance details",
        description="Retrieve details of a specific attendance record"
    ),
    create=extend_schema(
        summary="Create attendance record",
        description="Create a new attendance record"
    ),
    update=extend_schema(
        summary="Update attendance record",
        description="Update an attendance record (check-in/check-out)"
    )
)
class EventAttendanceViewSet(viewsets.ModelViewSet):
    """ViewSet for managing EventAttendance records."""
    
    queryset = EventAttendance.objects.select_related('event', 'attendee', 'check_in_by', 'check_out_by').all()
    serializer_class = EventAttendanceSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventAttendanceFilterSet
    ordering_fields = ['check_in_time', 'check_out_time']
    ordering = ['-check_in_time']


# ============================================================================
# ATTENDEE ORGANISATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List attendee organisations",
        description="Retrieve organisation associations for attendees"
    ),
    retrieve=extend_schema(
        summary="Get attendee organisation details",
        description="Retrieve details of a specific organisation association"
    ),
    create=extend_schema(
        summary="Link attendee to organisation",
        description="Link an attendee to an organisation"
    ),
    destroy=extend_schema(
        summary="Unlink attendee from organisation",
        description="Remove an organisation association"
    )
)
class AttendeeOrganisationViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """ViewSet for managing AttendeeOrganisation associations (nested under attendee)."""
    
    queryset = AttendeeOrganisation.objects.select_related('attendee', 'organisation').all()
    serializer_class = AttendeeOrganisationSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeOrganisationFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']  # No update
