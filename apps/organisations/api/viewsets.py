"""
Production-grade viewsets for the organisations app.

Provides comprehensive viewsets for organisation management with proper validation,
business logic separation, schema configuration, and permission classes.

ViewSets:
    - OrganisationViewSet: Full CRUD for organisations
    - OrganisationContactViewSet: Manage organisation contacts
    - OrganisationControlViewSet: Manage organisation controllers
    - UserOrganisationMembershipViewSet: Handle membership with verification
    - OrganisationAcceptanceCodeViewSet: Manage acceptance codes
    - OrganisationInviteViewSet: Handle invitations
    - InvolvedEventOrganisationViewSet: Manage event involvement
    - EventSponsorViewSet: Handle event sponsors
    - EventSponsorPackageViewSet: Manage sponsorship packages
    - LeaderViewSet: Manage organisation leaders

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any

from apps.organisations.models import (
    Organisation, OrganisationContact, OrganisationControl,
    UserOrganisationMembership, OrganisationAcceptanceCode, OrganisationInvite,
    InvolvedEventOrganisation, EventSponsor, EventSponsorPackage,
    Leader
)
from .serializers import (
    OrganisationListSerializer, OrganisationDetailSerializer, OrganisationCreateUpdateSerializer,
    OrganisationContactSerializer, OrganisationContactCreateUpdateSerializer,
    OrganisationControlSerializer, OrganisationControlCreateUpdateSerializer,
    UserOrganisationMembershipListSerializer, UserOrganisationMembershipDetailSerializer, UserOrganisationMembershipCreateUpdateSerializer,
    OrganisationAcceptanceCodeSerializer, OrganisationAcceptanceCodeCreateUpdateSerializer,
    OrganisationInviteListSerializer, OrganisationInviteDetailSerializer, OrganisationInviteCreateUpdateSerializer,
    InvolvedEventOrganisationSerializer, InvolvedEventOrganisationCreateUpdateSerializer,
    EventSponsorListSerializer, EventSponsorDetailSerializer, EventSponsorCreateUpdateSerializer,
    EventSponsorPackageListSerializer, EventSponsorPackageDetailSerializer, EventSponsorPackageCreateUpdateSerializer,
    LeaderListSerializer, LeaderDetailSerializer, LeaderCreateUpdateSerializer
)
from .filtersets import (
    OrganisationFilterSet, OrganisationContactFilterSet, OrganisationControlFilterSet,
    UserOrganisationMembershipFilterSet, OrganisationAcceptanceCodeFilterSet, OrganisationInviteFilterSet,
    InvolvedEventOrganisationFilterSet, EventSponsorFilterSet, EventSponsorPackageFilterSet,
    LeaderFilterSet
)
from .permissions import (
    IsOrganisationController, IsOrganisationControllerOrEventAdmin,
    IsOrganisationMember, IsOrganisationRelated, IsReadOnly
)


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration for organisation endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================================
# ORGANISATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List organisations",
        description="Retrieve a paginated list of organisations with advanced filtering.",
        tags=["Organisations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve organisation details",
        description="Get detailed information about a specific organisation including contacts and statistics.",
        tags=["Organisations"],
    ),
    create=extend_schema(
        summary="Create organisation",
        description="Create a new organisation. User will be set as creator.",
        tags=["Organisations"],
    ),
    update=extend_schema(
        summary="Update organisation",
        description="Update organisation details. Requires controller access.",
        tags=["Organisations"],
    ),
    partial_update=extend_schema(
        summary="Partially update organisation",
        description="Partially update organisation details. Requires controller access.",
        tags=["Organisations"],
    ),
    destroy=extend_schema(
        summary="Delete organisation",
        description="Delete an organisation. Requires controller access.",
        tags=["Organisations"],
    ),
)
class OrganisationViewSet(viewsets.ModelViewSet):
    """ViewSet for Organisation CRUD operations."""
    
    queryset = Organisation.objects.select_related('created_by').prefetch_related(
        'contacts', 'memberships', 'controllers'
    )
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOrganisationControllerOrEventAdmin | IsReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrganisationFilterSet
    search_fields = ['title', 'description']
    ordering_fields = ['title', 'added_at', 'updated_at']
    ordering = ['title']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return OrganisationListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return OrganisationCreateUpdateSerializer
        return OrganisationDetailSerializer
    
    @extend_schema(
        summary="List organisation contacts",
        description="Get all contacts for a specific organisation.",
        responses={200: OrganisationContactSerializer(many=True)},
        tags=["Organisations"],
    )
    @action(detail=True, methods=['get'])
    def contacts(self, request, pk=None):
        """Get all contacts for an organisation."""
        organisation = self.get_object()
        contacts = organisation.contacts.all()
        serializer = OrganisationContactSerializer(
            contacts, many=True, context={'request': request}
        )
        return Response(serializer.data)
    
    @extend_schema(
        summary="List organisation memberships",
        description="Get all memberships for a specific organisation.",
        responses={200: UserOrganisationMembershipListSerializer(many=True)},
        tags=["Organisations"],
    )
    @action(detail=True, methods=['get'])
    def memberships(self, request, pk=None):
        """Get all memberships for an organisation."""
        organisation = self.get_object()
        memberships = organisation.memberships.select_related('user', 'added_by').all()
        serializer = UserOrganisationMembershipListSerializer(
            memberships, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================================
# ORGANISATION CONTACT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List organisation contacts",
        description="Retrieve a paginated list of organisation contacts.",
        tags=["Organisation Contacts"],
    ),
    retrieve=extend_schema(
        summary="Retrieve contact details",
        description="Get detailed information about a specific contact.",
        tags=["Organisation Contacts"],
    ),
    create=extend_schema(
        summary="Create contact",
        description="Create a new contact for an organisation.",
        tags=["Organisation Contacts"],
    ),
    update=extend_schema(
        summary="Update contact",
        description="Update contact details.",
        tags=["Organisation Contacts"],
    ),
    partial_update=extend_schema(
        summary="Partially update contact",
        description="Partially update contact details.",
        tags=["Organisation Contacts"],
    ),
    destroy=extend_schema(
        summary="Delete contact",
        description="Delete an organisation contact.",
        tags=["Organisation Contacts"],
    ),
)
class OrganisationContactViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganisationContact CRUD operations."""
    
    queryset = OrganisationContact.objects.select_related('organisation')
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrganisationContactFilterSet
    search_fields = ['name', 'email', 'phone', 'label']
    ordering_fields = ['name', 'added_at']
    ordering = ['name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return OrganisationContactCreateUpdateSerializer
        return OrganisationContactSerializer


# ============================================================================
# ORGANISATION CONTROL VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List organisation controls",
        description="Retrieve a list of organisation control assignments.",
        tags=["Organisation Controls"],
    ),
    retrieve=extend_schema(
        summary="Retrieve control details",
        description="Get detailed information about a control assignment.",
        tags=["Organisation Controls"],
    ),
    create=extend_schema(
        summary="Create control",
        description="Assign control of an organisation to a user.",
        tags=["Organisation Controls"],
    ),
    destroy=extend_schema(
        summary="Remove control",
        description="Remove control assignment from a user.",
        tags=["Organisation Controls"],
    ),
)
class OrganisationControlViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganisationControl CRUD operations."""
    
    queryset = OrganisationControl.objects.select_related(
        'organisation', 'user', 'added_by'
    )
    permission_classes = [permissions.IsAuthenticated, IsOrganisationController]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = OrganisationControlFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']  # No PUT/PATCH
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'create':
            return OrganisationControlCreateUpdateSerializer
        return OrganisationControlSerializer


# ============================================================================
# USER ORGANISATION MEMBERSHIP VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List organisation memberships",
        description="Retrieve a list of organisation memberships with verification status.",
        tags=["Organisation Memberships"],
    ),
    retrieve=extend_schema(
        summary="Retrieve membership details",
        description="Get detailed information about a membership.",
        tags=["Organisation Memberships"],
    ),
    create=extend_schema(
        summary="Create membership",
        description="Add a user as a member of an organisation.",
        tags=["Organisation Memberships"],
    ),
    destroy=extend_schema(
        summary="Remove membership",
        description="Remove a user's membership from an organisation.",
        tags=["Organisation Memberships"],
    ),
)
class UserOrganisationMembershipViewSet(viewsets.ModelViewSet):
    """ViewSet for UserOrganisationMembership with verification actions."""
    
    queryset = UserOrganisationMembership.objects.select_related(
        'organisation', 'user', 'added_by'
    )
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = UserOrganisationMembershipFilterSet
    ordering_fields = ['added_at', 'verified_at']
    ordering = ['-added_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return UserOrganisationMembershipListSerializer
        elif self.action == 'create':
            return UserOrganisationMembershipCreateUpdateSerializer
        return UserOrganisationMembershipDetailSerializer
    
    @extend_schema(
        summary="Verify membership with code",
        description="Verify a membership using an acceptance code.",
        request={'application/json': {'type': 'object', 'properties': {'code': {'type': 'string'}}}},
        responses={200: UserOrganisationMembershipDetailSerializer},
        tags=["Organisation Memberships"],
    )
    @action(detail=True, methods=['post'], url_path='verify-with-code')
    def verify_with_code(self, request, pk=None):
        """Verify membership using an acceptance code."""
        membership = self.get_object()
        code_value = request.data.get('code')
        
        if not code_value:
            return Response(
                {'error': 'Acceptance code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            acceptance_code = OrganisationAcceptanceCode.objects.get(
                organisation=membership.organisation,
                code=code_value.upper()
            )
            membership.verify_with_code(acceptance_code)
            serializer = self.get_serializer(membership)
            return Response(serializer.data)
        except OrganisationAcceptanceCode.DoesNotExist:
            return Response(
                {'error': 'Invalid acceptance code'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except DjangoValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @extend_schema(
        summary="Verify membership manually",
        description="Manually verify a membership (requires controller access).",
        request=None,
        responses={200: UserOrganisationMembershipDetailSerializer},
        tags=["Organisation Memberships"],
    )
    @action(detail=True, methods=['post'], url_path='verify-manually', permission_classes=[permissions.IsAuthenticated, IsOrganisationController])
    def verify_manually(self, request, pk=None):
        """Manually verify a membership."""
        membership = self.get_object()
        
        try:
            membership.verify_manually(verified_by=request.user)
            serializer = self.get_serializer(membership)
            return Response(serializer.data)
        except DjangoValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# ============================================================================
# ORGANISATION ACCEPTANCE CODE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List acceptance codes",
        description="Retrieve a list of organisation acceptance codes.",
        tags=["Organisation Acceptance Codes"],
    ),
    retrieve=extend_schema(
        summary="Retrieve code details",
        description="Get detailed information about an acceptance code.",
        tags=["Organisation Acceptance Codes"],
    ),
    create=extend_schema(
        summary="Create acceptance code",
        description="Create a new acceptance code for an organisation.",
        tags=["Organisation Acceptance Codes"],
    ),
    update=extend_schema(
        summary="Update acceptance code",
        description="Update acceptance code details.",
        tags=["Organisation Acceptance Codes"],
    ),
    partial_update=extend_schema(
        summary="Partially update code",
        description="Partially update acceptance code details.",
        tags=["Organisation Acceptance Codes"],
    ),
    destroy=extend_schema(
        summary="Delete acceptance code",
        description="Delete an acceptance code.",
        tags=["Organisation Acceptance Codes"],
    ),
)
class OrganisationAcceptanceCodeViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganisationAcceptanceCode CRUD operations."""
    
    queryset = OrganisationAcceptanceCode.objects.select_related(
        'organisation', 'added_by'
    )
    permission_classes = [permissions.IsAuthenticated, IsOrganisationController]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = OrganisationAcceptanceCodeFilterSet
    ordering_fields = ['added_at', 'expires_at', 'uses']
    ordering = ['-added_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return OrganisationAcceptanceCodeCreateUpdateSerializer
        return OrganisationAcceptanceCodeSerializer


# ============================================================================
# ORGANISATION INVITE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List organisation invites",
        description="Retrieve a list of organisation invites.",
        tags=["Organisation Invites"],
    ),
    retrieve=extend_schema(
        summary="Retrieve invite details",
        description="Get detailed information about an invite.",
        tags=["Organisation Invites"],
    ),
    create=extend_schema(
        summary="Create invite",
        description="Create a new invite for a user to join an organisation.",
        tags=["Organisation Invites"],
    ),
    update=extend_schema(
        summary="Update invite",
        description="Update invite details.",
        tags=["Organisation Invites"],
    ),
    partial_update=extend_schema(
        summary="Partially update invite",
        description="Partially update invite details.",
        tags=["Organisation Invites"],
    ),
    destroy=extend_schema(
        summary="Delete invite",
        description="Delete an organisation invite.",
        tags=["Organisation Invites"],
    ),
)
class OrganisationInviteViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganisationInvite with accept action."""
    
    queryset = OrganisationInvite.objects.select_related(
        'organisation', 'target_user', 'invited_by'
    )
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = OrganisationInviteFilterSet
    ordering_fields = ['added_at', 'accepted_at', 'expires_at']
    ordering = ['-added_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return OrganisationInviteListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return OrganisationInviteCreateUpdateSerializer
        return OrganisationInviteDetailSerializer
    
    @extend_schema(
        summary="Accept invite",
        description="Accept an organisation invite and create membership.",
        request=None,
        responses={200: OrganisationInviteDetailSerializer},
        tags=["Organisation Invites"],
    )
    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """Accept an invite and create membership."""
        invite = self.get_object()
        
        # Check if user is the target user
        if invite.target_user != request.user:
            return Response(
                {'error': 'You can only accept invites sent to you'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not invite.is_valid:
            return Response(
                {'error': 'This invite is not valid'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Create or get membership
            membership, created = UserOrganisationMembership.objects.get_or_create(
                organisation=invite.organisation,
                user=invite.target_user,
                defaults={'added_by': invite.invited_by}
            )
            
            # Verify membership with invite (this also accepts the invite)
            if created or not membership.verified_at:
                membership.verify_with_invite(invite)
            else:
                # If membership already verified, just mark invite as accepted
                invite.accept_invite()
            
            serializer = self.get_serializer(invite)
            return Response(serializer.data)
        except DjangoValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# ============================================================================
# INVOLVED EVENT ORGANISATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List event organisation involvements",
        description="Retrieve a list of organisation involvements in events.",
        tags=["Event Organisation Involvement"],
    ),
    retrieve=extend_schema(
        summary="Retrieve involvement details",
        description="Get detailed information about an involvement.",
        tags=["Event Organisation Involvement"],
    ),
    create=extend_schema(
        summary="Create involvement",
        description="Add an organisation to an event with a specific role.",
        tags=["Event Organisation Involvement"],
    ),
    update=extend_schema(
        summary="Update involvement",
        description="Update involvement details.",
        tags=["Event Organisation Involvement"],
    ),
    partial_update=extend_schema(
        summary="Partially update involvement",
        description="Partially update involvement details.",
        tags=["Event Organisation Involvement"],
    ),
    destroy=extend_schema(
        summary="Remove involvement",
        description="Remove an organisation's involvement in an event.",
        tags=["Event Organisation Involvement"],
    ),
)
class InvolvedEventOrganisationViewSet(viewsets.ModelViewSet):
    """ViewSet for InvolvedEventOrganisation CRUD operations."""
    
    queryset = InvolvedEventOrganisation.objects.select_related(
        'organisation', 'event', 'added_by'
    )
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = InvolvedEventOrganisationFilterSet
    ordering_fields = ['added_at', 'role']
    ordering = ['-added_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return InvolvedEventOrganisationCreateUpdateSerializer
        return InvolvedEventOrganisationSerializer


# ============================================================================
# EVENT SPONSOR VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List event sponsors",
        description="Retrieve a list of event sponsors.",
        tags=["Event Sponsors"],
    ),
    retrieve=extend_schema(
        summary="Retrieve sponsor details",
        description="Get detailed information about an event sponsor including packages.",
        tags=["Event Sponsors"],
    ),
    create=extend_schema(
        summary="Create sponsor",
        description="Create a new event sponsor.",
        tags=["Event Sponsors"],
    ),
    update=extend_schema(
        summary="Update sponsor",
        description="Update sponsor details.",
        tags=["Event Sponsors"],
    ),
    partial_update=extend_schema(
        summary="Partially update sponsor",
        description="Partially update sponsor details.",
        tags=["Event Sponsors"],
    ),
    destroy=extend_schema(
        summary="Delete sponsor",
        description="Delete an event sponsor.",
        tags=["Event Sponsors"],
    ),
)
class EventSponsorViewSet(viewsets.ModelViewSet):
    """ViewSet for EventSponsor CRUD operations."""
    
    queryset = EventSponsor.objects.select_related(
        'organisation', 'event', 'added_by'
    ).prefetch_related('sponsorship_packages')
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'added_at']
    ordering = ['-added_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventSponsorListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventSponsorCreateUpdateSerializer
        return EventSponsorDetailSerializer
    
    @extend_schema(
        summary="List sponsor packages",
        description="Get all sponsorship packages for a specific sponsor.",
        responses={200: EventSponsorPackageListSerializer(many=True)},
        tags=["Event Sponsors"],
    )
    @action(detail=True, methods=['get'])
    def packages(self, request, pk=None):
        """Get all packages for a sponsor."""
        sponsor = self.get_object()
        packages = sponsor.sponsorship_packages.all()
        serializer = EventSponsorPackageListSerializer(
            packages, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================================
# EVENT SPONSOR PACKAGE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List sponsor packages",
        description="Retrieve a list of sponsorship packages with payment info.",
        tags=["Sponsorship Packages"],
    ),
    retrieve=extend_schema(
        summary="Retrieve package details",
        description="Get detailed information about a sponsorship package including payment.",
        tags=["Sponsorship Packages"],
    ),
    create=extend_schema(
        summary="Create package",
        description="Create a new sponsorship package.",
        tags=["Sponsorship Packages"],
    ),
    update=extend_schema(
        summary="Update package",
        description="Update package details.",
        tags=["Sponsorship Packages"],
    ),
    partial_update=extend_schema(
        summary="Partially update package",
        description="Partially update package details.",
        tags=["Sponsorship Packages"],
    ),
    destroy=extend_schema(
        summary="Delete package",
        description="Delete a sponsorship package.",
        tags=["Sponsorship Packages"],
    ),
)
class EventSponsorPackageViewSet(viewsets.ModelViewSet):
    """ViewSet for EventSponsorPackage with PayableModel support."""
    
    queryset = EventSponsorPackage.objects.select_related(
        'sponsor', 'event'
    )
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorPackageFilterSet
    search_fields = ['package_name', 'package_description']
    ordering_fields = ['package_name', 'added_at', 'base_amount']
    ordering = ['-added_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventSponsorPackageListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventSponsorPackageCreateUpdateSerializer
        return EventSponsorPackageDetailSerializer


# ============================================================================
# LEADER VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List leaders",
        description=(
            "Retrieve a list of leaders across organisations and locations. "
            "Leaders can be assigned to organisations, countries, clusters, chapters, or areas. "
            "All leaders must belong to an organisation for grouping purposes. "
            "Supports filtering by organisation, authority type, and user."
        ),
        tags=["Organisation Leaders"],
        parameters=[
            OpenApiParameter(name='user', type=OpenApiTypes.INT, description='Filter by user ID'),
            OpenApiParameter(name='organisation', type=OpenApiTypes.INT, description='Filter by organisation ID'),
            OpenApiParameter(name='authority_type', type=OpenApiTypes.STR, description='Filter by authority type (country, cluster, chapter, area, organisation)'),
            OpenApiParameter(name='authority_id', type=OpenApiTypes.INT, description='Filter by authority object ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Retrieve leader details",
        description=(
            "Get detailed information about a specific leader assignment including "
            "user details, organisation membership, authority object, and assignment metadata."
        ),
        tags=["Organisation Leaders"],
    ),
    create=extend_schema(
        summary="Create leader",
        description=(
            "Assign a user as a leader of an organisation. "
            "Leaders must belong to an organisation for grouping. "
            "Use location-specific endpoints to assign leaders to countries, clusters, chapters, or areas. "
            "Requires organisation controller permissions."
        ),
        tags=["Organisation Leaders"],
    ),
    update=extend_schema(
        summary="Update leader",
        description=(
            "Update leader details such as notes. "
            "Authority assignment (target_type and target_id) cannot be changed after creation. "
            "Requires organisation controller permissions."
        ),
        tags=["Organisation Leaders"],
    ),
    partial_update=extend_schema(
        summary="Partially update leader",
        description=(
            "Partially update leader details such as notes. "
            "Authority assignment cannot be changed after creation. "
            "Requires organisation controller permissions."
        ),
        tags=["Organisation Leaders"],
    ),
    destroy=extend_schema(
        summary="Remove leader",
        description=(
            "Remove a user's leadership assignment. "
            "This permanently removes the leadership relationship. "
            "Requires organisation controller permissions."
        ),
        tags=["Organisation Leaders"],
    ),
)
class LeaderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Leader CRUD operations supporting multiple authority types.
    
    Leaders can be assigned to:
    - Organisations (via this endpoint)
    - Countries, Clusters, Chapters, Areas (via location-specific endpoints)
    
    All leaders must belong to an organisation for grouping and permission purposes.
    """
    
    queryset = Leader.objects.select_related(
        'user', 'organisation', 'added_by', 'target_type'
    ).all()
    permission_classes = [permissions.IsAuthenticated, IsOrganisationController]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = LeaderFilterSet
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'organisation__title']
    ordering_fields = ['added_at', 'updated_at']
    ordering = ['-added_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return LeaderListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return LeaderCreateUpdateSerializer
        return LeaderDetailSerializer
