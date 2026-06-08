from rest_framework import viewsets, permissions, filters, exceptions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
import logging

from apps.payments.models import Payment, BankTransferEvidence
from apps.payments.api.serializers import (
    BankTransferEvidenceListSerializer, BankTransferEvidenceDetailSerializer,
    BankTransferEvidenceCreateSerializer, BankTransferEvidenceUpdateSerializer,)
from apps.payments.api.filtersets import BankTransferEvidenceFilterSet
from apps.payments.api.permissions import IsBankTransferEvidenceAccessible, user_can_manage_bank_evidence
from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
from apps.common.pagination import StandardPagination

import logging

logger = logging.getLogger(__name__)

@extend_schema_view(
    list=extend_schema(
        summary='List bank transfer evidence records',
        description=(
            'Retrieve a list of bank transfer evidence records. Access is scoped to payments the user can view. '
            'Supports filtering by verification status, event, and payment reference.'
        ),
        tags=['Bank Transfer Evidence'],
    ),
    retrieve=extend_schema(
        summary='Retrieve bank transfer evidence record',
        description='Get detailed information about a specific bank transfer evidence record.',
        tags=['Bank Transfer Evidence'],
    ),
    create=extend_schema(
        summary='Upload bank transfer evidence',
        description=(
            'Upload evidence for a bank transfer payment. Requires associated payment unless user is administrative. '
            'Evidence will be auto-matched to payments based on transfer ID when possible.'
        ),
        tags=['Bank Transfer Evidence'],
    ),
    update=extend_schema(
        summary='Update bank transfer evidence record',
        description='Update details of a bank transfer evidence record. Only possible before verification.',
        tags=['Bank Transfer Evidence'],
    ),
    partial_update=extend_schema(
        summary='Partially update bank transfer evidence record',
        description='Partially update details of a bank transfer evidence record. Only possible before verification.',
        tags=['Bank Transfer Evidence'],
    ),
    confirm_payment_match=extend_schema(
        summary='Confirm payment match for bank transfer evidence',
        description=(
            'Manually confirm that this bank transfer evidence matches its associated payment. '
            'If no payment is currently linked, the system will attempt to auto-match based on transfer ID.'
        ),
         request=None,
         responses={
             200: BankTransferEvidenceDetailSerializer,
             403: OpenApiResponse(description='Permission denied'),
         },
         tags=['Bank Transfer Evidence'],
     ),
     destroy=extend_schema(
         summary='Delete bank transfer evidence record',
         description='Delete a bank transfer evidence record. Only possible before verification.',
         tags=['Bank Transfer Evidence'],
     ),
)
class BankTransferEvidenceViewSet(viewsets.ModelViewSet):
    """CRUD viewset for bank transfer evidence uploads and confirmation."""

    queryset = BankTransferEvidence.objects.select_related('payment', 'verified_by', 'processed_by')
    permission_classes = [permissions.IsAuthenticated, IsBankTransferEvidenceAccessible]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BankTransferEvidenceFilterSet
    search_fields = ['transfer_id', 'payer_name', 'payment__payment_reference']
    ordering_fields = ['uploaded_at', 'updated_at', 'verification_status', 'auto_expiry_date']
    ordering = ['-uploaded_at']
    lookup_field = 'bank_transfer_id'

    def get_serializer_class(self):
        if self.action == 'list':
            return BankTransferEvidenceListSerializer
        if self.action == 'create':
            return BankTransferEvidenceCreateSerializer
        if self.action in ['update', 'partial_update']:
            return BankTransferEvidenceUpdateSerializer
        return BankTransferEvidenceDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        managed_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).values_list('event_id', flat=True)

        finance_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__name__icontains='finance'
        ).values_list('event_id', flat=True)

        return queryset.filter(
            Q(payment__user=user) |
            Q(payment__event_id__in=managed_event_ids) |
            Q(payment__event_id__in=finance_event_ids)
        ).distinct()

    def perform_create(self, serializer):
        payment = serializer.validated_data.get('payment')
        if payment and not user_can_manage_bank_evidence(self.request.user, payment.event) and payment.user != self.request.user:
            raise exceptions.PermissionDenied('You do not have permission to attach evidence to this payment.')

        if not payment and not self.request.user.is_superuser and not self.request.user.is_staff:
            raise exceptions.PermissionDenied('A payment is required unless you are an administrative user.')

        serializer.save()

    @action(detail=True, methods=['post'])
    def confirm_payment_match(self, request, bank_transfer_id=None):
        evidence = self.get_object()

        if not user_can_manage_bank_evidence(request.user, evidence.payment.event if evidence.payment else None):
            raise exceptions.PermissionDenied('You do not have permission to confirm this evidence record.')

        if not evidence.payment:
            matched_payment = Payment.objects.filter(bank_transfer_reference__icontains=evidence.transfer_id).first()
            if matched_payment:
                evidence.payment = matched_payment
                evidence.save(update_fields=['payment'])

        evidence.mark_verified(request.user)
        serializer = self.get_serializer(evidence)
        return Response(serializer.data)