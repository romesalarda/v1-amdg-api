from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from apps.payments.models import PaymentHistoryAction
from apps.payments.api.serializers import PaymentHistoryActionSerializer
from apps.payments.api.filtersets import PaymentHistoryActionFilterSet
from apps.payments.api.permissions import IsAdministrativeStaffOnly
from apps.common.pagination import StandardPagination

@extend_schema_view(
    list=extend_schema(
        summary="List payment history actions",
        description="List payment history. Only accessible by administrative staff.",
        tags=["Payment History"],
    ),
    retrieve=extend_schema(
        summary="Retrieve payment history action",
        description=(
            "Get detailed information about a specific payment history action including "
            "action type, timestamp, performer, and associated metadata for audit trails."
        ),
        tags=["Payment History"],
    )
)
class PaymentHistoryActionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for PaymentHistoryAction model.
    
    Permissions: Administrative staff only
    Provides audit trail of payment actions.
    """
    
    queryset = PaymentHistoryAction.objects.select_related('payment', 'performed_by')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    serializer_class = PaymentHistoryActionSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PaymentHistoryActionFilterSet
    search_fields = ['description', 'notes', 'action']
    ordering_fields = ['timestamp', 'action']
    ordering = ['-timestamp']
