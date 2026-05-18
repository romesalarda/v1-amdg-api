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
import uuid

from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Q, Prefetch, Count, Sum
from django.http import Http404
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any
from uuid import UUID

from apps.organisations.models import (
    Organisation, OrganisationContact, OrganisationControl,
    UserOrganisationMembership, OrganisationAcceptanceCode, OrganisationInvite,
    InvolvedEventOrganisation, EventSponsor, EventSponsorPackage, EventSponsorInvite,
    Leader, LeaderLocationType, LocationLeaderInvite
)
from apps.events.models import Event
from apps.payments.models import Payment, PaymentMethod, PaymentMethodTypeChoices, PaymentStatusChoices
from apps.utils.querying import get_organisation_or_url_safe_title
from .serializers import (
    OrganisationListSerializer, OrganisationDetailSerializer, OrganisationCreateUpdateSerializer,
    OrganisationContactSerializer, OrganisationContactCreateUpdateSerializer,
    OrganisationControlSerializer, OrganisationControlCreateUpdateSerializer,
    UserOrganisationMembershipListSerializer, UserOrganisationMembershipDetailSerializer, UserOrganisationMembershipCreateUpdateSerializer,
    OrganisationAcceptanceCodeSerializer, OrganisationAcceptanceCodeCreateUpdateSerializer,
    OrganisationInviteListSerializer, OrganisationInviteDetailSerializer, OrganisationInviteCreateUpdateSerializer,
    InvolvedEventOrganisationSerializer, InvolvedEventOrganisationCreateUpdateSerializer,
    EventSponsorListSerializer, EventSponsorDetailSerializer, EventSponsorCreateUpdateSerializer,
    EventSponsorLedgerSerializer,
    EventSponsorPackageListSerializer, EventSponsorPackageDetailSerializer, EventSponsorPackageCreateUpdateSerializer,
    EventSponsorInviteListSerializer, EventSponsorInviteDetailSerializer, EventSponsorInviteCreateUpdateSerializer,
    EventSponsorCheckoutSerializer, SponsorshipPaymentHistorySerializer,
    LeaderListSerializer, LeaderDetailSerializer, LeaderCreateUpdateSerializer,
    LocationLeaderInviteListSerializer, LocationLeaderInviteDetailSerializer, LocationLeaderInviteCreateUpdateSerializer
)
from .filtersets import (
    OrganisationFilterSet, OrganisationContactFilterSet, OrganisationControlFilterSet,
    UserOrganisationMembershipFilterSet, OrganisationAcceptanceCodeFilterSet, OrganisationInviteFilterSet,
    InvolvedEventOrganisationFilterSet, EventSponsorFilterSet, EventSponsorPackageFilterSet,
    EventSponsorInviteFilterSet,
    LeaderFilterSet, LocationLeaderInviteFilterSet
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
    lookup_field = 'url_safe_title'
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOrganisationControllerOrEventAdmin | IsReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrganisationFilterSet
    search_fields = ['title', 'description']
    ordering_fields = ['title', 'added_at', 'updated_at']
    ordering = ['title']

    def get_object(self):
        lookup_value = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        organisation = get_organisation_or_url_safe_title(lookup_value)
        self.check_object_permissions(self.request, organisation)
        return organisation
    
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
    def contacts(self, request, url_safe_title=None, pk=None):
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
    def memberships(self, request, url_safe_title=None, pk=None):
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
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = UserOrganisationMembershipFilterSet
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name']
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
        'organisation', 'event', 'added_by', 'verified_by', 'processed_by', 'package'
    ).order_by('-added_at')
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'added_at']
    ordering = ['-added_at']
    lookup_field = 'sponsor_id'

    def _get_organisation_for_sponsor_lists(self, request):
        organisation_id = request.query_params.get('organisation_id') or request.query_params.get('organisation')
        if not organisation_id:
            return None, Response({'organisation_id': ['organisation_id is required.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            organisation = get_organisation_or_url_safe_title(organisation_id)
        except Http404:
            return None, Response({'organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        is_org_controller = request.user.is_superuser or request.user.is_staff or OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user,
        ).exists()
        if not is_org_controller:
            return None, Response(
                {'error': 'You must control this organisation to view sponsors.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return organisation, None

    def _apply_sponsor_list_filters(self, queryset, request):
        event_id = request.query_params.get('event_id')
        if event_id:
            try:
                UUID(event_id)
            except ValueError:
                return None, Response({'event_id': ['event_id must be a valid UUID.']}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(event__event_id=event_id)

        sponsor_org_id = request.query_params.get('sponsor_organisation_id')
        if sponsor_org_id:
            try:
                queryset = queryset.filter(organisation=get_organisation_or_url_safe_title(sponsor_org_id))
            except Http404:
                return None, Response({'sponsor_organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        event_org_id = request.query_params.get('event_organisation_id')
        if event_org_id:
            try:
                queryset = queryset.filter(event__organisation=get_organisation_or_url_safe_title(event_org_id))
            except Http404:
                return None, Response({'event_organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        return queryset, None

    def _build_payment_map(self, sponsors):
        sponsor_ids = [str(sponsor.id) for sponsor in sponsors]
        if not sponsor_ids:
            return {}

        sponsor_type = ContentType.objects.get_for_model(EventSponsor)
        payments = Payment.objects.filter(
            target_type=sponsor_type,
            target_id__in=sponsor_ids,
        ).order_by('-created_at')

        payment_map = {}
        for payment in payments:
            try:
                sponsor_id = int(payment.target_id)
            except (TypeError, ValueError):
                continue
            if sponsor_id not in payment_map:
                payment_map[sponsor_id] = payment
        return payment_map
    
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
    def packages(self, request, sponsor_id=None):
        """Get package selected by the sponsor, if any."""
        sponsor = self.get_object()
        packages = [sponsor.package] if sponsor.package else []
        serializer = EventSponsorPackageListSerializer(
            packages, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @extend_schema(
        summary="Inbound sponsors list",
        description=(
            "List organisations sponsoring events owned by the specified organisation."
        ),
        tags=["Event Sponsors"],
        parameters=[
            OpenApiParameter(name='organisation_id', type=OpenApiTypes.STR, required=True, description='Organisation id or url_safe_title.'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.UUID, required=False, description='Event public UUID.'),
            OpenApiParameter(name='sponsor_organisation_id', type=OpenApiTypes.STR, required=False, description='Sponsor organisation id or url_safe_title.'),
        ],
        responses={200: EventSponsorLedgerSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='inbound')
    def inbound(self, request):
        organisation, error_response = self._get_organisation_for_sponsor_lists(request)
        if error_response:
            return error_response

        queryset = self.get_queryset().filter(event__organisation_id=organisation.id).order_by('-added_at')
        queryset, filter_error = self._apply_sponsor_list_filters(queryset, request)
        if filter_error:
            return filter_error

        page = self.paginate_queryset(queryset)
        if page is not None:
            payment_map = self._build_payment_map(page)
            serializer = EventSponsorLedgerSerializer(
                page,
                many=True,
                context={'request': request, 'payment_map': payment_map},
            )
            return self.get_paginated_response(serializer.data)

        payment_map = self._build_payment_map(queryset)
        serializer = EventSponsorLedgerSerializer(
            queryset,
            many=True,
            context={'request': request, 'payment_map': payment_map},
        )
        return Response(serializer.data)

    @extend_schema(
        summary="Outbound sponsors list",
        description=(
            "List events that the specified organisation is sponsoring."
        ),
        tags=["Event Sponsors"],
        parameters=[
            OpenApiParameter(name='organisation_id', type=OpenApiTypes.STR, required=True, description='Organisation id or url_safe_title.'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.UUID, required=False, description='Event public UUID.'),
            OpenApiParameter(name='event_organisation_id', type=OpenApiTypes.STR, required=False, description='Event organisation id or url_safe_title.'),
        ],
        responses={200: EventSponsorLedgerSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='outbound')
    def outbound(self, request):
        organisation, error_response = self._get_organisation_for_sponsor_lists(request)
        if error_response:
            return error_response

        queryset = self.get_queryset().filter(organisation_id=organisation.id).order_by('-added_at')
        queryset, filter_error = self._apply_sponsor_list_filters(queryset, request)
        if filter_error:
            return filter_error

        page = self.paginate_queryset(queryset)
        if page is not None:
            payment_map = self._build_payment_map(page)
            serializer = EventSponsorLedgerSerializer(
                page,
                many=True,
                context={'request': request, 'payment_map': payment_map},
            )
            return self.get_paginated_response(serializer.data)

        payment_map = self._build_payment_map(queryset)
        serializer = EventSponsorLedgerSerializer(
            queryset,
            many=True,
            context={'request': request, 'payment_map': payment_map},
        )
        return Response(serializer.data)

    @extend_schema(
        summary="Sponsor checkout",
        description=(
            "Create a provisional sponsor commitment and initialize payment. "
            "Supports direct authenticated controller flow and invite-token assisted flow."
        ),
        request=EventSponsorCheckoutSerializer,
        tags=["Event Sponsors"],
    )
    @action(detail=False, methods=['post'], url_path='checkout', permission_classes=[permissions.IsAuthenticated])
    def checkout(self, request):
        serializer = EventSponsorCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        invite = None
        if data.get('invite_token'):
            try:
                invite = EventSponsorInvite.objects.select_related(
                    'event', 'organisation', 'chapter_location'
                ).get(token=data['invite_token'])
            except EventSponsorInvite.DoesNotExist:
                return Response({'error': 'Invalid invite token.'}, status=status.HTTP_404_NOT_FOUND)

            if not invite.is_valid:
                return Response({'error': 'Invite is no longer valid.'}, status=status.HTTP_400_BAD_REQUEST)

        event = None
        if invite:
            event = invite.event
            payload_event_id = data.get('event_id')
            if payload_event_id and str(payload_event_id) != str(event.event_id):
                return Response({'event_id': ['event_id does not match invite token event.']}, status=status.HTTP_400_BAD_REQUEST)
        else:
            event_id = data.get('event_id')
            if not event_id:
                return Response({'event_id': ['event_id is required when invite_token is not provided.']}, status=status.HTTP_400_BAD_REQUEST)
            try:
                event = Event.objects.get(event_id=event_id)
            except Event.DoesNotExist:
                return Response({'event_id': ['Event not found.']}, status=status.HTTP_404_NOT_FOUND)

        settings_obj = getattr(event, 'settings', None)
        if settings_obj and not settings_obj.accepting_sponsorships_enabled:
            return Response({'error': 'Sponsorships are not enabled for this event.'}, status=status.HTTP_400_BAD_REQUEST)
        if settings_obj and settings_obj.requires_invite_acceptance_for_checkout and not invite:
            return Response(
                {'error': 'This event requires sponsorship invite acceptance before checkout.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            package = EventSponsorPackage.objects.get(package_id=data['package_id'])
        except EventSponsorPackage.DoesNotExist:
            return Response({'package_id': ['Package not found.']}, status=status.HTTP_404_NOT_FOUND)

        if package.event_id != event.id:
            return Response({'package_id': ['Selected package does not belong to the selected event.']}, status=status.HTTP_400_BAD_REQUEST)

        if not package.active:
            return Response({'package_id': ['Selected package is not active.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment_method = PaymentMethod.objects.get(pk=data['payment_method_id'])
        except PaymentMethod.DoesNotExist:
            return Response({'payment_method_id': ['Payment method not found.']}, status=status.HTTP_404_NOT_FOUND)

        if payment_method.event_id != event.id:
            return Response({'payment_method_id': ['Payment method does not belong to the selected event.']}, status=status.HTTP_400_BAD_REQUEST)

        if not payment_method.is_active:
            return Response({'payment_method_id': ['Payment method is not active.']}, status=status.HTTP_400_BAD_REQUEST)

        organisation = None
        if invite and invite.organisation_id:
            organisation = invite.organisation
        elif data.get('organisation_id'):
            try:
                organisation = Organisation.objects.get(pk=data['organisation_id'])
            except Organisation.DoesNotExist:
                return Response({'organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        if organisation is None:
            return Response({'organisation_id': ['Unable to resolve organisation for this checkout.']}, status=status.HTTP_400_BAD_REQUEST)

        is_org_controller = request.user.is_superuser or request.user.is_staff or OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user,
        ).exists()
        if not is_org_controller:
            return Response({'error': 'You must control this organisation to checkout sponsorship.'}, status=status.HTTP_403_FORBIDDEN)

        chapter_location = invite.chapter_location if invite and invite.chapter_location_id else None
        if data.get('chapter_location'):
            from apps.locations.models import ChapterLocation
            try:
                chapter_location = ChapterLocation.objects.get(pk=data['chapter_location'])
            except ChapterLocation.DoesNotExist:
                return Response({'chapter_location': ['Chapter location not found.']}, status=status.HTTP_404_NOT_FOUND)

        if EventSponsor.objects.filter(
            event=event,
            organisation=organisation,
            chapter_location=chapter_location,
        ).exists():
            return Response({'error': 'This organisation is already sponsoring the event for this location.'}, status=status.HTTP_409_CONFLICT)

        sponsor_name = (data.get('name') or organisation.title).strip()
        if not sponsor_name:
            return Response({'name': ['Sponsor name cannot be empty.']}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            sponsor = EventSponsor.objects.create(
                name=sponsor_name,
                description=data.get('description', ''),
                organisation=organisation,
                event=event,
                package=package,
                chapter_location=chapter_location,
                added_by=request.user,
            )

            payment = Payment.objects.create(
                user=request.user,
                event=event,
                method=payment_method,
                base_amount=package.modified_amount,
                description=f"Sponsorship payment for {event.title} ({package.package_name})",
                target_type=ContentType.objects.get_for_model(EventSponsor),
                target_id=str(sponsor.pk),
                status=PaymentStatusChoices.DRAFTING,
            )
            payment.transition_to(PaymentStatusChoices.PENDING)

            response_data = {
                'sponsor_id': str(sponsor.sponsor_id),
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'payment_status': payment.status,
                'payment_method_type': payment_method.method_type,
            }

            if payment_method.method_type == PaymentMethodTypeChoices.STRIPE:
                from apps.payments.services.stripe.payment_intents import PaymentIntentService
                from apps.payments.services.stripe.client import StripeClient
                from apps.payments.services.stripe.exceptions import StripeServiceError

                try:
                    stripe_account_id = payment_method.get_stripe_account_id()
                    if not stripe_account_id:
                        use_platform = bool((payment_method.provided_details or {}).get('use_platform_account'))
                        if not use_platform:
                            raise DjangoValidationError(
                                "This Stripe payment method has no connected account configured. "
                                "Please contact the event organiser."
                            )
                    payment_intent = PaymentIntentService.create(
                        amount=payment.base_amount,
                        currency=payment.base_amount.currency.code,
                        payment_reference=payment.payment_reference,
                        metadata=payment.prepare_stripe_metadata(),
                        customer_email=payment.user.email,
                        customer_id=payment.stripe_customer_id,
                        description=f"Sponsorship payment for {event.title}",
                        stripe_account_id=stripe_account_id,
                    )
                    payment.stripe_payment_intent = payment_intent.id
                    payment.save(update_fields=['stripe_payment_intent', 'updated_at'])
                    response_data.update({
                        'client_secret': payment_intent.client_secret,
                        'payment_intent_id': payment_intent.id,
                        'publishable_key': StripeClient.get_publishable_key(),
                    })
                except StripeServiceError as exc:
                    raise DjangoValidationError(f"Unable to initialize Stripe payment: {exc.user_message}")
            elif payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
                response_data.update({
                    'bank_transfer_reference': payment.bank_transfer_reference,
                    'payment_instructions': payment_method.provided_details or {},
                })

            if invite:
                invite.accepted = True
                invite.declined = False
                invite.responded_at = timezone.now()
                invite.save(update_fields=['accepted', 'declined', 'responded_at'])

        return Response(response_data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Sponsorship payment history",
        description=(
            "Get sponsorship payment summary and timeline for an organisation and event pair. "
            "Only organisation controllers or staff can access this endpoint."
        ),
        tags=["Event Sponsors"],
        parameters=[
            OpenApiParameter(name='organisation_id', type=OpenApiTypes.INT, required=True, description='Organisation ID.'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.UUID, required=True, description='Event public UUID.'),
        ],
        responses={200: SponsorshipPaymentHistorySerializer},
    )
    @action(detail=False, methods=['get'], url_path='payment-history', permission_classes=[permissions.IsAuthenticated])
    def payment_history(self, request):
        organisation_id = request.query_params.get('organisation_id')
        event_id = request.query_params.get('event_id')

        if not organisation_id:
            return Response({'organisation_id': ['organisation_id is required.']}, status=status.HTTP_400_BAD_REQUEST)
        if not event_id:
            return Response({'event_id': ['event_id is required.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            organisation = get_organisation_or_url_safe_title(organisation_id)
        except Http404:
            return Response({'organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            event = Event.objects.get(event_id=event_id)
        except Event.DoesNotExist:
            return Response({'event_id': ['Event not found.']}, status=status.HTTP_404_NOT_FOUND)

        is_org_controller = request.user.is_superuser or request.user.is_staff or OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user,
        ).exists()
        if not is_org_controller:
            return Response(
                {'error': 'You must control this organisation to view sponsorship payments.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        sponsor_ids = list(
            EventSponsor.objects.filter(
                organisation=organisation,
                event=event,
            ).values_list('id', flat=True)
        )

        if not sponsor_ids:
            data = {
                'event_id': event.event_id,
                'event_title': event.title,
                'organisation_id': organisation.id,
                'organisation_title': organisation.title,
                'summary': {
                    'total_payments': 0,
                    'completed_payments': 0,
                    'pending_payments': 0,
                    'failed_payments': 0,
                    'cancelled_payments': 0,
                    'total_completed_amount': '0.00',
                    'currency': 'GBP',
                },
                'timeline': [],
            }
            serializer = SponsorshipPaymentHistorySerializer(data)
            return Response(serializer.data)

        sponsor_content_type = ContentType.objects.get_for_model(EventSponsor)
        payment_queryset = Payment.objects.select_related('method').filter(
            target_type=sponsor_content_type,
            target_id__in=[str(sponsor_id) for sponsor_id in sponsor_ids],
            event=event,
        ).order_by('-created_at')

        aggregates = payment_queryset.aggregate(
            total_payments=Count('id'),
            completed_payments=Count('id', filter=Q(status=PaymentStatusChoices.COMPLETED)),
            pending_payments=Count('id', filter=Q(status=PaymentStatusChoices.PENDING)),
            failed_payments=Count('id', filter=Q(status=PaymentStatusChoices.FAILED)),
            cancelled_payments=Count('id', filter=Q(status=PaymentStatusChoices.CANCELLED)),
            total_completed_amount=Sum('base_amount', filter=Q(status=PaymentStatusChoices.COMPLETED)),
        )

        total_completed_amount = aggregates.get('total_completed_amount')
        if total_completed_amount is None:
            total_completed_amount_value = '0.00'
            currency = 'GBP'
        else:
            total_completed_amount_value = str(getattr(total_completed_amount, 'amount', total_completed_amount))
            currency = str(getattr(total_completed_amount, 'currency', 'GBP'))


        timeline = [
            {
                'payment_id': payment.payment_id,
                'payment_reference': payment.payment_reference,
                'status': payment.status,
                'amount': str(payment.base_amount.amount) if payment.base_amount else '0.00',
                'currency': str(payment.base_amount.currency) if payment.base_amount else currency,
                'method_type': payment.method.method_type if payment.method else None,
                'method_title': payment.method.title if payment.method else None,
                'method_provided_details': payment.method.provided_details if payment.method else None,
                'created_at': payment.created_at,
                'updated_at': payment.updated_at,
                'bank_transfer_reference': payment.bank_transfer_reference if payment.method and payment.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER else None,

            }
            for payment in payment_queryset
        ]

        response_payload = {
            'event_id': event.event_id,
            'event_title': event.title,
            'organisation_id': organisation.id,
            'organisation_title': organisation.title,
            'summary': {
                'total_payments': aggregates.get('total_payments', 0),
                'completed_payments': aggregates.get('completed_payments', 0),
                'pending_payments': aggregates.get('pending_payments', 0),
                'failed_payments': aggregates.get('failed_payments', 0),
                'cancelled_payments': aggregates.get('cancelled_payments', 0),
                'total_completed_amount': total_completed_amount_value,
                'currency': currency,
            },
            'timeline': timeline,
        }
        serializer = SponsorshipPaymentHistorySerializer(response_payload)
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
        'event'
    )
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorPackageFilterSet
    search_fields = ['package_name', 'package_description']
    ordering_fields = ['package_name', 'added_at', 'base_amount']
    ordering = ['-added_at']
    lookup_field = 'package_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventSponsorPackageListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventSponsorPackageCreateUpdateSerializer
        return EventSponsorPackageDetailSerializer


@extend_schema_view(
    list=extend_schema(summary="List sponsor invites", tags=["Event Sponsor Invites"]),
    retrieve=extend_schema(summary="Retrieve sponsor invite", tags=["Event Sponsor Invites"]),
    create=extend_schema(summary="Create sponsor invite", tags=["Event Sponsor Invites"]),
    update=extend_schema(summary="Update sponsor invite", tags=["Event Sponsor Invites"]),
    partial_update=extend_schema(summary="Partially update sponsor invite", tags=["Event Sponsor Invites"]),
    destroy=extend_schema(summary="Delete sponsor invite", tags=["Event Sponsor Invites"]),
)
class EventSponsorInviteViewSet(viewsets.ModelViewSet):
    """ViewSet for sponsor invitation lifecycle."""

    queryset = EventSponsorInvite.objects.select_related('event', 'organisation', 'chapter_location')
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorInviteFilterSet
    search_fields = ['email', 'event__title', 'organisation__title']
    ordering_fields = ['sent_at', 'responded_at']
    ordering = ['-sent_at']
    lookup_field = 'invite_id'

    def get_serializer_class(self):
        if self.action == 'list':
            return EventSponsorInviteListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return EventSponsorInviteCreateUpdateSerializer
        return EventSponsorInviteDetailSerializer

    @extend_schema(
        summary="Accept sponsor invite by token",
        request={'application/json': {'type': 'object', 'properties': {'token': {'type': 'string', 'format': 'uuid'}}, 'required': ['token']}},
        tags=["Event Sponsor Invites"],
    )
    @action(detail=False, methods=['post'], url_path='accept-by-token', permission_classes=[permissions.AllowAny])
    def accept_by_token(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invite = EventSponsorInvite.objects.get(token=token)
        except EventSponsorInvite.DoesNotExist:
            return Response({'error': 'Invite not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not invite.is_valid:
            return Response({'error': 'Invite is no longer valid.'}, status=status.HTTP_400_BAD_REQUEST)

        invite.accepted = True
        invite.declined = False
        invite.responded_at = timezone.now()
        invite.save(update_fields=['accepted', 'declined', 'responded_at'])

        serializer = EventSponsorInviteDetailSerializer(invite, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Decline sponsor invite by token",
        request={'application/json': {'type': 'object', 'properties': {'token': {'type': 'string', 'format': 'uuid'}}, 'required': ['token']}},
        tags=["Event Sponsor Invites"],
    )
    @action(detail=False, methods=['post'], url_path='decline-by-token', permission_classes=[permissions.AllowAny])
    def decline_by_token(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invite = EventSponsorInvite.objects.get(token=token)
        except EventSponsorInvite.DoesNotExist:
            return Response({'error': 'Invite not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not invite.is_valid:
            return Response({'error': 'Invite is no longer valid.'}, status=status.HTTP_400_BAD_REQUEST)

        invite.declined = True
        invite.accepted = False
        invite.responded_at = timezone.now()
        invite.save(update_fields=['accepted', 'declined', 'responded_at'])

        serializer = EventSponsorInviteDetailSerializer(invite, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# LEADER VIEWSETS
# ============================================================================

User = get_user_model()


@extend_schema_view(
    list=extend_schema(
        summary="List leaders",
        description=(
            "Retrieve a list of location leaders. "
            "Leaders are assigned only to country, cluster, chapter, or area locations."
        ),
        tags=["Organisation Leaders"],
        parameters=[
            OpenApiParameter(name='user', type=OpenApiTypes.INT, description='Filter by user ID'),
            OpenApiParameter(name='organisation', type=OpenApiTypes.STR, description='Filter by organisation id or url_safe_title'),
            OpenApiParameter(name='location_type', type=OpenApiTypes.STR, description='Filter by location type (country, cluster, chapter, area)'),
            OpenApiParameter(name='location_id', type=OpenApiTypes.INT, description='Filter by location ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Retrieve leader details",
        tags=["Organisation Leaders"],
    ),
    create=extend_schema(
        summary="Create leader",
        description=(
            "Assign a verified member/controller from your organisation as a leader "
            "for a location using location_type and location_id."
        ),
        tags=["Organisation Leaders"],
    ),
    update=extend_schema(
        summary="Update leader",
        description="Update leader notes only. Location assignment cannot be changed.",
        tags=["Organisation Leaders"],
    ),
    partial_update=extend_schema(
        summary="Partially update leader",
        description="Partially update leader notes. Location assignment cannot be changed.",
        tags=["Organisation Leaders"],
    ),
    destroy=extend_schema(
        summary="Remove leader",
        tags=["Organisation Leaders"],
    ),
)
class LeaderViewSet(viewsets.ModelViewSet):
    """ViewSet for typed location leader assignments."""

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
        if self.action == 'list':
            return LeaderListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return LeaderCreateUpdateSerializer
        return LeaderDetailSerializer

    @extend_schema(
        summary="Search leader candidates",
        description=(
            "Search eligible users that can become leaders for an organisation. "
            "Candidates are verified members or controllers of that organisation."
        ),
        parameters=[
            OpenApiParameter(name='organisation', type=OpenApiTypes.STR, required=True, description='Organisation id or url_safe_title'),
            OpenApiParameter(name='search', type=OpenApiTypes.STR, required=False, description='Search by name, username, or email'),
            OpenApiParameter(name='location_type', type=OpenApiTypes.STR, required=False, description='Optional location type to exclude existing leaders'),
            OpenApiParameter(name='location_id', type=OpenApiTypes.INT, required=False, description='Optional location id to exclude existing leaders'),
        ],
        responses={200: OpenApiResponse(description='Paginated list of candidate users')},
        tags=["Organisation Leaders"],
    )
    @action(detail=False, methods=['get'], url_path='candidate-users')
    def candidate_users(self, request):
        organisation_id = request.query_params.get('organisation')
        if not organisation_id:
            return Response({'error': 'organisation query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            organisation = get_organisation_or_url_safe_title(organisation_id)
        except Http404:
            return Response({'error': 'Organisation not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_superuser and not request.user.is_staff:
            if not OrganisationControl.objects.filter(organisation=organisation, user=request.user).exists():
                return Response({'error': 'You must control this organisation to search candidates.'}, status=status.HTTP_403_FORBIDDEN)

        verified_member_ids = UserOrganisationMembership.objects.filter(
            organisation=organisation,
            verified_at__isnull=False,
        ).values_list('user_id', flat=True)
        controller_ids = OrganisationControl.objects.filter(
            organisation=organisation,
        ).values_list('user_id', flat=True)

        queryset = User.objects.filter(
            id__in=list(set(verified_member_ids).union(set(controller_ids)))
        )

        search_value = request.query_params.get('search', '').strip()
        if search_value:
            queryset = queryset.filter(
                Q(email__icontains=search_value)
                | Q(username__icontains=search_value)
                | Q(first_name__icontains=search_value)
                | Q(last_name__icontains=search_value)
            )

        location_type = request.query_params.get('location_type')
        location_id = request.query_params.get('location_id')
        if location_type and location_id:
            existing_user_ids = Leader.filter_by_location(
                Leader.objects.filter(organisation=organisation),
                location_type,
                int(location_id),
            ).values_list('user_id', flat=True)
            queryset = queryset.exclude(id__in=existing_user_ids)

        queryset = queryset.order_by('first_name', 'last_name', 'email')

        page = self.paginate_queryset(queryset)
        candidates = page if page is not None else queryset
        data = [
            {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': f"{user.first_name} {user.last_name}".strip() or user.username,
            }
            for user in candidates
        ]

        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)


# ============================================================================
# LOCATION LEADER INVITE VIEWSETS
# ============================================================================


@extend_schema_view(
    list=extend_schema(
        summary="List location leader invites",
        description="Retrieve invites for assigning leaders to locations.",
        tags=["Location Leader Invites"],
    ),
    retrieve=extend_schema(
        summary="Retrieve location leader invite",
        tags=["Location Leader Invites"],
    ),
    create=extend_schema(
        summary="Create location leader invite",
        description="Invite an eligible organisation user to become a location leader.",
        tags=["Location Leader Invites"],
    ),
    update=extend_schema(
        summary="Update location leader invite",
        tags=["Location Leader Invites"],
    ),
    partial_update=extend_schema(
        summary="Partially update location leader invite",
        tags=["Location Leader Invites"],
    ),
    destroy=extend_schema(
        summary="Delete location leader invite",
        tags=["Location Leader Invites"],
    ),
)
class LocationLeaderInviteViewSet(viewsets.ModelViewSet):
    """ViewSet for location leader invite lifecycle."""

    queryset = LocationLeaderInvite.objects.select_related(
        'organisation', 'target_user', 'invited_by'
    ).all()
    permission_classes = [permissions.IsAuthenticated, IsOrganisationController]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = LocationLeaderInviteFilterSet
    search_fields = ['target_user__email', 'target_user__first_name', 'target_user__last_name', 'organisation__title']
    ordering_fields = ['added_at', 'expires_at', 'accepted_at']
    ordering = ['-added_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return LocationLeaderInviteListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return LocationLeaderInviteCreateUpdateSerializer
        return LocationLeaderInviteDetailSerializer

    @extend_schema(
        summary="My location leader invites",
        description="List active invites targeted to the authenticated user.",
        tags=["Location Leader Invites"],
    )
    @action(detail=False, methods=['get'], url_path='my-invites')
    def my_invites(self, request):
        queryset = self.filter_queryset(
            self.get_queryset().filter(target_user=request.user)
        )
        page = self.paginate_queryset(queryset)
        serializer = LocationLeaderInviteListSerializer(
            page if page is not None else queryset,
            many=True,
            context={'request': request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        summary="Accept location leader invite",
        description="Accept an invite and create the leader assignment. Only invite target can accept.",
        request=None,
        responses={200: LocationLeaderInviteDetailSerializer},
        tags=["Location Leader Invites"],
    )
    @action(detail=True, methods=['post'], url_path='accept')
    def accept(self, request, pk=None):
        invite = self.get_object()

        if invite.target_user != request.user:
            return Response({'error': 'You can only accept invites sent to you.'}, status=status.HTTP_403_FORBIDDEN)

        if not invite.is_valid:
            return Response({'error': 'This invite is not valid.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invite.accept_invite(accepted_by=request.user)
        except DjangoValidationError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = LocationLeaderInviteDetailSerializer(invite, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
