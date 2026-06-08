from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema_view, extend_schema
from apps.products.models import ProductCategory, EventProductCategory
from apps.products.api.serializers import (
    ProductCategorySerializer,
    ProductCategoryCreateUpdateSerializer,
    EventProductCategorySerializer,
    EventProductCategoryCreateUpdateSerializer,
)
from apps.common.pagination import StandardPagination
from apps.products.api.permissions import CanManageCategories
from apps.products.api.filtersets import ProductCategoryFilterSet, EventProductCategoryFilterSet

@extend_schema_view(
    list=extend_schema(
        summary="List product categories",
        description="Retrieve a paginated list of all product categories. Categories are global across all events.",
        tags=["Product Categories"],
    ),
    retrieve=extend_schema(
        summary="Retrieve category details",
        description="Get detailed information about a specific product category.",
        tags=["Product Categories"],
    ),
    create=extend_schema(
        summary="Create a new category",
        description="Create a new product category. Requires category management permissions.",
        tags=["Product Categories"],
    ),
    update=extend_schema(
        summary="Update category",
        description="Update an existing product category. Requires category management permissions.",
        tags=["Product Categories"],
    ),
    partial_update=extend_schema(
        summary="Partially update category",
        description="Partially update an existing product category. Requires category management permissions.",
        tags=["Product Categories"],
    ),
)
class ProductCategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing product categories.
    
    Provides:
    - List/Retrieve: All authenticated users
    
    Categories are global and can be associated with events through EventProductCategory.
    """
    
    queryset = ProductCategory.objects.all()
    permission_classes = [permissions.IsAuthenticated, CanManageCategories]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductCategoryFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    serializer_class = ProductCategorySerializer

    def get_serializer_class(self):
        """Use stricter serializer for writes while keeping rich read responses."""
        if self.action in ['create', 'update', 'partial_update']:
            return ProductCategoryCreateUpdateSerializer
        return ProductCategorySerializer
    

@extend_schema_view(
    list=extend_schema(
        summary="List event-category associations",
        description="Retrieve a paginated list of event-category associations.",
        tags=["Product Categories"],
    ),
    retrieve=extend_schema(
        summary="Retrieve association details",
        description="Get detailed information about a specific event-category association.",
        tags=["Product Categories"],
    ),
    create=extend_schema(
        summary="Associate category with event",
        description="Create a new event-category association. Event administrators can manage their event's categories.",
        tags=["Product Categories"],
    ),
    destroy=extend_schema(
        summary="Remove category from event",
        description="Delete an event-category association.",
        tags=["Product Categories"],
    ),
)
class EventProductCategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event-category associations.
    
    Provides:
    - List/Retrieve: All authenticated users
    - Create/Delete: Event administrators
    
    Note: Update is not supported - delete and recreate instead.
    """
    
    queryset = EventProductCategory.objects.select_related('event', 'category')
    permission_classes = [permissions.IsAuthenticated, CanManageCategories]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventProductCategoryFilterSet
    search_fields = ['event__title', 'category__name']
    ordering_fields = ['added_at', 'event__title', 'category__name']
    ordering = ['-added_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']  # No PUT/PATCH
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'create':
            return EventProductCategoryCreateUpdateSerializer
        return EventProductCategorySerializer
