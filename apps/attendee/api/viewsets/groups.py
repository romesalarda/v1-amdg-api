from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.attendee.models import AttendeeGuardian, FamilyGroup, FamilyAttendee

from apps.attendee.api.serializers import (
    FamilyGroupListSerializer, FamilyGroupDetailSerializer,
    FamilyGroupCreateUpdateSerializer, FamilyAttendeeSerializer, AttendeeGuardianSerializer
)

from apps.attendee.api.filtersets import AttendeeGuardianFilterSet,FamilyGroupFilterSet, FamilyAttendeeFilterSet
from apps.attendee.api.permissions import CanManageAttendeePersonalInfo, CanAccessFamilyInfo
from apps.common.pagination import StandardPagination


@extend_schema_view(
    list=extend_schema(
        summary="List Family Guardians",
        description=(
            "Retrieve a list of family guardians showing which users are designated as guardians for specific attendees. "
            "Guardians typically manage minors or dependents and have elevated permissions for those attendees."
        ),
        tags=['Family Guardians']
    ),
    retrieve=extend_schema(
        summary="Get Guardian Details",
        description=(
            "Retrieve details of a specific family guardian relationship including the user, attendee, and guardian role. "
            "Shows which attendees the guardian is responsible for and their permissions."
        ),
        tags=['Family Guardians']
    ),
    create=extend_schema(
        summary="Add Family Guardian",
        description=(
            "Designate a user as a guardian for an attendee. "
            "Guardians typically manage minors or dependents and have elevated permissions for those attendees."
        ),
        tags=['Family Guardians']
    ),  
    destroy=extend_schema(
        summary="Remove Family Guardian",
        description=(
            "Remove a guardian designation for an attendee. "
            "This does not delete the user or attendee record, only the guardian relationship."
        ),
        tags=['Family Guardians']
    )
)
class AttendeeGuardianViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeGuardian relationships.
    
    Handles the many-to-many relationship between users and attendees they are responsible for.
    Guardians typically manage minors or dependents and have elevated permissions for those attendees.
    """
    
    queryset = AttendeeGuardian.objects.select_related('user', 'attendee').all()
    serializer_class = AttendeeGuardianSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeGuardianFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        return queryset.filter(
            Q(user=user) |
            Q(attendee__user=user) |
            Q(attendee__guardians__user=user) |
            Q(attendee__event__staff_members__user=user)
        ).distinct()
    

@extend_schema_view(
    list=extend_schema(
        summary="List Family Groups",
        description=(
            "Retrieve a list of family groups with their associated members. "
            "Family groups organize attendees into related units for easier management and communication. "
            "Results include family name, creation details, and member count."
        ),
        tags=['Family Groups']
    ),
    retrieve=extend_schema(
        summary="Get Family Group Details",
        description=(
            "Retrieve comprehensive information about a specific family group including all members, "
            "their relationships within the family (parent, child, sibling, etc.), "
            "and primary guardian designations."
        ),
        tags=['Family Groups']
    ),
    create=extend_schema(
        summary="Create Family Group",
        description=(
            "Create a new family group to organize related attendees. "
            "Family groups facilitate bulk operations and communication with multiple attendees "
            "who share family relationships."
        ),
        tags=['Family Groups']
    ),
    update=extend_schema(
        summary="Update Family Group",
        description=(
            "Update family group information such as the family name or designation. "
            "Use member management endpoints to add or remove attendees from the group."
        ),
        tags=['Family Groups']
    ),
    partial_update=extend_schema(
        summary="Partially Update Family Group",
        description="Partially update family group information without providing complete payload.",
        tags=['Family Groups']
    ),
    destroy=extend_schema(
        summary="Delete Family Group",
        description=(
            "Delete a family group and remove all member associations. "
            "This does not delete the individual attendee records, only the grouping relationship."
        ),
        tags=['Family Groups']
    )
)
class FamilyGroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing FamilyGroup records.
    
    Family groups organize related attendees (family members) for easier management.
    Supports grouping attendees by family relationships and designating primary guardians.
    """
    
    queryset = FamilyGroup.objects.prefetch_related('family_attendees__attendee').all()
    permission_classes = [CanAccessFamilyInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = FamilyGroupFilterSet
    search_fields = ['family_name']
    ordering_fields = ['created_at', 'family_name']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        return queryset.filter(
            Q(created_by=user) |
            Q(family_attendees__attendee__user=user) |
            Q(family_attendees__attendee__guardians__user=user) |
            Q(family_attendees__attendee__event__staff_members__user=user)
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return FamilyGroupListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return FamilyGroupCreateUpdateSerializer
        return FamilyGroupDetailSerializer
    
    @extend_schema(
        summary="Get Family Group Members",
        description=(
            "Retrieve all members of a specific family group with their relationships and roles. "
            "Shows which attendees belong to the family and their relationships (parent, child, sibling, etc.), "
            "including primary guardian designations."
        ),
        tags=['Family Groups'],
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
        summary="List Family Attendee Memberships",
        description=(
            "Retrieve a list of family attendee memberships showing how attendees are associated with family groups. "
            "Includes relationship types (parent, child, sibling) and primary guardian status."
        ),
        tags=['Family Attendees']
    ),
    retrieve=extend_schema(
        summary="Get Family Membership Details",
        description=(
            "Retrieve details of a specific family attendee membership including "
            "the attendee, family group, relationship type, and whether they are designated as primary guardian."
        ),
        tags=['Family Attendees']
    ),
    create=extend_schema(
        summary="Add Attendee to Family",
        description=(
            "Add an attendee to a family group with a specified relationship (parent, child, sibling, spouse, etc.). "
            "Optionally designate them as the primary guardian for the family."
        ),
        tags=['Family Attendees']
    ),
    update=extend_schema(
        summary="Update Family Membership",
        description=(
            "Update a family attendee membership to change relationship type or primary guardian status."
        ),
        tags=['Family Attendees']
    ),
    partial_update=extend_schema(
        summary="Partially Update Family Membership",
        description="Partially update family membership details without providing complete payload.",
        tags=['Family Attendees']
    ),
    destroy=extend_schema(
        summary="Remove Attendee from Family",
        description=(
            "Remove an attendee from a family group. "
            "This does not delete the attendee record, only the family association."
        ),
        tags=['Family Attendees']
    )
)
class FamilyAttendeeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing FamilyAttendee relationships.
    
    Handles the many-to-many relationship between family groups and attendees,
    including relationship types and primary guardian designations.
    """
    
    queryset = FamilyAttendee.objects.select_related('family_group', 'attendee').all()
    serializer_class = FamilyAttendeeSerializer
    permission_classes = [CanAccessFamilyInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = FamilyAttendeeFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        return queryset.filter(
            Q(family_group__created_by=user) |
            Q(attendee__user=user) |
            Q(attendee__guardians__user=user) |
            Q(attendee__event__staff_members__user=user)
        ).distinct()