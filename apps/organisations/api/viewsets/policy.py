from rest_framework import viewsets, permissions, filters
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.organisations.models import (
    OrganisationEventPolicy, OrganisationEventTypePolicyRestriction,
)
from apps.organisations.api.serializers import (
    OrganisationEventPolicySerializer,
    OrganisationEventTypePolicyRestrictionListSerializer,
    OrganisationEventTypePolicyRestrictionDetailSerializer,
    OrganisationEventTypePolicyRestrictionCreateUpdateSerializer,
)
from apps.organisations.api.filtersets import OrganisationEventTypePolicyRestrictionFilterSet
from apps.organisations.api.permissions import WriteRequiresControllerOrPolicyManager

from apps.common.pagination import StandardPagination


# ============================================================================
# ORGANISATION EVENT TYPE POLICY RESTRICTION VIEWSET
# ============================================================================


@extend_schema_view(
    list=extend_schema(
        summary="List Event Type Policy Restrictions",
        description=(
            "Retrieve a list of event type restrictions defined for organisations. "
            "Each restriction specifies whether a particular event type is allowed "
            "under an organisation and whether it requires additional approval. "
            "Any authenticated user may read; write operations require a controller "
            "or a leader with policy management permission."
        ),
        tags=["Organisation Policy"],
        parameters=[
            OpenApiParameter(
                name='organisation',
                type=OpenApiTypes.STR,
                description='Filter by organisation id or url_safe_title',
            ),
            OpenApiParameter(
                name='event_type',
                type=OpenApiTypes.INT,
                description='Filter by EventType ID',
            ),
            OpenApiParameter(
                name='is_allowed',
                type=OpenApiTypes.BOOL,
                description='Filter by whether the event type is allowed',
            ),
            OpenApiParameter(
                name='requires_approval',
                type=OpenApiTypes.BOOL,
                description='Filter by whether approval is required',
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve Event Type Policy Restriction",
        description="Get details of a specific event type policy restriction.",
        tags=["Organisation Policy"],
    ),
    create=extend_schema(
        summary="Create Event Type Policy Restriction",
        description=(
            "Define a restriction for an event type under an organisation. "
            "Requires controller or policy management leader permission."
        ),
        tags=["Organisation Policy"],
    ),
    update=extend_schema(
        summary="Update Event Type Policy Restriction",
        description=(
            "Update an event type restriction. "
            "Requires controller or policy management leader permission."
        ),
        tags=["Organisation Policy"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Type Policy Restriction",
        description=(
            "Partially update an event type restriction. "
            "Requires controller or policy management leader permission."
        ),
        tags=["Organisation Policy"],
    ),
    destroy=extend_schema(
        summary="Delete Event Type Policy Restriction",
        description=(
            "Remove an event type restriction. "
            "Requires controller or policy management leader permission."
        ),
        tags=["Organisation Policy"],
    ),
)
class OrganisationEventTypePolicyRestrictionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for OrganisationEventTypePolicyRestriction.

    Read access: any authenticated user.
    Write access: organisation controllers or leaders with ALLOW_POLICY_MANAGEMENT.
    """

    queryset = OrganisationEventTypePolicyRestriction.objects.select_related(
        'organisation', 'event_type', 'created_by'
    ).all()
    permission_classes = [permissions.IsAuthenticated, WriteRequiresControllerOrPolicyManager]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = OrganisationEventTypePolicyRestrictionFilterSet
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['organisation', 'event_type']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return OrganisationEventTypePolicyRestrictionCreateUpdateSerializer
        if self.action == 'list':
            return OrganisationEventTypePolicyRestrictionListSerializer
        return OrganisationEventTypePolicyRestrictionDetailSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
