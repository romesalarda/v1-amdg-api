from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.organisations.models import InvolvedEventOrganisation
from apps.organisations.api.serializers import InvolvedEventOrganisationSerializer, InvolvedEventOrganisationCreateUpdateSerializer
from apps.organisations.api.filtersets import InvolvedEventOrganisationFilterSet
from apps.organisations.api.permissions import (IsOrganisationControllerOrEventAdmin,)

from apps.common.pagination import StandardPagination

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