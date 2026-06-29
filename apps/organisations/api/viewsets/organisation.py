from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.organisations.models import (
    Organisation, OrganisationContact, OrganisationControl,
    OrganisationEventPolicy,
)
from apps.utils.querying import get_object_or_url_safe_title
from apps.organisations.api.serializers import (
    OrganisationListSerializer, OrganisationDetailSerializer, OrganisationCreateUpdateSerializer,
    OrganisationContactSerializer, OrganisationContactCreateUpdateSerializer,
    OrganisationControlSerializer, OrganisationControlCreateUpdateSerializer,
    UserOrganisationMembershipListSerializer,
    OrganisationEventPolicySerializer,
)
from apps.organisations.api.filtersets import (
    OrganisationFilterSet, OrganisationContactFilterSet, OrganisationControlFilterSet,
)
from apps.organisations.api.permissions import (
    IsOrganisationController, IsOrganisationControllerOrEventAdmin,
    IsReadOnly, WriteRequiresControllerOrPolicyManager,
)

from apps.common.pagination import StandardPagination

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
    ).filter(verified=True)
    
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
        print(f"Looking up organisation with {self.lookup_field}={lookup_value}")  # Debugging line
        organisation = get_object_or_url_safe_title(self.get_queryset(), lookup_value)
        print(f"Found organisation: {organisation}")  # Debugging line
        self.check_object_permissions(self.request, organisation)
        print(f"Permissions checked for organisation: {organisation}")  # Debugging line
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

    @extend_schema(
        summary="My permissions for this organisation",
        description=(
            "Returns the requesting user's permission summary for this organisation, including "
            "controller status, membership status, leader status, and all leader permission codes "
            "with their CRUD flags. Designed to power frontend community permission middleware."
        ),
        responses={200: {
            'type': 'object',
            'properties': {
                'organisation': {'type': 'string'},
                'organisation_url_safe_title': {'type': 'string'},
                'is_staff': {'type': 'boolean'},
                'is_controller': {'type': 'boolean'},
                'is_member': {'type': 'boolean'},
                'is_leader': {'type': 'boolean'},
                'leader_permissions': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'permission_code': {'type': 'string'},
                            'allow_create': {'type': 'boolean'},
                            'allow_read': {'type': 'boolean'},
                            'allow_update': {'type': 'boolean'},
                            'allow_delete': {'type': 'boolean'},
                        },
                    },
                },
            },
        }},
        tags=["Organisations"],
    )
    @action(detail=True, methods=["GET"], url_path="my-permissions")
    def my_permissions(self, request, url_safe_title):
        from apps.organisations.models import (
            UserOrganisationMembership, Leader, LeaderPermission,
        )
        obj = self.get_object()
        user = request.user
        is_controller = (
            user.is_superuser
            or user.is_staff
            or OrganisationControl.objects.filter(organisation=obj, user=user).exists()
        )
        is_member = UserOrganisationMembership.objects.filter(
            organisation=obj, user=user
        ).exists()
        is_leader = Leader.objects.filter(organisation=obj, user=user).exists()
        leader_permissions = []
        if is_leader:
            leader_permissions = list(
                LeaderPermission.objects.filter(
                    leader__organisation=obj, leader__user=user
                ).values(
                    'permission_code', 'allow_create', 'allow_read',
                    'allow_update', 'allow_delete',
                )
            )
        return Response({
            'organisation': obj.title,
            'organisation_url_safe_title': obj.url_safe_title,
            'is_staff': user.is_superuser or user.is_staff,
            'is_controller': is_controller,
            'is_member': is_member,
            'is_leader': is_leader,
            'leader_permissions': leader_permissions,
        })

    @extend_schema(
        summary="Get or update organisation event policy",
        description=(
            "GET: Retrieve the event policy for this organisation (created automatically on first access). "
            "PATCH: Update policy fields. Requires controller access or a leader with "
            "ALLOW_POLICY_MANAGEMENT permission."
        ),
        request=OrganisationEventPolicySerializer,
        responses={200: OrganisationEventPolicySerializer},
        tags=["Organisation Policy"],
    )
    @action(
        detail=True,
        methods=['get', 'patch'],
        url_path='policy',
        permission_classes=[
            permissions.IsAuthenticated,
            WriteRequiresControllerOrPolicyManager,
        ],
    )
    def policy(self, request, url_safe_title=None):
        organisation = self.get_object()
        event_policy, _ = OrganisationEventPolicy.objects.get_or_create(
            organisation=organisation,
            defaults={'created_by': request.user},
        )
        if request.method == 'PATCH':
            # Check write permission manually since the action uses a custom permission list
            # and the organisation object has already been fetched above.
            write_perm = WriteRequiresControllerOrPolicyManager()
            if not write_perm.has_object_permission(request, self, organisation):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(write_perm.message)
            serializer = OrganisationEventPolicySerializer(
                event_policy,
                data=request.data,
                partial=True,
                context={'request': request},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        serializer = OrganisationEventPolicySerializer(
            event_policy, context={'request': request}
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