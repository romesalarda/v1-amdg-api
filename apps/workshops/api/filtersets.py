from django_filters import rest_framework as filters

from apps.workshops.models.workshop import Workshop, WorkshopStatus, AllocationMode
from apps.workshops.models.registration import WorkshopRegistration, WorkshopRegistrationStatus
from apps.workshops.models.interest import WorkshopInterestSubmission


class WorkshopFilterSet(filters.FilterSet):
    """
    Filterset for Workshop list endpoints.

    Supported filters:
    - event: filter by event ID
    - status: lifecycle status (DRAFT, OPEN, CLOSED, CANCELLED)
    - allocation_mode: FCFS, INTEREST_RANKING, RANDOM, MANUAL
    - date_after / date_before: filter by workshop date range
    """

    date_after = filters.DateTimeFilter(field_name='date', lookup_expr='gte')
    date_before = filters.DateTimeFilter(field_name='date', lookup_expr='lte')

    class Meta:
        model = Workshop
        fields = ('event', 'status', 'allocation_mode')


class WorkshopRegistrationFilterSet(filters.FilterSet):
    """
    Filterset for WorkshopRegistration list endpoints.

    Supported filters:
    - workshop: filter by workshop ID
    - attendee: filter by attendee ID
    - status: PENDING_ALLOCATION, CONFIRMED, WAITLISTED, CANCELLED
    - allocation_method: which method produced the registration
    """

    class Meta:
        model = WorkshopRegistration
        fields = ('workshop', 'attendee', 'status', 'allocation_method')


class WorkshopInterestSubmissionFilterSet(filters.FilterSet):
    """
    Filterset for WorkshopInterestSubmission list endpoints.

    Supported filters:
    - event: filter by event ID
    - attendee: filter by attendee ID
    - is_finalised: boolean — only finalised / only draft submissions
    """

    class Meta:
        model = WorkshopInterestSubmission
        fields = ('event', 'attendee', 'is_finalised')
