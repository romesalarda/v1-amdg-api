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

from apps.payments.models import DebitExpense
from apps.payments.api.serializers import (
    DebitExpenseListSerializer, DebitExpenseDetailSerializer, DebitExpenseCreateSerializer, DebitExpenseUpdateSerializer,
)
from apps.payments.api.filtersets import DebitExpenseFilterSet
from apps.payments.api.permissions import IsDebitAccessible
from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
from apps.common.pagination import StandardPagination
from apps.payments.api.permissions import user_can_manage_credits

import logging

logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(
        summary='List debit expenses',
        description='List estimated inbound expenses. Users see records they created or for events they manage.',
        tags=['Budget'],
    ),
    retrieve=extend_schema(
        summary='Retrieve debit expense',
        description='Get detailed information about a specific debit expense including quantity and unit price.',
        tags=['Budget'],
    ),
    create=extend_schema(
        summary='Create debit expense',
        description=(
            'Create a new estimated inbound expense. amount is auto-computed from quantity × unit_price. '
            'target_* fields are backend-only and must not be supplied.'
        ),
        tags=['Budget'],
    ),
    update=extend_schema(
        summary='Update debit expense',
        description='Update a debit expense with a complete payload. Use PATCH for partial updates.',
        tags=['Budget'],
    ),
    partial_update=extend_schema(
        summary='Partially update debit expense',
        description='Partially update a debit expense such as description or quantity.',
        tags=['Budget'],
    ),
    destroy=extend_schema(
        summary='Delete debit expense',
        description='Delete a debit expense. Only possible before verification.',
        tags=['Budget'],
    ),
)
class DebitExpenseViewSet(viewsets.ModelViewSet):
    """CRUD viewset for debit (estimated inbound) expenses."""

    queryset = DebitExpense.objects.select_related('event', 'created_by', 'verified_by', 'processed_by', 'target_type')
    permission_classes = [permissions.IsAuthenticated, IsDebitAccessible]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DebitExpenseFilterSet
    search_fields = ['debit_id', 'description', 'event__name', 'created_by__username']
    ordering_fields = ['created_at', 'updated_at', 'amount', 'paid_date', 'expense_type', 'is_settled', 'quantity']
    ordering = ['-created_at']
    lookup_field = 'debit_id'

    def get_serializer_class(self):
        if self.action == 'list':
            return DebitExpenseListSerializer
        if self.action == 'create':
            return DebitExpenseCreateSerializer
        if self.action in ['update', 'partial_update']:
            return DebitExpenseUpdateSerializer
        return DebitExpenseDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        accessible_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).values_list('event_id', flat=True)

        finance_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__name__icontains='finance'
        ).values_list('event_id', flat=True)

        return queryset.filter(
            Q(created_by=user) |
            Q(event_id__in=accessible_event_ids) |
            Q(event_id__in=finance_event_ids)
        ).distinct()

    def perform_create(self, serializer):
        event = serializer.validated_data.get('event')
        if not user_can_manage_credits(self.request.user, event):
            raise exceptions.PermissionDenied('You do not have permission to create debits for this event.')
        serializer.save(created_by=self.request.user)
