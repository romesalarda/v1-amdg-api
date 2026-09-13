
from rest_framework import viewsets, permissions, filters, exceptions

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)

from apps.payments.models import CreditExpense
from apps.payments.api.serializers import (
    CreditExpenseListSerializer, CreditExpenseDetailSerializer, CreditExpenseCreateSerializer, CreditExpenseUpdateSerializer,
)
from apps.payments.api.filtersets import CreditExpenseFilterSet
from apps.payments.api.permissions import IsCreditAccessible, user_can_access_event_payments
from apps.common.pagination import StandardPagination
from apps.payments.api.permissions import user_can_manage_credits

import logging

logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(
        summary='List credit expenses',
        description=(
            'Retrieve a list of credit expenses. Access is scoped to events the user can view. '
            'Supports filtering by event, settlement status, and date range.'
        ),
        tags=['Credit Expenses'],
    ),
    retrieve=extend_schema(
        summary='Retrieve credit expense',
        description='Get detailed information about a specific credit expense record.',
        tags=['Credit Expenses'],
    ),
    create=extend_schema(
        summary='Create credit expense',
        description=(
            'Create a new credit expense. Requires event association and appropriate permissions. '
            'Used to record expected inbound funds for budgeting purposes.'
        ),
        tags=['Credit Expenses'],
    ),
    update=extend_schema(
        summary='Update credit expense',
        description='Update details of a credit expense record. Only possible before settlement.',
        tags=['Credit Expenses'],
    ),
    partial_update=extend_schema(
        summary='Partially update credit expense',
        description='Partially update details of a credit expense record. Only possible before settlement.',
        tags=['Credit Expenses'],
    ),
    destroy=extend_schema(
        summary='Delete credit expense',
        description='Delete a credit expense record. Only possible before settlement.',
        tags=['Credit Expenses'],
    ),
)
class CreditExpenseViewSet(viewsets.ModelViewSet):
    """CRUD viewset for credit expenses."""

    queryset = CreditExpense.objects.select_related('event', 'created_by', 'verified_by', 'processed_by', 'target_type')
    permission_classes = [permissions.IsAuthenticated, IsCreditAccessible]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CreditExpenseFilterSet
    search_fields = ['credit_id', 'description', 'event__name', 'created_by__username']
    ordering_fields = ['created_at', 'updated_at', 'amount', 'paid_date', 'expense_type', 'is_settled']
    ordering = ['-created_at']
    lookup_field = 'credit_id'

    def get_serializer_class(self):
        if self.action == 'list':
            return CreditExpenseListSerializer
        if self.action == 'create':
            return CreditExpenseCreateSerializer
        if self.action in ['update', 'partial_update']:
            return CreditExpenseUpdateSerializer
        return CreditExpenseDetailSerializer

    def get_queryset(self):
        """
        For LIST only: no event filter -> only credits the user created;
        event/event__event_id filter -> all credits for that event if authorized, else own only.
        Detail actions rely on object-level permissions.
        """
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if self.action != 'list':
            return queryset

        from apps.events.models import Event

        event_uuid = self.request.query_params.get('event__event_id')
        event_pk = self.request.query_params.get('event')

        if not event_uuid and not event_pk:
            return queryset.filter(created_by=user).distinct()

        event = None
        if event_uuid:
            event = Event.objects.filter(event_id=event_uuid).first()
        elif event_pk and str(event_pk).isdigit():
            event = Event.objects.filter(pk=int(event_pk)).first()

        if not event:
            return queryset.none()

        if user_can_access_event_payments(user, event, action='read'):
            return queryset.filter(event=event).distinct()

        return queryset.filter(event=event, created_by=user).distinct()

    def perform_create(self, serializer):
        event = serializer.validated_data.get('event')
        if not user_can_manage_credits(self.request.user, event):
            raise exceptions.PermissionDenied('You do not have permission to create credits for this event.')

        serializer.save(created_by=self.request.user)