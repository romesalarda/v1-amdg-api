from rest_framework import viewsets, permissions, filters
from django.db.models import Q
from drf_spectacular.utils import extend_schema_view, extend_schema
from apps.products.models import OrderItem
from apps.products.api.serializers import OrderItemSerializer
from apps.common.pagination import StandardPagination
from apps.products.api.permissions import IsOrderOwnerOrAdministrative

@extend_schema_view(
    list=extend_schema(
        summary="List order items",
        description="Retrieve a paginated list of order items. Access controlled by order ownership.",
        tags=["Order Items"],
    ),
    retrieve=extend_schema(
        summary="Retrieve order item details",
        description="Get detailed information about a specific order item.",
        tags=["Order Items"],
    ),
)
class OrderItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for OrderItem.
    
    Order items are created and managed through the Order viewset.
    This viewset provides read-only access for viewing items.
    
    Permissions:
    - Read: Order owner or administrative staff
    """
    
    queryset = OrderItem.objects.select_related(
        'order', 'order__customer', 'order__attendee', 'product_variant', 'product_variant__product'
    )
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsOrderOwnerOrAdministrative]
    pagination_class = StandardPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['order__created_at', 'quantity', 'total_price']
    ordering = ['-order__created_at']
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all order items
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see only their own order items
        return queryset.filter(
            Q(order__customer=user) |
            Q(order__attendee__user=user)
        )
