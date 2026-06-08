from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
# Import models
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.bookings.models import (
    BookingPackage, PackageProduct,
)
from apps.common.api.serializers import AvailabilityWindowSerializer
from apps.bookings.api.serializers import (
    BookingPackageListSerializer, BookingPackageDetailSerializer, BookingPackageCreateUpdateSerializer,
    BookingPackageRuleSerializer,
    PackageProductSerializer, PackageProductCreateUpdateSerializer,
)
from apps.bookings.api.filtersets import BookingPackageFilterSet
from apps.bookings.api.permissions import IsAdministrativeStaff
from apps.bookings.api.pagination import StandardPagination

import logging
logger = logging.getLogger(__name__)

@extend_schema_view(
    list=extend_schema(
        summary="List booking packages",
        description="Retrieve a list of booking packages. Filter by event, ticket type, or eligibility.",
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='eligible_for_attendee',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Filter packages eligible for specific attendee UUID',
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve booking package details",
        description="Get detailed information about a specific booking package including rules.",
        tags=["Booking Packages"],
    ),
    create=extend_schema(
        summary="Create booking package",
        description="Create a new booking package with optional rules. Requires administrative access.",
        tags=["Booking Packages"],
    ),
    update=extend_schema(
        summary="Update booking package",
        description="Update an existing booking package. Requires administrative access.",
        tags=["Booking Packages"],
    ),
    partial_update=extend_schema(
        summary="Partially update booking package",
        description="Partially update a booking package. Requires administrative access.",
        tags=["Booking Packages"],
    ),
    destroy=extend_schema(
        summary="Delete booking package",
        description="Delete a booking package. Requires administrative access.",
        tags=["Booking Packages"],
    ),
)
class BookingPackageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing booking packages.
    
    Provides:
    - List/Retrieve: Any authenticated user can view packages
    - Create/Update/Delete: Administrative staff only
    - Eligibility filtering: Check if packages apply to specific attendees
    
    Permissions:
    - List/Retrieve: Authenticated users
    - Create/Update/Delete: Administrative staff
    """
    
    queryset = BookingPackage.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingPackageFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name', 'base_amount']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return BookingPackageListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return BookingPackageCreateUpdateSerializer
        return BookingPackageDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action in ['list', 'retrieve', 'rules', 'package_products']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdministrativeStaff()]
    
    def get_queryset(self):
        """Optimize queryset with select_related and prefetch rules."""
        return super().get_queryset().select_related(
            'event', 'ticket_type', 'created_by'
        ).prefetch_related('rules')
    
    def destroy(self, request, *args, **kwargs):
        """
        Override destroy to prevent deletion if packages are linked to existing bookings.
        """
        instance = self.get_object()
        if instance.can_delete is False:
            return Response(
                {'detail': 'Cannot delete booking package linked to existing bookings.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)
        
    @extend_schema(
        summary="List rules for booking package",
        description="Retrieve all rules associated with this booking package.",
        tags=["Booking Packages"],
        responses={200: BookingPackageRuleSerializer(many=True)},
        operation_id="bookings_package_rules_list",
    )
    @action(detail=True, methods=['get'], url_path='rules')
    def rules(self, request, pk=None):
        """Return all rules for this booking package."""
        package = self.get_object()
        rules = package.rules.filter(active=True)
        serializer = BookingPackageRuleSerializer(rules, many=True, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        methods=['GET'],
        summary="List package products",
        description="Retrieve products linked to this booking package.",
        tags=["Booking Packages"],
        responses={200: PackageProductSerializer(many=True)},
        operation_id="bookings_package_products_list",
    )
    @extend_schema(
        methods=['POST'],
        summary="Add product to booking package",
        description="Link an event product to this booking package with quantity and package-specific percentage modifier.",
        tags=["Booking Packages"],
        request=PackageProductCreateUpdateSerializer,
        responses={
            201: PackageProductSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Permission denied')
        },
        operation_id="bookings_package_products_create",
    )
    @action(detail=True, methods=['get', 'post'], url_path='products', permission_classes=[permissions.IsAuthenticated])
    def package_products(self, request, pk=None):
        """List or create package-product links for the booking package."""
        package = self.get_object()

        if request.method == 'GET':
            products = package.package_products.select_related('product', 'booking_package', 'added_by').order_by('-added_at')
            paginated = self.paginate_queryset(products)
            if paginated is not None:
                serializer = PackageProductSerializer(paginated, many=True, context={'request': request})
                return self.get_paginated_response(serializer.data)
            serializer = PackageProductSerializer(products, many=True, context={'request': request})
            return Response(serializer.data)

        if not IsAdministrativeStaff().has_permission(request, self):
            return Response({'detail': 'You do not have permission to perform this action.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = PackageProductCreateUpdateSerializer(
            data=request.data,
            context={'request': request, 'booking_package': package},
        )
        serializer.is_valid(raise_exception=True)
        package_product = serializer.save()
        response_serializer = PackageProductSerializer(package_product, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        methods=['PATCH'],
        summary="Partially update package product",
        description="Partially update a linked product for this booking package.",
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='package_product_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                required=True,
                description='Database ID of the PackageProduct link to update.',
            )
        ],
        request=PackageProductCreateUpdateSerializer,
        responses={
            200: PackageProductSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Package product not found'),
        },
        operation_id="bookings_package_products_partial_update",
    )
    @extend_schema(
        methods=['PUT'],
        summary="Update package product",
        description="Fully update a linked product for this booking package.",
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='package_product_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                required=True,
                description='Database ID of the PackageProduct link to update.',
            )
        ],
        request=PackageProductCreateUpdateSerializer,
        responses={
            200: PackageProductSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Package product not found'),
        },
        operation_id="bookings_package_products_update",
    )
    @extend_schema(
        methods=['DELETE'],
        summary="Remove product from booking package",
        description="Delete a linked package product from this booking package.",
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='package_product_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                required=True,
                description='Database ID of the PackageProduct link to delete.',
            )
        ],
        responses={
            204: OpenApiResponse(description='Deleted successfully'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Package product not found'),
        },
        operation_id="bookings_package_products_destroy",
    )
    @action(
        detail=True,
        methods=['patch', 'put', 'delete'],
        url_path=r'products/(?P<package_product_id>[^/.]+)',
        permission_classes=[permissions.IsAuthenticated],
    )
    def package_product_detail(self, request, pk=None, package_product_id=None):
        """Update or delete a specific package-product link."""
        if not IsAdministrativeStaff().has_permission(request, self):
            return Response({'detail': 'You do not have permission to perform this action.'}, status=status.HTTP_403_FORBIDDEN)

        package = self.get_object()
        package_product = get_object_or_404(
            PackageProduct.objects.select_related('product', 'booking_package', 'added_by'),
            id=package_product_id,
            booking_package=package,
        )

        if request.method == 'DELETE':
            package_product.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = PackageProductCreateUpdateSerializer(
            package_product,
            data=request.data,
            partial=(request.method == 'PATCH'),
            context={'request': request, 'booking_package': package},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        response_serializer = PackageProductSerializer(updated, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Add discount to booking package",
        description=(
            "Create a discount specifically for this booking package. "
            "The discount will be automatically linked to this package. "
            "Administrative staff only."
        ),
        tags=["Booking Packages"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Discount name'},
                    'description': {'type': 'string', 'description': 'Optional description'},
                    'discount_type': {'type': 'string', 'enum': ['PERCENTAGE', 'FIXED']},
                    'percentage': {'type': 'string', 'description': 'Percentage value (0-100) for percentage discounts'},
                    'amount': {'type': 'string', 'description': 'Fixed amount for fixed discounts'},
                    'active': {'type': 'boolean', 'default': True},
                },
                'required': ['name', 'discount_type'],
            }
        },
        responses={
            201: {'description': 'Discount created successfully'},
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied'},
        },
        operation_id="bookings_package_add_discount",
    )
    @action(detail=True, methods=['post'], url_path='discounts', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaff])
    def add_discount(self, request, pk=None):
        """Add a discount to this booking package."""
        from apps.payments.models import Discount, DiscountType
        from apps.payments.api.serializers import DiscountDetailSerializer
        from django.contrib.contenttypes.models import ContentType
        from djmoney.money import Money
        from decimal import Decimal
        
        package = self.get_object()
        
        # Validate required fields
        name = request.data.get('name')
        discount_type = request.data.get('discount_type')
        
        if not name:
            return Response(
                {'name': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not discount_type or discount_type not in ['PERCENTAGE', 'FIXED']:
            return Response(
                {'discount_type': ['Must be either PERCENTAGE or FIXED.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate type-specific fields
        if discount_type == 'PERCENTAGE':
            percentage = request.data.get('percentage')
            if not percentage:
                return Response(
                    {'percentage': ['Percentage is required for percentage discounts.']},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                percentage_val = Decimal(str(percentage))
                if not (0 <= percentage_val <= 100):
                    return Response(
                        {'percentage': ['Percentage must be between 0 and 100.']},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except (ValueError, TypeError):
                return Response(
                    {'percentage': ['Invalid percentage value.']},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif discount_type == 'FIXED':
            amount = request.data.get('amount')
            if not amount:
                return Response(
                    {'amount': ['Amount is required for fixed discounts.']},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                amount_val = Decimal(str(amount))
                if amount_val <= 0:
                    return Response(
                        {'amount': ['Amount must be greater than zero.']},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except (ValueError, TypeError):
                return Response(
                    {'amount': ['Invalid amount value.']},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Create discount with automatic target linkage
        try:
            discount_data = {
                'name': name,
                'description': request.data.get('description', ''),
                'discount_type': discount_type,
                'target_type': ContentType.objects.get_for_model(BookingPackage),
                'target_id': package.id,
                'active': request.data.get('active', True),
                'created_by': request.user,
            }
            
            if discount_type == 'PERCENTAGE':
                discount_data['percentage'] = Decimal(str(request.data.get('percentage')))
            else:
                discount_data['amount'] = Money(Decimal(str(request.data.get('amount'))), 'GBP')
            
            discount = Discount.objects.create(**discount_data)
            
            serializer = DiscountDetailSerializer(discount, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @extend_schema(
        summary="List availability windows for booking package",
        description="Retrieve all availability windows associated with this booking package.",
        tags=["Booking Packages"],
        responses={200: AvailabilityWindowSerializer(many=True)},
        operation_id="bookings_package_availability_windows_list",
    )
    @action(detail=True, methods=['get'], url_path='availability-windows')
    def availability_windows(self, request, pk=None):
        """Return all availability windows for this booking package."""
        package = self.get_object()
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        
        windows = package.availability_windows.all()
        paginated = self.paginate_queryset(windows)
        if paginated is not None:
            serializer = AvailabilityWindowSerializer(paginated, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = AvailabilityWindowSerializer(windows, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Add availability window to booking package",
        description=(
            "Add a new availability window to the booking package defining when it's available for booking. "
            "Specify start and end times to control package visibility and bookability. "
            "Only administrative staff can add availability windows."
        ),
        tags=["Booking Packages"],
        request=AvailabilityWindowSerializer,
        responses={
            201: AvailabilityWindowSerializer,
            400: OpenApiResponse(description='Validation errors'),
            403: OpenApiResponse(description='Permission denied')
        },
        operation_id="bookings_package_add_availability_window",
    )
    @action(detail=True, methods=['post'], url_path='add-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaff])
    def add_availability_window(self, request, pk=None):
        """Add an availability window to this booking package."""
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        from django.contrib.contenttypes.models import ContentType
        
        package = self.get_object()
        
        serializer = AvailabilityWindowSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(BookingPackage)
            window = serializer.save(
                target_type=content_type,
                target_id=package.id
            )
            return Response(
                AvailabilityWindowSerializer(window, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        methods=['PATCH'],
        summary="Partially update availability window for booking package",
        description=(
            "Partially update an existing availability window for the booking package. "
            "Only administrative staff can update availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to update',
                required=True
            )
        ],
        request=AvailabilityWindowSerializer,
        responses={
            200: AvailabilityWindowSerializer,
            400: OpenApiResponse(description='Invalid data or missing window_id'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Window not found')
        },
        operation_id="bookings_package_update_availability_window",
    )
    @extend_schema(
        methods=['PUT'],
        summary="Fully update availability window for booking package",
        description=(
            "Fully update an existing availability window for the booking package. "
            "Only administrative staff can update availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to update',
                required=True
            )
        ],
        request=AvailabilityWindowSerializer,
        responses={
            200: AvailabilityWindowSerializer,
            400: OpenApiResponse(description='Invalid data or missing window_id'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Window not found')
        },
        operation_id="bookings_package_update_availability_window_full",
    )
    @action(detail=True, methods=['patch', 'put'], url_path='update-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaff])
    def update_availability_window(self, request, pk=None):
        """Update an existing availability window for the booking package."""
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        from django.contrib.contenttypes.models import ContentType
        
        package = self.get_object()
        
        window_id = request.query_params.get('window_id') or request.data.get('availability_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter or availability_id in request body is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            content_type = ContentType.objects.get_for_model(BookingPackage)
            window = AvailabilityWindow.objects.get(
                availability_id=window_id,
                target_id=package.id,
                target_type=content_type
            )
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this booking package"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = AvailabilityWindowSerializer(
            window,
            data=request.data,
            partial=(request.method == 'PATCH'),
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Remove availability window from booking package",
        description=(
            "Remove an availability window from the booking package by its window ID. "
            "Permanently deletes the window. "
            "Only administrative staff can remove availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Booking Packages"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to remove',
                required=True
            )
        ],
        responses={
            204: OpenApiResponse(description='Window removed successfully'),
            400: OpenApiResponse(description='Bad request - missing window_id'),
            403: OpenApiResponse(description='Permission denied'),
            404: OpenApiResponse(description='Window not found')
        },
        operation_id="bookings_package_remove_availability_window",
    )
    @action(detail=True, methods=['delete'], url_path='remove-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaff])
    def remove_availability_window(self, request, pk=None):
        """Remove an availability window from this booking package."""
        from apps.common.models import AvailabilityWindow
        
        package = self.get_object()
        
        window_id = request.query_params.get('window_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            window = AvailabilityWindow.objects.get(availability_id=window_id, target_id=package.id)
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this booking package"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        window.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)