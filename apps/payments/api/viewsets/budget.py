from rest_framework import viewsets, status, permissions, filters, serializers, exceptions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes

from apps.payments.models import (
    Payment, PaymentStatusChoices, CreditExpense,
    DebitExpense, BudgetProposal,
)
from apps.payments.api.serializers import (
    CreditExpenseListSerializer, 
    DebitExpenseListSerializer, 
    BudgetProposalListSerializer, BudgetProposalDetailSerializer, BudgetProposalCreateSerializer, BudgetProposalUpdateSerializer,
    BudgetProposalStatisticsSerializer, EventBudgetStatisticsSerializer,
)
from apps.payments.api.filtersets import BudgetProposalFilterSet

from apps.payments.api.permissions import IsBudgetProposalAccessible
from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
from apps.common.pagination import StandardPagination

from apps.payments.api.permissions import user_can_manage_credits

import logging

logger = logging.getLogger(__name__)

@extend_schema_view(
    list=extend_schema(
        summary='List budget proposals',
        description='List budget proposals for events the user manages. Includes aggregated totals and health status.',
        tags=['Budget'],
    ),
    retrieve=extend_schema(
        summary='Retrieve budget proposal',
        description='Get detailed information about a budget proposal including linked credits, debits, and statistics.',
        tags=['Budget'],
    ),
    create=extend_schema(
        summary='Create budget proposal',
        description=(
            'Create a new budget proposal for an event. Optionally link existing credit and debit expenses. '
            'All linked expenses must belong to the same event as the proposal.'
        ),
        tags=['Budget'],
    ),
    update=extend_schema(
        summary='Update budget proposal',
        description='Update a budget proposal with a complete payload. Use PATCH for partial updates.',
        tags=['Budget'],
    ),
    partial_update=extend_schema(
        summary='Partially update budget proposal',
        description='Partially update a budget proposal such as title, description, or linked expenses.',
        tags=['Budget'],
    ),
    destroy=extend_schema(
        summary='Delete budget proposal',
        description='Delete a budget proposal. Does not delete linked credit or debit expenses.',
        tags=['Budget'],
    ),
)
class BudgetProposalViewSet(viewsets.ModelViewSet):
    """Full CRUD viewset for budget proposals with nested credit/debit management and statistics."""

    queryset = BudgetProposal.objects.select_related(
        'event', 'proposed_by', 'verified_by', 'processed_by'
    ).prefetch_related('credit_expenses', 'debit_expenses')
    permission_classes = [permissions.IsAuthenticated, IsBudgetProposalAccessible]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BudgetProposalFilterSet
    search_fields = ['proposal_title', 'proposal_description', 'event__name', 'proposed_by__username']
    ordering_fields = ['created_at', 'updated_at', 'proposal_title', 'verification_status']
    ordering = ['-created_at']
    lookup_field = 'proposal_id'

    def get_serializer_class(self):
        if self.action == 'list':
            return BudgetProposalListSerializer
        if self.action == 'create':
            return BudgetProposalCreateSerializer
        if self.action in ['update', 'partial_update']:
            return BudgetProposalUpdateSerializer
        return BudgetProposalDetailSerializer

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
            Q(proposed_by=user) |
            Q(event_id__in=accessible_event_ids) |
            Q(event_id__in=finance_event_ids)
        ).distinct()

    def perform_create(self, serializer):
        event = serializer.validated_data.get('event')
        if not user_can_manage_credits(self.request.user, event):
            raise exceptions.PermissionDenied('You do not have permission to create budget proposals for this event.')
        serializer.save()

    # ------------------------------------------------------------------
    # Nested credit management actions
    # ------------------------------------------------------------------

    @extend_schema(
        summary='List credits linked to proposal',
        description='Returns all credit expenses currently linked to this budget proposal.',
        tags=['Budget'],
        responses={
            200: CreditExpenseListSerializer(many=True)
        }
    )
    @action(detail=True, methods=['get'], url_path='credits')
    def credits(self, request, proposal_id=None):
        proposal = self.get_object()
        qs = proposal.credit_expenses.all()
        page = self.paginate_queryset(qs)
        serializer = CreditExpenseListSerializer(
            page if page is not None else qs, many=True, context={'request': request}
        )
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @extend_schema(
        summary='Add credit to proposal',
        description='Link an existing CreditExpense to this budget proposal. The credit must belong to the same event.',
        request=inline_serializer(
            name='AddCreditRequest',
            fields={'credit_id': serializers.UUIDField(help_text='UUID of the CreditExpense to link')}
        ),
        responses={200: {'description': 'Credit linked successfully'}, 400: {'description': 'Validation error'}},
        tags=['Budget'],
    )
    @action(detail=True, methods=['post'], url_path='add-credit')
    def add_credit(self, request, proposal_id=None):
        proposal = self.get_object()
        credit_id = request.data.get('credit_id')
        if not credit_id:
            raise ValidationError({'credit_id': 'This field is required.'})

        try:
            credit = CreditExpense.objects.get(credit_id=credit_id)
        except CreditExpense.DoesNotExist:
            raise ValidationError({'credit_id': 'Credit expense not found.'})

        if proposal.event_id and credit.event_id != proposal.event_id:
            raise ValidationError({'credit_id': 'This credit does not belong to the proposal\'s event.'})

        proposal.credit_expenses.add(credit)
        return Response({'detail': 'Credit linked to proposal.'}, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Remove credit from proposal',
        description='Unlink a CreditExpense from this budget proposal. Does not delete the credit expense.',
        request=inline_serializer(
            name='RemoveCreditRequest',
            fields={'credit_id': serializers.UUIDField(help_text='UUID of the CreditExpense to unlink')}
        ),
        responses={200: {'description': 'Credit unlinked successfully'}, 400: {'description': 'Validation error'}},
        tags=['Budget'],
    )
    @action(detail=True, methods=['post'], url_path='remove-credit')
    def remove_credit(self, request, proposal_id=None):
        proposal = self.get_object()
        credit_id = request.data.get('credit_id')
        if not credit_id:
            raise ValidationError({'credit_id': 'This field is required.'})

        try:
            credit = CreditExpense.objects.get(credit_id=credit_id)
        except CreditExpense.DoesNotExist:
            raise ValidationError({'credit_id': 'Credit expense not found.'})

        proposal.credit_expenses.remove(credit)
        return Response({'detail': 'Credit unlinked from proposal.'}, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Nested debit management actions
    # ------------------------------------------------------------------

    @extend_schema(
        summary='List debits linked to proposal',
        description='Returns all debit expenses currently linked to this budget proposal.',
        tags=['Budget'],
        responses={
            200: DebitExpenseListSerializer(many=True)
        }
    )
    @action(detail=True, methods=['get'], url_path='debits')
    def debits(self, request, proposal_id=None):
        proposal = self.get_object()
        qs = proposal.debit_expenses.all()
        page = self.paginate_queryset(qs)
        serializer = DebitExpenseListSerializer(
            page if page is not None else qs, many=True, context={'request': request}
        )
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @extend_schema(
        summary='Add debit to proposal',
        description='Link an existing DebitExpense to this budget proposal. The debit must belong to the same event.',
        request=inline_serializer(
            name='AddDebitRequest',
            fields={'debit_id': serializers.UUIDField(help_text='UUID of the DebitExpense to link')}
        ),
        responses={200: {'description': 'Debit linked successfully'}, 400: {'description': 'Validation error'}},
        tags=['Budget'],
    )
    @action(detail=True, methods=['post'], url_path='add-debit')
    def add_debit(self, request, proposal_id=None):
        proposal = self.get_object()
        debit_id = request.data.get('debit_id')
        if not debit_id:
            raise ValidationError({'debit_id': 'This field is required.'})

        try:
            debit = DebitExpense.objects.get(debit_id=debit_id)
        except DebitExpense.DoesNotExist:
            raise ValidationError({'debit_id': 'Debit expense not found.'})

        if proposal.event_id and debit.event_id != proposal.event_id:
            raise ValidationError({'debit_id': 'This debit does not belong to the proposal\'s event.'})

        proposal.debit_expenses.add(debit)
        return Response({'detail': 'Debit linked to proposal.'}, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Remove debit from proposal',
        description='Unlink a DebitExpense from this budget proposal. Does not delete the debit expense.',
        request=inline_serializer(
            name='RemoveDebitRequest',
            fields={'debit_id': serializers.UUIDField(help_text='UUID of the DebitExpense to unlink')}
        ),
        responses={200: {'description': 'Debit unlinked successfully'}, 400: {'description': 'Validation error'}},
        tags=['Budget'],
    )
    @action(detail=True, methods=['post'], url_path='remove-debit')
    def remove_debit(self, request, proposal_id=None):
        proposal = self.get_object()
        debit_id = request.data.get('debit_id')
        if not debit_id:
            raise ValidationError({'debit_id': 'This field is required.'})

        try:
            debit = DebitExpense.objects.get(debit_id=debit_id)
        except DebitExpense.DoesNotExist:
            raise ValidationError({'debit_id': 'Debit expense not found.'})

        proposal.debit_expenses.remove(debit)
        return Response({'detail': 'Debit unlinked from proposal.'}, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Statistics actions
    # ------------------------------------------------------------------

    @extend_schema(
        summary='Per-proposal budget statistics',
        description=(
            'Returns estimated vs real inbound, total outgoing, net figures, variance, and health status '
            'for a single budget proposal. Real inbound is read-only from completed payments — never modified.'
        ),
        responses={200: BudgetProposalStatisticsSerializer},
        tags=['Budget'],
    )
    @action(detail=True, methods=['get'], url_path='statistics')
    def statistics(self, request, proposal_id=None):
        from django.db.models import Sum as DbSum
        proposal = self.get_object()
        currency = 'GBP'

        estimated_inbound = proposal.total_debits.amount if proposal.total_debits else 0
        if proposal.total_debits:
            currency = str(proposal.total_debits.currency)

        total_outgoing = proposal.total_credits.amount if proposal.total_credits else 0

        real_result = Payment.objects.filter(
            event=proposal.event,
            status=PaymentStatusChoices.COMPLETED,
        ).aggregate(total=DbSum('base_amount')) if proposal.event_id else {'total': None}
        real_inbound = real_result.get('total') or 0

        net_estimated = estimated_inbound - total_outgoing
        net_real = real_inbound - total_outgoing
        variance = real_inbound - estimated_inbound

        if real_inbound == 0 and total_outgoing == 0:
            health = 'UNKNOWN'
        elif net_real > 0:
            health = 'SURPLUS'
        elif net_real == 0:
            health = 'BREAK_EVEN'
        else:
            health = 'DEFICIT'

        data = {
            'proposal_id': proposal.proposal_id,
            'proposal_title': proposal.proposal_title,
            'event_id': proposal.event.event_id if proposal.event else None,
            'event_name': proposal.event.title if proposal.event else None,
            'estimated_inbound': estimated_inbound,
            'estimated_inbound_currency': currency,
            'real_inbound': real_inbound,
            'real_inbound_currency': currency,
            'total_outgoing': total_outgoing,
            'total_outgoing_currency': currency,
            'net_estimated': net_estimated,
            'net_real': net_real,
            'variance': variance,
            'health_status': health,
            'credit_count': proposal.credit_expenses.count(),
            'debit_count': proposal.debit_expenses.count(),
        }
        serializer = BudgetProposalStatisticsSerializer(data)
        return Response(serializer.data)

    @extend_schema(
        summary='Per-event budget statistics',
        description=(
            'Aggregates budget statistics across all proposals for an event. '
            'Accepts event_id (UUID) as a required query parameter. '
            'Real inbound is read-only from completed payments — never modified.'
        ),
        parameters=[
            OpenApiParameter(
                name='event_id', type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY,
                description='Event UUID to aggregate budget statistics for', required=True,
            )
        ],
        responses={200: EventBudgetStatisticsSerializer},
        tags=['Budget'],
    )
    @action(detail=False, methods=['get'], url_path='event-statistics')
    def event_statistics(self, request):
        from django.db.models import Sum as DbSum
        event_id = request.query_params.get('event_id')
        if not event_id:
            raise ValidationError({'event_id': 'This query parameter is required.'})

        proposals = self.get_queryset().filter(event__url_safe_title=event_id).select_related('event').prefetch_related('credit_expenses', 'debit_expenses')

        if not proposals:
            return Response({'detail': 'No budget proposals found for this event.'}, status=status.HTTP_404_NOT_FOUND)
    
        event = proposals.first().event
        currency = 'GBP'

        total_estimated = sum(
            p.total_debits.amount for p in proposals if p.total_debits
        )
        total_outgoing = sum(
            p.total_credits.amount for p in proposals if p.total_credits
        )

        real_result = Payment.objects.filter(
            event=event,
            status=PaymentStatusChoices.COMPLETED,
        ).aggregate(total=DbSum('base_amount'))
        real_inbound = real_result.get('total') or 0

        net_estimated = total_estimated - total_outgoing
        net_real = real_inbound - total_outgoing
        variance = real_inbound - total_estimated

        if real_inbound == 0 and total_outgoing == 0:
            health = 'UNKNOWN'
        elif net_real > 0:
            health = 'SURPLUS'
        elif net_real == 0:
            health = 'BREAK_EVEN'
        else:
            health = 'DEFICIT'

        data = {
            'event_id': event.event_id if event else None,
            'event_name': event.title if event else None,
            'proposal_count': proposals.count(),
            'total_estimated_inbound': total_estimated,
            'total_real_inbound': real_inbound,
            'total_outgoing': total_outgoing,
            'net_estimated': net_estimated,
            'net_real': net_real,
            'variance': variance,
            'health_status': health,
            'currency': currency,
        }
        serializer = EventBudgetStatisticsSerializer(data)
        return Response(serializer.data)
