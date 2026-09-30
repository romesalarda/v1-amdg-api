from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import OuterRef, Subquery
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)

from apps.payments.api.permissions import (
    resolve_event_from_request, user_can_access_event_payments,
)

from apps.products.models import StockAuditLog
from apps.payments.models import Payment
from apps.payments.api.serializers import StockAuditLogSerializer
from apps.payments.api.filtersets import StockAuditLogFilterSet
from apps.payments.api.permissions import permissions
from apps.common.pagination import StandardPagination
from apps.events.models import Event

@extend_schema_view(
    list=extend_schema(
        summary='List stock audit logs',
        description=(
            'Retrieve stock audit logs. List access is event-scoped and requires event_id. '
            'Regular users only see logs tied to their own payments.'
        ),
        tags=['Stock Audit'],
    ),
    retrieve=extend_schema(
        summary='Retrieve stock audit log',
        description='Get a single stock audit log entry with inferred payment and event metadata.',
        tags=['Stock Audit'],
    )
)
class StockAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only StockAuditLog endpoint with event-scoped list responses."""

    queryset = StockAuditLog.objects.select_related('product_variant', 'product_variant__product', 'actor')
    permission_classes = [permissions.IsAuthenticated]  # Custom filtering in get_queryset enforces access control
    serializer_class = StockAuditLogSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = StockAuditLogFilterSet
    search_fields = ['notes', 'webhook_event_id', 'change_reason']
    ordering_fields = ['created_at', 'change_amount', 'new_quantity']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        payment_subquery = Payment.objects.filter(
            payment_id=OuterRef('payment_id')
        )

        queryset = queryset.annotate(
            payment_owner_id=Subquery(payment_subquery.values('user_id')[:1]),
            payment_event_id=Subquery(payment_subquery.values('event__event_id')[:1]),
            payment_event_title=Subquery(payment_subquery.values('event__title')[:1]),
            payment_reference_annotated=Subquery(payment_subquery.values('payment_reference')[:1]),
        )

        event = resolve_event_from_request(self.request)

        if event and user_can_access_event_payments(user, event):
            return queryset.filter(payment_event_id=event.event_id).distinct()
        
        return queryset.none()