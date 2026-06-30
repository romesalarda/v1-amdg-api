import uuid

from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.http import Http404
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.organisations.models import (
    OrganisationControl, UserOrganisationMembership, Leader, LocationLeaderInvite,
    LeaderPermission,
)
from apps.utils.querying import get_organisation_or_url_safe_title, get_object_or_url_safe_title
from apps.organisations.api.serializers import (
    LeaderListSerializer, LeaderDetailSerializer, LeaderCreateUpdateSerializer,
    LocationLeaderInviteListSerializer, LocationLeaderInviteDetailSerializer, LocationLeaderInviteCreateUpdateSerializer,
    LeaderPermissionSerializer, LeaderPermissionCreateUpdateSerializer,
)
from apps.organisations.api.filtersets import (LeaderFilterSet, LocationLeaderInviteFilterSet, LeaderPermissionFilterSet)
from apps.organisations.api.permissions import (
    IsOrganisationController, WriteRequiresOrganisationController,
    HasManageLeadersPermission,
)

from apps.common.pagination import StandardPagination

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

    def get_permissions(self):
        """Safe methods allow leaders with ALLOW_MANAGE_LEADERS; writes remain controller-only."""
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated(), HasManageLeadersPermission()]
        return [permissions.IsAuthenticated(), IsOrganisationController()]

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
            
        if organisation.requires_manual_verification:
            verified_member_ids = UserOrganisationMembership.objects.filter(
                organisation=organisation,
                verified_at__isnull=False,
            ).values_list('user_id', flat=True)
        else:
            verified_member_ids = UserOrganisationMembership.objects.filter(
                organisation=organisation,
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

    def get_permissions(self):
        """Safe methods allow leaders with ALLOW_MANAGE_LEADERS; writes remain controller-only."""
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated(), HasManageLeadersPermission()]
        return [permissions.IsAuthenticated(), IsOrganisationController()]

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


# ============================================================================
# LEADER PERMISSION VIEWSET
# ============================================================================


@extend_schema_view(
    list=extend_schema(
        summary="List Leader Permissions",
        description=(
            "Retrieve leader permissions. Non-controller users see only their own permissions. "
            "Organisation controllers see all permissions and can filter by user or organisation."
        ),
        tags=["Leader Permissions"],
        parameters=[
            OpenApiParameter(name='leader', type=OpenApiTypes.INT, description='Filter by leader ID'),
            OpenApiParameter(name='user', type=OpenApiTypes.INT, description='Filter by user ID'),
            OpenApiParameter(name='organisation', type=OpenApiTypes.STR, description='Filter by organisation id or url_safe_title'),
            OpenApiParameter(name='permission_code', type=OpenApiTypes.STR, description='Filter by permission code'),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve Leader Permission",
        description="Retrieve details of a leader permission. Non-controllers can only access their own.",
        tags=["Leader Permissions"],
    ),
    create=extend_schema(
        summary="Create Leader Permission",
        description="Assign a permission code to a leader. Only organisation controllers can create leader permissions.",
        tags=["Leader Permissions"],
    ),
    update=extend_schema(
        summary="Update Leader Permission",
        description="Update a leader permission. Only organisation controllers can update.",
        tags=["Leader Permissions"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Leader Permission",
        description="Partially update a leader permission. Only organisation controllers can update.",
        tags=["Leader Permissions"],
    ),
    destroy=extend_schema(
        summary="Delete Leader Permission",
        description="Remove a permission from a leader. Only organisation controllers can delete.",
        tags=["Leader Permissions"],
    ),
)
class LeaderPermissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for LeaderPermission records.

    Read access:
      - Any authenticated user can list/retrieve their own leader permissions.
      - Organisation controllers (and Django staff/superusers) can access all records.

    Write access (create, update, delete):
      - Restricted to organisation controllers and Django staff/superusers.
    """

    serializer_class = LeaderPermissionSerializer
    permission_classes = [permissions.IsAuthenticated, WriteRequiresOrganisationController]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = LeaderPermissionFilterSet
    search_fields = ['permission_code', 'description']
    ordering_fields = ['created_at', 'permission_code']
    ordering = ['permission_code']

    def get_queryset(self):
        """
        Non-controllers see only their own LeaderPermission records.
        Controllers and staff/superusers see all records.
        """
        if getattr(self, 'swagger_fake_view', False):
            return LeaderPermission.objects.none()
        user = self.request.user
        base_qs = LeaderPermission.objects.select_related(
            'leader__user', 'leader__organisation'
        )
        if user.is_superuser or user.is_staff:
            return base_qs
        if OrganisationControl.objects.filter(user=user).exists():
            return base_qs
        # Regular leaders — scope to own records only
        return base_qs.filter(leader__user=user)

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LeaderPermissionCreateUpdateSerializer
        return LeaderPermissionSerializer