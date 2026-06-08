from rest_framework import viewsets, filters
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view
)

from apps.attendee.models import AttendeeOrganisation
from apps.attendee.api.serializers import AttendeeOrganisationSerializer
from apps.attendee.api.filtersets import AttendeeOrganisationFilterSet
from apps.attendee.api.permissions import IsEventStaffOrReadOnly
from apps.common.pagination import StandardPagination
from apps.attendee.api.viewsets import NestedAttendeeViewSetMixin

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Organisations",
        description=(
            "Retrieve organisation associations for attendees showing which organisations attendees belong to or represent. "
            "Useful for tracking institutional affiliations, group registrations, and organisational analytics. "
            "Supports filtering by organisation, attendee, or association date."
        ),
        tags=['Attendee Organisations']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Organisation Details",
        description=(
            "Retrieve detailed information about a specific organisation association including "
            "the attendee, organisation details, association timestamp, and any additional context."
        ),
        tags=['Attendee Organisations']
    ),
    create=extend_schema(
        summary="Link Attendee to Organisation",
        description=(
            "Create a new association between an attendee and an organisation. "
            "Links attendees to institutions, companies, parishes, or other organisational entities they represent. "
            "Enables organisational reporting and group management."
        ),
        tags=['Attendee Organisations']
    ),
    destroy=extend_schema(
        summary="Unlink Attendee from Organisation",
        description=(
            "Remove an organisation association from an attendee when the affiliation is no longer valid. "
            "Does not delete the attendee or organisation records, only the association between them."
        ),
        tags=['Attendee Organisations']
    )
)
class AttendeeOrganisationViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeOrganisation associations.
    
    Handles the many-to-many relationship between attendees and organisations.
    Supports institutional affiliations, group registrations, and organisational analytics.
    No update operation - associations are either created or deleted.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeOrganisation.objects.select_related('attendee', 'organisation').all()
    serializer_class = AttendeeOrganisationSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeOrganisationFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']  # No update