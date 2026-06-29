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
)
from apps.utils.querying import get_object_or_url_safe_title
from apps.organisations.api.serializers import (
    OrganisationListSerializer, OrganisationDetailSerializer, OrganisationCreateUpdateSerializer,
    OrganisationContactSerializer, OrganisationContactCreateUpdateSerializer,
    OrganisationControlSerializer, OrganisationControlCreateUpdateSerializer,
    UserOrganisationMembershipListSerializer,

)
from apps.organisations.api.filtersets import (
    OrganisationFilterSet, OrganisationContactFilterSet, OrganisationControlFilterSet,
)
from apps.organisations.api.permissions import (
    IsOrganisationController, IsOrganisationControllerOrEventAdmin,
    IsReadOnly
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
        organisation = get_object_or_url_safe_title(self.get_queryset(), lookup_value)
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

    @extend_schema(
        summary="List organisation controllers",
        description="Get all controllers for a specific organisation.",
        responses={200: {
            "type": "object",
            "properties": {
                "organisation" : {"type": "string"},
                "organisation_url_safe_title" : {"type": "string"},
                "can_view": {"type": "boolean"},
            }
        }},
        tags=["Organisations"],
    )
    @action(detail=True, methods=["GET"], url_path="my-permissions")
    def my_permissions(self, request, url_safe_title):
        obj = self.get_object()
        permissions = {
            "organisation": obj.title,
            "organisation_url_safe_title": obj.url_safe_title,
            "can_view": IsOrganisationControllerOrEventAdmin().has_permission(request, self),
        }
        return Response(permissions)

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