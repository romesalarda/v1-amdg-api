from rest_framework import viewsets, status, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from apps.payments.models import PaymentMethod
from apps.payments.api.serializers import (
    PaymentMethodSerializer, PaymentMethodDetailSerializer, PaymentMethodCreateUpdateSerializer,
)
from apps.payments.api.filtersets import PaymentMethodFilterSet
from apps.payments.api.permissions import IsAdministrativeStaffOnly
from apps.common.pagination import StandardPagination

@extend_schema_view(
    list=extend_schema(
        summary="List payment methods",
        description="Retrieve all payment methods. Only accessible by administrative staff.",
        tags=["Payment Methods"],
    ),
    retrieve=extend_schema(
        summary="Retrieve payment method",
        description="Get detailed information about a specific payment method.",
        tags=["Payment Methods"],
    ),
    create=extend_schema(
        summary="Create payment method",
        description="Create a new payment method for an event. Only admins.",
        tags=["Payment Methods"],
    ),
    update=extend_schema(
        summary="Update payment method",
        description=(
            "Update a payment method with complete payload. "
            "Use PATCH for partial updates. Only administrative staff can update payment methods."
        ),
        tags=["Payment Methods"],
    ),
    partial_update=extend_schema(
        summary="Partially update payment method",
        description=(
            "Partially update a payment method such as changing status or configuration. "
            "Only administrative staff can update payment methods."
        ),
        tags=["Payment Methods"],
    ),
    destroy=extend_schema(
        summary="Delete payment method",
        description=(
            "Delete a payment method. Use with caution as this affects payment processing. "
            "Only administrative staff can delete payment methods."
        ),
        tags=["Payment Methods"],
    )
)
class PaymentMethodViewSet(viewsets.ModelViewSet):
    """
    ViewSet for PaymentMethod model operations.
    
    Permissions: Administrative staff only
    All operations restricted to admins for security and control.
    """
    
    queryset = PaymentMethod.objects.select_related('event', 'created_by')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PaymentMethodFilterSet
    search_fields = ['title', 'code', 'description']
    ordering_fields = ['created_at', 'title', 'method_type']
    ordering = ['-created_at']
    lookup_field = 'method_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return PaymentMethodSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return PaymentMethodCreateUpdateSerializer
        return PaymentMethodDetailSerializer
    
    def perform_create(self, serializer):
        """Set created_by to current user."""
        serializer.save(created_by=self.request.user)