from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.organisations.models import (
    UserOrganisationMembership, OrganisationAcceptanceCode, OrganisationInvite,
)
from apps.organisations.api.serializers import (
    UserOrganisationMembershipListSerializer, UserOrganisationMembershipDetailSerializer, UserOrganisationMembershipCreateUpdateSerializer,
    OrganisationAcceptanceCodeSerializer, OrganisationAcceptanceCodeCreateUpdateSerializer,
    OrganisationInviteListSerializer, OrganisationInviteDetailSerializer, OrganisationInviteCreateUpdateSerializer,
)
from apps.organisations.api.filtersets import (
    UserOrganisationMembershipFilterSet, OrganisationAcceptanceCodeFilterSet, OrganisationInviteFilterSet,
)
from apps.organisations.api.permissions import IsOrganisationController

from apps.common.pagination import StandardPagination

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
    permission_classes = [permissions.IsAuthenticated, IsOrganisationController]
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