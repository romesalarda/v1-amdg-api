"""
Production-grade viewsets for the products app.

Provides comprehensive viewsets for product management with proper validation,
business logic separation, schema configuration, nested routes, custom actions,
and permission classes.

ViewSets:
    - ProductCategoryViewSet: Manage product categories (admin only create/update/delete)
    - EventProductCategoryViewSet: Manage event-category associations
    - ProductViewSet: Full CRUD for products with nested variants route and image management
    - ProductVariantViewSet: Manage product variants with stock operations (nested under products)
    - OrderViewSet: Manage orders with item management and status transitions
    - OrderItemViewSet: Read-only order items (managed through orders)

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch, Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiExample,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any

from apps.products.models import (
    Product, ProductVariant,
    Order, OrderItem, OrderStatusChoices, OPEN_ORDER_STATUSES,
    ProductCategory, EventProductCategory
)
from apps.common.models import Resource
from apps.payments.models import Discount, DiscountRule
from apps.payments.api.serializers import (
    DiscountListSerializer, DiscountDetailSerializer, DiscountCreateUpdateSerializer
)
from .serializers import (
    ProductCategorySerializer, ProductCategoryCreateUpdateSerializer,
    EventProductCategorySerializer, EventProductCategoryCreateUpdateSerializer,
    ProductListSerializer, ProductDetailSerializer, ProductCreateSerializer, ProductUpdateSerializer,
    ProductVariantListSerializer, ProductVariantDetailSerializer, ProductVariantCreateUpdateSerializer,
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer, OrderUpdateSerializer,
    OrderItemSerializer, OrderItemCreateSerializer,
)
from .filtersets import (
    ProductCategoryFilterSet, EventProductCategoryFilterSet,
    ProductFilterSet, ProductVariantFilterSet, OrderFilterSet,
)
from .permissions import (
    IsAdministrativeStaff, IsAdministrativeStaffOnly,
    IsOrderOwnerOrAdministrative, IsReadOnly,
    CanManageProducts, CanManageCategories,
)
from apps.payments.evaluator import discount_applies as _discount_applies
from apps.payments.models.discounts import DiscountType as _DiscountType
from djmoney.money import Money

import decimal

User = get_user_model()


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration for product endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class PurchaseContextMixin:
    """Resolve optional attendee/customer context for serializer output enrichment."""

    def _user_has_attendee_access(self, attendee, user):
        if user.is_superuser or user.is_staff:
            return True

        attendee_owner_match = attendee.user_id == user.id
        attendee_booking_match = bool(
            attendee.booking_id and attendee.booking and attendee.booking.made_by_id == user.id
        )
        return attendee_owner_match or attendee_booking_match

    def _resolve_effective_customer(self):
        request_user = self.request.user
        customer_id = self.request.query_params.get('customer_id')

        if not customer_id or not (request_user.is_superuser or request_user.is_staff):
            return request_user

        try:
            return User.objects.get(pk=customer_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return request_user

    def _resolve_attendee_context(self, effective_customer):
        attendee_id = self.request.query_params.get('attendee_id')
        if not attendee_id:
            return None, False

        from apps.attendee.models import Attendee

        attendee = (
            Attendee.objects
            .select_related('booking', 'event', 'user')
            .filter(attendee_id=attendee_id)
            .first()
        )
        if attendee is None:
            return None, False

        if not self._user_has_attendee_access(attendee, effective_customer):
            return None, False

        requested_customer = self.request.query_params.get('customer_id')
        if requested_customer and (self.request.user.is_superuser or self.request.user.is_staff):
            attendee_owner_match = attendee.user_id == effective_customer.id
            attendee_booking_match = bool(
                attendee.booking_id and attendee.booking and attendee.booking.made_by_id == effective_customer.id
            )
            if not attendee_owner_match and not attendee_booking_match:
                return None, False

        return attendee, True

    def _build_purchase_context(self):
        effective_customer = self._resolve_effective_customer()
        attendee, context_enabled = self._resolve_attendee_context(effective_customer)
        return {
            'context_enabled': context_enabled,
            'context_customer': effective_customer,
            'context_attendee': attendee,
        }


# ============================================================================
# PRODUCT CATEGORY VIEWSETS
# ============================================================================

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


# ============================================================================
# PRODUCT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List products",
        description="Retrieve a paginated list of products. Supports extensive filtering for e-commerce-style search including price ranges, categories, stock availability, and full-text search.",
        parameters=[
            OpenApiParameter(
                name='attendee_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Optional attendee UUID to enable attendee-specific pricing and eligibility context.',
                required=False,
            ),
            OpenApiParameter(
                name='customer_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional customer identifier override (admin/staff only).',
                required=False,
            ),
        ],
        tags=["Products"],
        examples=[
            OpenApiExample(
                'Filter by event and category',
                value={'event': 123, 'category': '1,2', 'in_stock': True},
                request_only=True,
            ),
            OpenApiExample(
                'Price range search',
                value={'min_price': 10, 'max_price': 50, 'is_active': True},
                request_only=True,
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve product details",
        description="Get detailed information about a specific product including images, variants, availability windows, and rules.",
        parameters=[
            OpenApiParameter(
                name='attendee_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Optional attendee UUID to enable attendee-specific pricing and eligibility context.',
                required=False,
            ),
            OpenApiParameter(
                name='customer_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional customer identifier override (admin/staff only).',
                required=False,
            ),
        ],
        tags=["Products"],
    ),
    create=extend_schema(
        summary="Create product",
        description="Create a new product. Event administrators can create products for their events. Supports image upload via multipart/form-data for direct file uploads (main_image and additional_images fields) instead of resource IDs.",
        tags=["Products"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'description': {'type': 'string'},
                    'event': {'type': 'integer'},
                    'base_amount': {'type': 'string'},
                    'base_amount_currency': {'type': 'string'},
                    'percentage_modifier': {'type': 'number'},
                    'verified': {'type': 'boolean'},
                    'is_active': {'type': 'boolean'},
                    'main_image': {'type': 'string', 'format': 'binary'},
                    'additional_images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                }
            }
        }
    ),
    update=extend_schema(
        summary="Update product",
        description="Update an existing product. Only administrators can modify products. Supports image upload via multipart/form-data for direct file uploads.",
        tags=["Products"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'description': {'type': 'string'},
                    'base_amount': {'type': 'string'},
                    'base_amount_currency': {'type': 'string'},
                    'percentage_modifier': {'type': 'number'},
                    'verified': {'type': 'boolean'},
                    'is_active': {'type': 'boolean'},
                    'main_image': {'type': 'string', 'format': 'binary'},
                    'additional_images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                }
            }
        }
    ),
    partial_update=extend_schema(
        summary="Partially update product",
        description="Partially update a product. Supports image upload via multipart/form-data for direct file uploads.",
        tags=["Products"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'description': {'type': 'string'},
                    'base_amount': {'type': 'string'},
                    'base_amount_currency': {'type': 'string'},
                    'percentage_modifier': {'type': 'number'},
                    'verified': {'type': 'boolean'},
                    'is_active': {'type': 'boolean'},
                    'main_image': {'type': 'string', 'format': 'binary'},
                    'additional_images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                }
            }
        }
    ),
    destroy=extend_schema(
        summary="Delete product",
        description="Delete a product. Only allowed if no orders reference this product's variants.",
        tags=["Products"],
    ),
)
class ProductViewSet(PurchaseContextMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing products.
    
    Provides:
    - List/Retrieve: All authenticated users
    - Create/Update/Delete: Event administrators
    - Custom actions: add_image, remove_image, toggle_active
    - Nested route: /products/list/{product_id}/variants/
    
    Permissions:
    - Read: Authenticated users
    - Write: Administrative staff for the event
    """
    
    queryset = Product.objects.select_related('event', 'added_by', 'last_updated_by').prefetch_related(
        'variants'
    )
    permission_classes = [permissions.IsAuthenticated, CanManageProducts]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilterSet
    search_fields = ['title', 'description', 'display_code']
    ordering_fields = ['added_at', 'title', 'base_amount']
    ordering = ['-added_at']
    lookup_field = 'product_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return ProductListSerializer
        elif self.action == 'create':
            return ProductCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ProductUpdateSerializer
        return ProductDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Admins see all products
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see only active products (unless they're event admins)
        # Event admins can see their event's products regardless of active status
        # For now, show all active products to authenticated users
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self._build_purchase_context())
        return context
    
    @extend_schema(
        summary="Add image to product",
        description="Upload an image file directly to the product. The file will be automatically converted to a Resource object and attached to the product. Supports JPEG, PNG, GIF, and WebP formats up to 10MB. If is_main is true, any existing main image will be replaced.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'image': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Image file to upload (JPEG, PNG, GIF, or WebP, max 10MB)'
                    },
                    'is_main': {
                        'type': 'string',
                        'description': 'Whether this should be the main product image (true/false, 1/0, yes/no)',
                        'default': 'false'
                    },
                },
                'required': ['image'],
            }
        },
        responses={
            200: {
                'description': 'Image added successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Image added to product Conference T-Shirt.',
                            'resource_id': 123,
                            'image_url': 'https://example.com/media/resources/images/product_image.png'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid image file or validation error',
                'content': {
                    'application/json': {
                        'example': {
                            'image': ['Image file size cannot exceed 10MB.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'}
        },
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='add-image')
    def add_image(self, request, product_id=None):
        """Add an image to the product."""
        product = self.get_object()
        image_file = request.FILES.get('image')
        is_main = request.data.get('is_main', 'false').lower() in ['true', '1', 'yes']
        
        if not image_file:
            raise ValidationError({'image': 'Image file is required.'})
        
        # Validate file size (max 10MB)
        if image_file.size > 10 * 1024 * 1024:
            raise ValidationError({'image': 'Image file size cannot exceed 10MB.'})
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        if hasattr(image_file, 'content_type') and image_file.content_type not in allowed_types:
            raise ValidationError({'image': 'Only JPEG, PNG, GIF, and WebP images are allowed.'})
        
        try:
            # Get content type for product
            content_type = ContentType.objects.get_for_model(Product)
            
            # Create Resource object for the image
            tag = 'PRODUCT_PHOTO_MAIN' if is_main else 'PRODUCT_PHOTO_SECONDARY'
            resource = Resource.objects.create(
                name=f"{product.title} - {'Main' if is_main else 'Additional'} Image",
                description=f"{'Main' if is_main else 'Additional'} product image for {product.title}",
                tag=tag,
                target_type=content_type,
                target_id=str(product.id),
                resource_type='IMAGE',
                image=image_file,
                added_by=request.user,
                public=True
            )
            
            product.add_product_image(resource, is_main=is_main)
            
            return Response({
                'status': 'success',
                'message': f'Image added to product {product.title}.',
                'resource_id': resource.id,
                'image_url': resource.image.url if resource.image else None
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Remove image from product",
        description="Remove an image resource from the product by providing the resource ID. The resource will be disassociated from the product.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'resource_id': {
                        'type': 'integer',
                        'description': 'ID of the image resource to remove'
                    },
                },
                'required': ['resource_id'],
            }
        },
        responses={
            200: {
                'description': 'Image removed successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Image removed from product Conference T-Shirt.'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid resource_id or validation error',
                'content': {
                    'application/json': {
                        'example': {
                            'resource_id': ['Resource ID is required.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Resource does not exist'}
        },
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='remove-image')
    def remove_image(self, request, product_id=None):
        """Remove an image from the product."""
        product = self.get_object()
        resource_id = request.data.get('resource_id')
        
        if not resource_id:
            raise ValidationError({'resource_id': 'Resource ID is required.'})
        
        try:
            resource = Resource.objects.get(id=resource_id)
            product.remove_product_image(resource)
            return Response({
                'status': 'success',
                'message': f'Image removed from product {product.title}.'
            }, status=status.HTTP_200_OK)
        except Resource.DoesNotExist:
            raise ValidationError({'resource_id': 'Resource does not exist.'})
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Toggle product active status",
        description="Toggle the is_active status of a product between true and false. Only administrators can perform this action. Active products are visible to regular users, inactive products are only visible to administrators.",
        request=None,
        responses={
            200: {
                'description': 'Status toggled successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'is_active': True,
                            'message': 'Product Conference T-Shirt is now active.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Product not found'}
        },
        tags=["Products"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_name='toggle-active', url_path='toggle-active')
    def toggle_active(self, request, product_id=None):
        """Toggle the is_active status of the product."""
        product = self.get_object()
        product.is_active = not product.is_active
        product.save()
        
        return Response({
            'status': 'success',
            'is_active': product.is_active,
            'message': f'Product {product.title} is now {"active" if product.is_active else "inactive"}.'
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="List product discounts",
        description="Retrieve all discounts associated with this product, filtered by the event. Returns a paginated list of active and inactive discounts with their rules and HATEOAS links.",
        parameters=[
            OpenApiParameter(
                name='active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter by active status'
            ),
        ],
        responses={
            200: {
                'description': 'Discounts retrieved successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'count': 2,
                            'next': None,
                            'previous': None,
                            'results': [
                                {
                                    'id': 1,
                                    'discount_id': 'uuid-here',
                                    'name': 'Early Bird Discount',
                                    'discount_type': 'PERCENTAGE',
                                    'discount_value': '20%',
                                    'percentage': '20.00',
                                    'amount': None,
                                    'active': True,
                                    'rules': [],
                                    '_links': {
                                        'self': '/api/products/list/1/discounts/uuid-here/',
                                        'product': '/api/products/list/1/',
                                        'update': '/api/products/list/1/update-discount/uuid-here/',
                                        'delete': '/api/products/list/1/remove-discount/uuid-here/'
                                    }
                                }
                            ],
                            '_links': {
                                'self': '/api/products/list/1/discounts/',
                                'product': '/api/products/list/1/',
                                'add_discount': '/api/products/list/1/add-discount/'
                            }
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires authentication'},
            404: {'description': 'Product not found'}
        },
        tags=["Products", "Discounts"],
    )
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated], url_path='discounts')
    def list_discounts(self, request, product_id=None):
        """List all discounts for this product."""
        product = self.get_object()
        
        # Get ContentType for Product
        content_type = ContentType.objects.get_for_model(Product)
        
        # Query discounts targeting this product
        queryset = Discount.objects.filter(
            target_type=content_type,
            target_id=product.id
        ).select_related('created_by').prefetch_related('rules')
        
        # Filter by active status if provided
        active_filter = request.query_params.get('active')
        if active_filter is not None:
            active_filter = active_filter.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(active=active_filter)
        
        # Serialize discounts
        serializer = DiscountListSerializer(queryset, many=True, context={'request': request})
        
        # Build HATEOAS links
        results = serializer.data
        for discount_data in results:
            discount_id = discount_data.get('discount_id')
            discount_data['_links'] = {
                'self': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/discounts/{discount_id}/'
                ),
                'product': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/'
                ),
                'update': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/update-discount/{discount_id}/'
                ),
                'delete': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/remove-discount/{discount_id}/'
                )
            }
        
        return Response({
            'count': len(results),
            'next': None,
            'previous': None,
            'results': results,
            '_links': {
                'self': request.build_absolute_uri(),
                'product': request.build_absolute_uri(f'/api/products/list/{product.product_id}/'),
                'add_discount': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/add-discount/'
                )
            }
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Add discount to product",
        description="Create a new discount for this product or associate an existing discount. Supports creating discounts with nested rules (maximum 2). The ContentType and target_id are automatically set based on the product. Rules can be edited separately after creation.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'discount_id': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'Optional: UUID of existing discount to associate',
                        'nullable': True
                    },
                    'name': {
                        'type': 'string',
                        'description': 'Discount name',
                        'example': 'Early Bird Special'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Discount description',
                        'nullable': True
                    },
                    'discount_type': {
                        'type': 'string',
                        'enum': ['PERCENTAGE', 'FIXED'],
                        'description': 'Type of discount'
                    },
                    'percentage': {
                        'type': 'string',
                        'description': 'Percentage value (required if discount_type is PERCENTAGE)',
                        'example': '20.00',
                        'nullable': True
                    },
                    'amount': {
                        'type': 'string',
                        'description': 'Fixed amount (required if discount_type is FIXED)',
                        'example': '10.00',
                        'nullable': True
                    },
                    'active': {
                        'type': 'boolean',
                        'description': 'Whether discount is active',
                        'default': True
                    },
                    'rules': {
                        'type': 'array',
                        'description': 'Optional discount rules (maximum 2)',
                        'maxItems': 2,
                        'items': {
                            'type': 'object',
                            'properties': {
                                'rule_type': {'type': 'string'},
                                'name': {'type': 'string'},
                                'description': {'type': 'string', 'nullable': True},
                                'value': {'type': 'string', 'nullable': True}
                            }
                        }
                    }
                },
                'required': ['name', 'discount_type']
            }
        },
        responses={
            201: {
                'description': 'Discount created successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'id': 1,
                            'discount_id': 'uuid-here',
                            'name': 'Early Bird Discount',
                            'discount_type': 'PERCENTAGE',
                            'discount_value': '20%',
                            'percentage': '20.00',
                            'amount': None,
                            'active': True,
                            'rules': [],
                            '_links': {
                                'self': '/api/products/list/1/discounts/uuid-here/',
                                'product': '/api/products/list/1/',
                                'update': '/api/products/list/1/update-discount/uuid-here/',
                                'delete': '/api/products/list/1/remove-discount/uuid-here/',
                                'list_discounts': '/api/products/list/1/discounts/'
                            }
                        }
                    }
                }
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Product not found'}
        },
        tags=["Products", "Discounts"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='add-discount')
    def add_discount(self, request, product_id=None):
        """Create a new discount for this product or associate an existing one."""
        product = self.get_object()
        discount_id = request.data.get('discount_id')
        
        # Get ContentType for Product
        content_type = ContentType.objects.get_for_model(Product)
        
        if discount_id:
            # Associate existing discount
            try:
                discount = Discount.objects.get(discount_id=discount_id)
                # Update target to this product
                discount.target_type = content_type
                discount.target_id = product.id
                discount.save()
                
                serializer = DiscountDetailSerializer(discount, context={'request': request})
                discount_data = serializer.data
                
                # Add HATEOAS links
                discount_data['_links'] = {
                    'self': request.build_absolute_uri(
                        f'/api/products/list/{product.product_id}/discounts/{discount.discount_id}/'
                    ),
                    'product': request.build_absolute_uri(
                        f'/api/products/list/{product.product_id}/'
                    ),
                    'update': request.build_absolute_uri(
                        f'/api/products/list/{product.product_id}/update-discount/{discount.discount_id}/'
                    ),
                    'delete': request.build_absolute_uri(
                        f'/api/products/list/{product.product_id}/remove-discount/{discount.discount_id}/'
                    ),
                    'list_discounts': request.build_absolute_uri(
                        f'/api/products/list/{product.product_id}/discounts/'
                    )
                }
                
                return Response(discount_data, status=status.HTTP_200_OK)
            except Discount.DoesNotExist:
                raise ValidationError({'discount_id': 'Discount with this ID does not exist.'})
        else:
            # Create new discount
            data = request.data.copy()
            data['target_type'] = content_type.id
            data['target_id'] = product.id
            
            serializer = DiscountCreateUpdateSerializer(data=data, context={'request': request})
            serializer.is_valid(raise_exception=True)
            discount = serializer.save(created_by=request.user)
            
            # Handle nested rules if provided
            rules_data = request.data.get('rules', [])
            for rule_data in rules_data:
                DiscountRule.objects.create(
                    discount=discount,
                    rule_type=rule_data.get('rule_type'),
                    name=rule_data.get('name'),
                    description=rule_data.get('description', ''),
                    value=rule_data.get('value', '')
                )
            
            # Re-fetch to include rules
            discount.refresh_from_db()
            detail_serializer = DiscountDetailSerializer(discount, context={'request': request})
            discount_data = detail_serializer.data
            
            # Add HATEOAS links
            discount_data['_links'] = {
                'self': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/discounts/{discount.discount_id}/'
                ),
                'product': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/'
                ),
                'update': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/update-discount/{discount.discount_id}/'
                ),
                'delete': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/remove-discount/{discount.discount_id}/'
                ),
                'list_discounts': request.build_absolute_uri(
                    f'/api/products/list/{product.product_id}/discounts/'
                )
            }
            
            return Response(discount_data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Update product discount",
        description="Update an existing discount associated with this product. Can update name, description, type, values, and active status. Rules can be updated through separate rule management endpoints.",
        parameters=[
            OpenApiParameter(
                name='discount_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the discount to update'
            ),
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'nullable': True},
                    'description': {'type': 'string', 'nullable': True},
                    'discount_type': {
                        'type': 'string',
                        'enum': ['PERCENTAGE', 'FIXED'],
                        'nullable': True
                    },
                    'percentage': {'type': 'string', 'nullable': True},
                    'amount': {'type': 'string', 'nullable': True},
                    'active': {'type': 'boolean', 'nullable': True}
                }
            }
        },
        responses={
            200: {
                'description': 'Discount updated successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'id': 1,
                            'discount_id': 'uuid-here',
                            'name': 'Updated Discount',
                            'discount_type': 'PERCENTAGE',
                            'discount_value': '25%',
                            'percentage': '25.00',
                            'amount': None,
                            'active': True,
                            'rules': [],
                            '_links': {
                                'self': '/api/products/list/1/discounts/uuid-here/',
                                'product': '/api/products/list/1/',
                                'delete': '/api/products/list/1/remove-discount/uuid-here/',
                                'list_discounts': '/api/products/list/1/discounts/'
                            }
                        }
                    }
                }
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Product or discount not found'}
        },
        tags=["Products", "Discounts"],
    )
    @action(detail=True, methods=['patch'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='update-discount/(?P<discount_id>[^/.]+)')
    def update_discount(self, request, product_id=None, discount_id=None):
        """Update a discount for this product."""
        product = self.get_object()
        
        # Get ContentType for Product
        content_type = ContentType.objects.get_for_model(Product)
        
        try:
            discount = Discount.objects.get(
                discount_id=discount_id,
                target_type=content_type,
                target_id=product.id
            )
        except Discount.DoesNotExist:
            raise ValidationError({'discount_id': 'Discount not found for this product.'})
        
        serializer = DiscountCreateUpdateSerializer(
            discount,
            data=request.data,
            partial=True,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Return detailed response with HATEOAS
        discount.refresh_from_db()
        detail_serializer = DiscountDetailSerializer(discount, context={'request': request})
        discount_data = detail_serializer.data
        
        discount_data['_links'] = {
            'self': request.build_absolute_uri(
                f'/api/products/list/{product.product_id}/discounts/{discount.discount_id}/'
            ),
            'product': request.build_absolute_uri(
                f'/api/products/list/{product.product_id}/'
            ),
            'delete': request.build_absolute_uri(
                f'/api/products/list/{product.product_id}/remove-discount/{discount.discount_id}/'
            ),
            'list_discounts': request.build_absolute_uri(
                f'/api/products/list/{product.product_id}/discounts/'
            )
        }
        
        return Response(discount_data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Remove discount from product",
        description="Remove a discount from this product. The discount will be deleted entirely (not just disassociated). To deactivate a discount without deleting it, use the update endpoint with active=false.",
        parameters=[
            OpenApiParameter(
                name='discount_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the discount to remove'
            ),
        ],
        responses={
            200: {
                'description': 'Discount removed successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Discount removed from product Conference T-Shirt.',
                            '_links': {
                                'product': '/api/products/list/1/',
                                'list_discounts': '/api/products/list/1/discounts/'
                            }
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Product or discount not found'}
        },
        tags=["Products", "Discounts"],
    )
    @action(detail=True, methods=['delete'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='remove-discount/(?P<discount_id>[^/.]+)')
    def remove_discount(self, request, product_id=None, discount_id=None):
        """Remove a discount from this product."""
        product = self.get_object()
        
        # Get ContentType for Product
        content_type = ContentType.objects.get_for_model(Product)
        
        try:
            discount = Discount.objects.get(
                discount_id=discount_id,
                target_type=content_type,
                target_id=product.id
            )
            discount.delete()
            
            return Response({
                'status': 'success',
                'message': f'Discount removed from product {product.title}.',
                '_links': {
                    'product': request.build_absolute_uri(
                        f'/api/products/list/{product.product_id}/'
                    ),
                    'list_discounts': request.build_absolute_uri(
                        f'/api/products/list/{product.product_id}/discounts/'
                    )
                }
            }, status=status.HTTP_200_OK)
        except Discount.DoesNotExist:
            raise ValidationError({'discount_id': 'Discount not found for this product.'})
    
    @extend_schema(
        summary="List availability windows for product",
        description="Retrieve all availability windows associated with this product.",
        tags=["Products"],
        responses={200: {'description': 'List of availability windows'}},
        operation_id="products_availability_windows_list",
    )
    @action(detail=True, methods=['get'], url_path='availability-windows')
    def availability_windows(self, request, product_id=None):
        """Return all availability windows for this product."""
        product = self.get_object()
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        
        windows = product.availability_windows.all()
        paginated = self.paginate_queryset(windows)
        if paginated is not None:
            serializer = AvailabilityWindowSerializer(paginated, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = AvailabilityWindowSerializer(windows, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Add availability window to product",
        description=(
            "Add a new availability window to the product defining when it's available for purchase. "
            "Specify start and end times to control product visibility and purchasability. "
            "Only administrative staff can add availability windows."
        ),
        tags=["Products"],
        request={'application/json': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Window name'},
                'description': {'type': 'string', 'description': 'Optional description'},
                'availability_type': {'type': 'string', 'description': 'Type of availability window (defaults to PRODUCT_WINDOW)'},
                'available_from': {'type': 'string', 'format': 'date-time', 'description': 'Start datetime'},
                'available_to': {'type': 'string', 'format': 'date-time', 'description': 'End datetime'},
                'timezone': {'type': 'string', 'description': 'Timezone string'},
            },
            'required': ['name', 'available_from', 'available_to'],
        }},
        responses={
            201: {'description': 'Window created successfully'},
            400: {'description': 'Validation errors'},
            403: {'description': 'Permission denied'}
        },
        operation_id="products_add_availability_window",
    )
    @action(detail=True, methods=['post'], url_path='add-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def add_availability_window(self, request, product_id=None):
        """Add an availability window to this product."""
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        from django.contrib.contenttypes.models import ContentType
        
        product = self.get_object()
        
        serializer = AvailabilityWindowSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(Product)
            window = serializer.save(
                target_type=content_type,
                target_id=product.id
            )
            return Response(
                AvailabilityWindowSerializer(window, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        methods=['PATCH'],
        summary="Partially update availability window for product",
        description=(
            "Partially update an existing availability window for the product. "
            "Only administrative staff can update availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Products"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to update',
                required=True
            )
        ],
        request={'application/json': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Window name'},
                'description': {'type': 'string', 'description': 'Optional description'},
                'available_from': {'type': 'string', 'format': 'date-time'},
                'available_to': {'type': 'string', 'format': 'date-time'},
                'timezone': {'type': 'string'},
            },
        }},
        responses={
            200: {'description': 'Window updated successfully'},
            400: {'description': 'Invalid data or missing window_id'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Window not found'}
        },
        operation_id="products_update_availability_window",
    )
    @extend_schema(
        methods=['PUT'],
        summary="Fully update availability window for product",
        description=(
            "Fully update an existing availability window for the product. "
            "Only administrative staff can update availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Products"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to update',
                required=True
            )
        ],
        request={'application/json': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Window name'},
                'description': {'type': 'string', 'description': 'Optional description'},
                'available_from': {'type': 'string', 'format': 'date-time'},
                'available_to': {'type': 'string', 'format': 'date-time'},
                'timezone': {'type': 'string'},
            },
        }},
        responses={
            200: {'description': 'Window updated successfully'},
            400: {'description': 'Invalid data or missing window_id'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Window not found'}
        },
        operation_id="products_update_availability_window_full",
    )
    @action(detail=True, methods=['patch', 'put'], url_path='update-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def update_availability_window(self, request, product_id=None):
        """Update an existing availability window for the product."""
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        from django.contrib.contenttypes.models import ContentType
        
        product = self.get_object()
        
        window_id = request.query_params.get('window_id') or request.data.get('availability_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter or availability_id in request body is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            content_type = ContentType.objects.get_for_model(Product)
            window = AvailabilityWindow.objects.get(
                availability_id=window_id,
                target_id=product.id,
                target_type=content_type
            )
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this product"},
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
        summary="Remove availability window from product",
        description=(
            "Remove an availability window from the product by its window ID. "
            "Permanently deletes the window. "
            "Only administrative staff can remove availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Products"],
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
            204: {'description': 'Window removed successfully'},
            400: {'description': 'Bad request'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Window not found'}
        },
        operation_id="products_remove_availability_window",
    )
    @action(detail=True, methods=['delete'], url_path='remove-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def remove_availability_window(self, request, product_id=None):
        """Remove an availability window from this product."""
        from apps.common.models import AvailabilityWindow
        
        product = self.get_object()
        
        window_id = request.query_params.get('window_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            window = AvailabilityWindow.objects.get(availability_id=window_id, target_id=product.id)
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this product"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        window.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# PRODUCT VARIANT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List product variants",
        description="Retrieve a paginated list of product variants. Supports filtering by size, color, stock, price ranges. Can be accessed as nested route under products or standalone.",
        parameters=[
            OpenApiParameter(
                name='attendee_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Optional attendee UUID to enable attendee-specific pricing and eligibility context.',
                required=False,
            ),
            OpenApiParameter(
                name='customer_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional customer identifier override (admin/staff only).',
                required=False,
            ),
        ],
        tags=["Product Variants"],
    ),
    retrieve=extend_schema(
        summary="Retrieve variant details",
        description="Get detailed information about a specific product variant including stock, pricing, and product details.",
        parameters=[
            OpenApiParameter(
                name='attendee_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Optional attendee UUID to enable attendee-specific pricing and eligibility context.',
                required=False,
            ),
            OpenApiParameter(
                name='customer_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional customer identifier override (admin/staff only).',
                required=False,
            ),
        ],
        tags=["Product Variants"],
    ),
    create=extend_schema(
        summary="Create product variant",
        description="Create a new product variant. Event administrators can create variants for their products.",
        tags=["Product Variants"],
    ),
    update=extend_schema(
        summary="Update product variant",
        description="Update an existing product variant. Only administrators can modify variants.",
        tags=["Product Variants"],
    ),
    partial_update=extend_schema(
        summary="Partially update product variant",
        description="Partially update a product variant.",
        tags=["Product Variants"],
    ),
    destroy=extend_schema(
        summary="Delete product variant",
        description="Delete a product variant. Only allowed if no orders reference this variant.",
        tags=["Product Variants"],
    ),
)
class ProductVariantViewSet(PurchaseContextMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing product variants.
    
    Provides:
    - List/Retrieve: All authenticated users
    - Create/Update/Delete: Event administrators
    - Custom actions: increment_stock, decrement_stock, set_stock, toggle_active
    
    Permissions:
    - Read: Authenticated users
    - Write: Administrative staff for the event
    - Stock operations: Administrative staff only
    """
    
    queryset = ProductVariant.objects.select_related(
        'product', 'product__event', 'added_by', 'last_updated_by'
    )
    permission_classes = [permissions.IsAuthenticated, CanManageProducts]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductVariantFilterSet
    search_fields = ['product__title', 'size', 'color']
    ordering_fields = ['added_at', 'stock_quantity', 'base_amount']
    ordering = ['-added_at']
    lookup_field = 'variant_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return ProductVariantListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProductVariantCreateUpdateSerializer
        return ProductVariantDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on URL and user permissions."""
        queryset = super().get_queryset()
        
        # If accessing through nested route, filter by product
        product_id = self.kwargs.get('product_product_id')
        if product_id:
            queryset = queryset.filter(product__product_id=product_id)
        
        user = self.request.user
        
        # Admins see all variants
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see only active variants of active products
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self._build_purchase_context())
        return context
    
    @extend_schema(
        summary="Increment variant stock",
        description="Atomically increment the stock quantity of a variant. The operation is atomic to prevent race conditions. If max_stock_quantity is set, the increment will fail if it would exceed the maximum. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'amount': {
                        'type': 'integer',
                        'description': 'Amount to increment (must be positive)',
                        'example': 10,
                        'minimum': 1
                    },
                },
                'required': ['amount'],
            }
        },
        responses={
            200: {
                'description': 'Stock incremented successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'stock_quantity': 60,
                            'message': 'Stock incremented by 10. New stock: 60'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid amount or would exceed max stock',
                'content': {
                    'application/json': {
                        'example': {
                            'amount': ['Amount must be a positive integer.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='increment-stock')
    def increment_stock(self, request, product_product_id=None, variant_id=None):
        """Increment the stock quantity of the variant."""
        variant = self.get_object()
        amount = request.data.get('amount')

        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise ValidationError({'amount': 'Amount must be a positive integer.'})
        
        if not amount or amount <= 0:
            raise ValidationError({'amount': 'Amount must be a positive amount.'})
        
        try:
            variant.increment_stock(amount)
            variant.refresh_from_db()
            return Response({
                'status': 'success',
                'stock_quantity': variant.stock_quantity,
                'message': f'Stock incremented by {amount}. New stock: {variant.stock_quantity}'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Decrement variant stock",
        description="Atomically decrement the stock quantity of a variant. The operation is atomic to prevent race conditions. Will fail if there is insufficient stock. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'amount': {
                        'type': 'integer',
                        'description': 'Amount to decrement (must be positive)',
                        'example': 5,
                        'minimum': 1
                    },
                },
                'required': ['amount'],
            }
        },
        responses={
            200: {
                'description': 'Stock decremented successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'stock_quantity': 45,
                            'message': 'Stock decremented by 5. New stock: 45'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid amount or insufficient stock',
                'content': {
                    'application/json': {
                        'example': {
                            'error': 'Insufficient stock for the selected product variant.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='decrement-stock')
    def decrement_stock(self, request, product_product_id=None, variant_id=None):
        """Decrement the stock quantity of the variant."""
        variant = self.get_object()
        amount = request.data.get('amount')

        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise ValidationError({'amount': 'Amount must be a positive integer.'})
        
        if not amount or amount <= 0:
            raise ValidationError({'amount': 'Amount must be a positive amount.'})
        
        try:
            variant.decrement_stock(amount)
            variant.refresh_from_db()
            return Response({
                'status': 'success',
                'stock_quantity': variant.stock_quantity,
                'message': f'Stock decremented by {amount}. New stock: {variant.stock_quantity}'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Set variant stock",
        description="Set the stock quantity to a specific value, overriding the current stock level. Useful for inventory adjustments or corrections. Only administrators can perform stock operations.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'stock_quantity': {
                        'type': 'integer',
                        'description': 'New stock quantity (must be non-negative)',
                        'example': 50,
                        'minimum': 0
                    },
                },
                'required': ['stock_quantity'],
            }
        },
        responses={
            200: {
                'description': 'Stock set successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'stock_quantity': 50,
                            'message': 'Stock set to 50.'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid stock_quantity value',
                'content': {
                    'application/json': {
                        'example': {
                            'stock_quantity': ['Stock quantity must be a non-negative integer.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='set-stock')
    def set_stock(self, request, product_product_id=None, variant_id=None):
        """Set the stock quantity to a specific value."""
        variant = self.get_object()
        stock_quantity = request.data.get('stock_quantity')

        try:
            stock_quantity = int(stock_quantity)
        except (TypeError, ValueError):
            raise ValidationError({'stock_quantity': 'Stock quantity must be a non-negative integer.'})
        
        if stock_quantity is None or not isinstance(stock_quantity, int) or stock_quantity < 0:
            raise ValidationError({'stock_quantity': 'Stock quantity must be a non-negative integer.'})
        
        variant.stock_quantity = stock_quantity
        variant.save()
        
        return Response({
            'status': 'success',
            'stock_quantity': variant.stock_quantity,
            'message': f'Stock set to {stock_quantity}.'
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Toggle variant active status",
        description="Toggle the is_active status of a variant between true and false. Only administrators can perform this action. Inactive variants are not visible to regular users and cannot be purchased.",
        request=None,
        responses={
            200: {
                'description': 'Status toggled successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'is_active': True,
                            'message': 'Variant is now active.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def toggle_active(self, request, product_product_id=None, variant_id=None):
        """Toggle the is_active status of the variant."""
        variant = self.get_object()
        variant.is_active = not variant.is_active
        variant.save()
        
        return Response({
            'status': 'success',
            'is_active': variant.is_active,
            'message': f'Variant is now {"active" if variant.is_active else "inactive"}.'
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Add image to variant",
        description="Upload an image file directly to the variant. The file will be automatically converted to a Resource object and attached to the variant. Supports JPEG, PNG, GIF, and WebP formats up to 10MB. If is_main is true, any existing main image will be replaced.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'image': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Image file to upload (JPEG, PNG, GIF, or WebP, max 10MB)'
                    },
                    'is_main': {
                        'type': 'string',
                        'description': 'Whether this should be the main variant image (true/false, 1/0, yes/no)',
                        'default': 'false'
                    },
                },
                'required': ['image'],
            }
        },
        responses={
            200: {
                'description': 'Image added successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'resource_id': 123,
                            'message': 'Image added to variant successfully.'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid image file',
                'content': {
                    'application/json': {
                        'example': {
                            'image': ['No image file provided.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='add-image')
    def add_image(self, request, product_product_id=None, variant_id=None):
        """Add an image to the variant by uploading a file directly."""
        variant = self.get_object()
        image_file = request.FILES.get('image')
        is_main_str = request.data.get('is_main', 'false').lower()
        is_main = is_main_str in ['true', '1', 'yes']
        
        if not image_file:
            raise ValidationError({'image': 'No image file provided.'})
        
        # Validate file size (10MB limit)
        if image_file.size > 10 * 1024 * 1024:
            raise ValidationError({'image': 'Image file size must not exceed 10MB.'})
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        if image_file.content_type not in allowed_types:
            raise ValidationError({
                'image': f'Invalid image type. Allowed types: {", ".join(allowed_types)}'
            })
        
        try:
            # Create Resource object
            resource = Resource.objects.create(
                added_by=request.user,
                image=image_file,
                resource_type="IMAGE",
                # alt_text=f'Variant image for {variant.product.title} ({variant.size})',
                target_type=ContentType.objects.get_for_model(variant),
                target_id=variant.id,
            )
            
            # Add to variant using mixin method
            variant.add_variant_image(resource, is_main=is_main)
            
            return Response({
                'status': 'success',
                'resource_id': resource.id,
                'message': 'Image added to variant successfully.'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise e 
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Remove image from variant",
        description="Remove an image resource from the variant by resource ID. Only administrators can perform this action.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'resource_id': {
                        'type': 'integer',
                        'description': 'ID of the resource to remove',
                        'example': 123
                    },
                },
                'required': ['resource_id'],
            }
        },
        responses={
            200: {
                'description': 'Image removed successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Image removed from variant successfully.'
                        }
                    }
                }
            },
            400: {
                'description': 'Invalid resource_id',
                'content': {
                    'application/json': {
                        'example': {
                            'resource_id': ['Resource does not exist.']
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='remove-image')
    def remove_image(self, request, product_product_id=None, variant_id=None):
        """Remove an image from the variant."""
        variant = self.get_object()
        resource_id = request.data.get('resource_id')
        
        if not resource_id:
            raise ValidationError({'resource_id': 'Resource ID is required.'})
        
        try:
            resource = Resource.objects.get(id=resource_id)
            variant.remove_variant_image(resource)
            
            return Response({
                'status': 'success',
                'message': 'Image removed from variant successfully.'
            }, status=status.HTTP_200_OK)
        except Resource.DoesNotExist:
            raise ValidationError({'resource_id': 'Resource does not exist.'})
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="List variant discounts",
        description="Retrieve all discounts associated with this product variant, filtered by the event. Returns a paginated list of active and inactive discounts with their rules and HATEOAS links.",
        parameters=[
            OpenApiParameter(
                name='active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter by active status'
            ),
        ],
        responses={
            200: {
                'description': 'Discounts retrieved successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'count': 2,
                            'next': None,
                            'previous': None,
                            'results': [
                                {
                                    'id': 1,
                                    'discount_id': 'uuid-here',
                                    'name': 'Size Discount',
                                    'discount_type': 'PERCENTAGE',
                                    'discount_value': '15%',
                                    'percentage': '15.00',
                                    'amount': None,
                                    'active': True,
                                    'rules': [],
                                    '_links': {
                                        'self': '/api/products/list/1/variants/2/discounts/uuid-here/',
                                        'variant': '/api/products/list/1/variants/2/',
                                        'update': '/api/products/list/1/variants/2/update-discount/uuid-here/',
                                        'delete': '/api/products/list/1/variants/2/remove-discount/uuid-here/'
                                    }
                                }
                            ],
                            '_links': {
                                'self': '/api/products/list/1/variants/2/discounts/',
                                'variant': '/api/products/list/1/variants/2/',
                                'add_discount': '/api/products/list/1/variants/2/add-discount/'
                            }
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires authentication'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants", "Discounts"],
    )
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated], url_path='discounts')
    def list_discounts(self, request, product_product_id=None, variant_id=None):
        """List all discounts for this variant."""
        variant = self.get_object()
        
        # Get ContentType for ProductVariant
        content_type = ContentType.objects.get_for_model(ProductVariant)
        
        # Query discounts targeting this variant
        queryset = Discount.objects.filter(
            target_type=content_type,
            target_id=variant.id
        ).select_related('created_by').prefetch_related('rules')
        
        # Filter by active status if provided
        active_filter = request.query_params.get('active')
        if active_filter is not None:
            active_filter = active_filter.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(active=active_filter)
        
        # Serialize discounts
        serializer = DiscountListSerializer(queryset, many=True, context={'request': request})
        
        # Build HATEOAS links
        results = serializer.data
        for discount_data in results:
            discount_id = discount_data.get('discount_id')
            discount_data['_links'] = {
                'self': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/{discount_id}/'
                ),
                'variant': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/'
                ),
                'update': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/update-discount/{discount_id}/'
                ),
                'delete': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/remove-discount/{discount_id}/'
                )
            }
        
        return Response({
            'count': len(results),
            'next': None,
            'previous': None,
            'results': results,
            '_links': {
                'self': request.build_absolute_uri(),
                'variant': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/'
                ),
                'add_discount': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/add-discount/'
                )
            }
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Add discount to variant",
        description="Create a new discount for this product variant or associate an existing discount. Supports creating discounts with nested rules (maximum 2). The ContentType and target_id are automatically set based on the variant. Rules can be edited separately after creation.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'discount_id': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'Optional: UUID of existing discount to associate',
                        'nullable': True
                    },
                    'name': {
                        'type': 'string',
                        'description': 'Discount name',
                        'example': 'Large Size Discount'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Discount description',
                        'nullable': True
                    },
                    'discount_type': {
                        'type': 'string',
                        'enum': ['PERCENTAGE', 'FIXED'],
                        'description': 'Type of discount'
                    },
                    'percentage': {
                        'type': 'string',
                        'description': 'Percentage value (required if discount_type is PERCENTAGE)',
                        'example': '15.00',
                        'nullable': True
                    },
                    'amount': {
                        'type': 'string',
                        'description': 'Fixed amount (required if discount_type is FIXED)',
                        'example': '5.00',
                        'nullable': True
                    },
                    'active': {
                        'type': 'boolean',
                        'description': 'Whether discount is active',
                        'default': True
                    },
                    'rules': {
                        'type': 'array',
                        'description': 'Optional discount rules (maximum 2)',
                        'maxItems': 2,
                        'items': {
                            'type': 'object',
                            'properties': {
                                'rule_type': {'type': 'string'},
                                'name': {'type': 'string'},
                                'description': {'type': 'string', 'nullable': True},
                                'value': {'type': 'string', 'nullable': True}
                            }
                        }
                    }
                },
                'required': ['name', 'discount_type']
            }
        },
        responses={
            201: {
                'description': 'Discount created successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'id': 1,
                            'discount_id': 'uuid-here',
                            'name': 'Size Discount',
                            'discount_type': 'PERCENTAGE',
                            'discount_value': '15%',
                            'percentage': '15.00',
                            'amount': None,
                            'active': True,
                            'rules': [],
                            '_links': {
                                'self': '/api/products/list/1/variants/2/discounts/uuid-here/',
                                'variant': '/api/products/list/1/variants/2/',
                                'update': '/api/products/list/1/variants/2/update-discount/uuid-here/',
                                'delete': '/api/products/list/1/variants/2/remove-discount/uuid-here/',
                                'list_discounts': '/api/products/list/1/variants/2/discounts/'
                            }
                        }
                    }
                }
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant not found'}
        },
        tags=["Product Variants", "Discounts"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='add-discount')
    def add_discount(self, request, product_product_id=None, variant_id=None):
        """Create a new discount for this variant or associate an existing one."""
        variant = self.get_object()
        discount_id = request.data.get('discount_id')
        
        # Get ContentType for ProductVariant
        content_type = ContentType.objects.get_for_model(ProductVariant)
        
        if discount_id:
            # Associate existing discount
            try:
                discount = Discount.objects.get(discount_id=discount_id)
                # Update target to this variant
                discount.target_type = content_type
                discount.target_id = variant.id
                discount.save()
                
                serializer = DiscountDetailSerializer(discount, context={'request': request})
                discount_data = serializer.data
                
                # Add HATEOAS links
                discount_data['_links'] = {
                    'self': request.build_absolute_uri(
                        f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/{discount.discount_id}/'
                    ),
                    'variant': request.build_absolute_uri(
                        f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/'
                    ),
                    'update': request.build_absolute_uri(
                        f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/update-discount/{discount.discount_id}/'
                    ),
                    'delete': request.build_absolute_uri(
                        f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/remove-discount/{discount.discount_id}/'
                    ),
                    'list_discounts': request.build_absolute_uri(
                        f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/'
                    )
                }
                
                return Response(discount_data, status=status.HTTP_200_OK)
            except Discount.DoesNotExist:
                raise ValidationError({'discount_id': 'Discount with this ID does not exist.'})
        else:
            # Create new discount
            data = request.data.copy()
            data['target_type'] = content_type.id
            data['target_id'] = variant.id
            
            serializer = DiscountCreateUpdateSerializer(data=data, context={'request': request})
            serializer.is_valid(raise_exception=True)
            discount = serializer.save(created_by=request.user)
            
            # Handle nested rules if provided
            rules_data = request.data.get('rules', [])
            for rule_data in rules_data:
                DiscountRule.objects.create(
                    discount=discount,
                    rule_type=rule_data.get('rule_type'),
                    name=rule_data.get('name'),
                    description=rule_data.get('description', ''),
                    value=rule_data.get('value', '')
                )
            
            # Re-fetch to include rules
            discount.refresh_from_db()
            detail_serializer = DiscountDetailSerializer(discount, context={'request': request})
            discount_data = detail_serializer.data
            
            # Add HATEOAS links
            discount_data['_links'] = {
                'self': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/{discount.discount_id}/'
                ),
                'variant': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/'
                ),
                'update': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/update-discount/{discount.discount_id}/'
                ),
                'delete': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/remove-discount/{discount.discount_id}/'
                ),
                'list_discounts': request.build_absolute_uri(
                    f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/'
                )
            }
            
            return Response(discount_data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Update variant discount",
        description="Update an existing discount associated with this variant. Can update name, description, type, values, and active status. Rules can be updated through separate rule management endpoints.",
        parameters=[
            OpenApiParameter(
                name='discount_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the discount to update'
            ),
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'nullable': True},
                    'description': {'type': 'string', 'nullable': True},
                    'discount_type': {
                        'type': 'string',
                        'enum': ['PERCENTAGE', 'FIXED'],
                        'nullable': True
                    },
                    'percentage': {'type': 'string', 'nullable': True},
                    'amount': {'type': 'string', 'nullable': True},
                    'active': {'type': 'boolean', 'nullable': True}
                }
            }
        },
        responses={
            200: {
                'description': 'Discount updated successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'id': 1,
                            'discount_id': 'uuid-here',
                            'name': 'Updated Variant Discount',
                            'discount_type': 'PERCENTAGE',
                            'discount_value': '20%',
                            'percentage': '20.00',
                            'amount': None,
                            'active': True,
                            'rules': [],
                            '_links': {
                                'self': '/api/products/list/1/variants/2/discounts/uuid-here/',
                                'variant': '/api/products/list/1/variants/2/',
                                'delete': '/api/products/list/1/variants/2/remove-discount/uuid-here/',
                                'list_discounts': '/api/products/list/1/variants/2/discounts/'
                            }
                        }
                    }
                }
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant or discount not found'}
        },
        tags=["Product Variants", "Discounts"],
    )
    @action(detail=True, methods=['patch'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='update-discount/(?P<discount_id>[^/.]+)')
    def update_discount(self, request, product_product_id=None, variant_id=None, discount_id=None):
        """Update a discount for this variant."""
        variant = self.get_object()
        
        # Get ContentType for ProductVariant
        content_type = ContentType.objects.get_for_model(ProductVariant)
        
        try:
            discount = Discount.objects.get(
                discount_id=discount_id,
                target_type=content_type,
                target_id=variant.id
            )
        except Discount.DoesNotExist:
            raise ValidationError({'discount_id': 'Discount not found for this variant.'})
        
        serializer = DiscountCreateUpdateSerializer(
            discount,
            data=request.data,
            partial=True,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Return detailed response with HATEOAS
        discount.refresh_from_db()
        detail_serializer = DiscountDetailSerializer(discount, context={'request': request})
        discount_data = detail_serializer.data
        
        discount_data['_links'] = {
            'self': request.build_absolute_uri(
                f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/{discount.discount_id}/'
            ),
            'variant': request.build_absolute_uri(
                f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/'
            ),
            'delete': request.build_absolute_uri(
                f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/remove-discount/{discount.discount_id}/'
            ),
            'list_discounts': request.build_absolute_uri(
                f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/'
            )
        }
        
        return Response(discount_data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Remove discount from variant",
        description="Remove a discount from this variant. The discount will be deleted entirely (not just disassociated). To deactivate a discount without deleting it, use the update endpoint with active=false.",
        parameters=[
            OpenApiParameter(
                name='discount_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description='UUID of the discount to remove'
            ),
        ],
        responses={
            200: {
                'description': 'Discount removed successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Discount removed from variant successfully.',
                            '_links': {
                                'variant': '/api/products/list/1/variants/2/',
                                'list_discounts': '/api/products/list/1/variants/2/discounts/'
                            }
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - requires administrative access'},
            404: {'description': 'Variant or discount not found'}
        },
        tags=["Product Variants", "Discounts"],
    )
    @action(detail=True, methods=['delete'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly], url_path='remove-discount/(?P<discount_id>[^/.]+)')
    def remove_discount(self, request, product_product_id=None, variant_id=None, discount_id=None):
        """Remove a discount from this variant."""
        variant = self.get_object()
        
        # Get ContentType for ProductVariant
        content_type = ContentType.objects.get_for_model(ProductVariant)
        
        try:
            discount = Discount.objects.get(
                discount_id=discount_id,
                target_type=content_type,
                target_id=variant.id
            )
            discount.delete()
            
            return Response({
                'status': 'success',
                'message': 'Discount removed from variant successfully.',
                '_links': {
                    'variant': request.build_absolute_uri(
                        f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/'
                    ),
                    'list_discounts': request.build_absolute_uri(
                        f'/api/products/list/{variant.product.product_id}/variants/{variant.variant_id}/discounts/'
                    )
                }
            }, status=status.HTTP_200_OK)
        except Discount.DoesNotExist:
            raise ValidationError({'discount_id': 'Discount not found for this variant.'})
    
    @extend_schema(
        summary="List availability windows for product variant",
        description="Retrieve all availability windows associated with this product variant.",
        tags=["Product Variants"],
        responses={200: {'description': 'List of availability windows'}},
        operation_id="product_variants_availability_windows_list",
    )
    @action(detail=True, methods=['get'], url_path='availability-windows')
    def availability_windows(self, request, product_product_id=None, variant_id=None):
        """Return all availability windows for this product variant."""
        variant = self.get_object()
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        
        windows = variant.availability_windows.all()
        paginated = self.paginate_queryset(windows)
        if paginated is not None:
            serializer = AvailabilityWindowSerializer(paginated, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = AvailabilityWindowSerializer(windows, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Add availability window to product variant",
        description=(
            "Add a new availability window to the product variant defining when it's available for purchase. "
            "Specify start and end times to control variant visibility and purchasability. "
            "Only administrative staff can add availability windows."
        ),
        tags=["Product Variants"],
        request={'application/json': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Window name'},
                'description': {'type': 'string', 'description': 'Optional description'},
                'availability_type': {'type': 'string', 'description': 'Type of availability window (defaults to PRODUCT_WINDOW)'},
                'available_from': {'type': 'string', 'format': 'date-time', 'description': 'Start datetime'},
                'available_to': {'type': 'string', 'format': 'date-time', 'description': 'End datetime'},
                'timezone': {'type': 'string', 'description': 'Timezone string'},
            },
            'required': ['name', 'available_from', 'available_to'],
        }},
        responses={
            201: {'description': 'Window created successfully'},
            400: {'description': 'Validation errors'},
            403: {'description': 'Permission denied'}
        },
        operation_id="product_variants_add_availability_window",
    )
    @action(detail=True, methods=['post'], url_path='add-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def add_availability_window(self, request, product_product_id=None, variant_id=None):
        """Add an availability window to this product variant."""
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        from django.contrib.contenttypes.models import ContentType
        
        variant = self.get_object()
        
        serializer = AvailabilityWindowSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(ProductVariant)
            window = serializer.save(
                target_type=content_type,
                target_id=variant.id
            )
            return Response(
                AvailabilityWindowSerializer(window, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        methods=['PATCH'],
        summary="Partially update availability window for product variant",
        description=(
            "Partially update an existing availability window for the product variant. "
            "Only administrative staff can update availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Product Variants"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to update',
                required=True
            )
        ],
        request={'application/json': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Window name'},
                'description': {'type': 'string', 'description': 'Optional description'},
                'available_from': {'type': 'string', 'format': 'date-time'},
                'available_to': {'type': 'string', 'format': 'date-time'},
                'timezone': {'type': 'string'},
            },
        }},
        responses={
            200: {'description': 'Window updated successfully'},
            400: {'description': 'Invalid data or missing window_id'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Window not found'}
        },
        operation_id="product_variants_update_availability_window",
    )
    @extend_schema(
        methods=['PUT'],
        summary="Fully update availability window for product variant",
        description=(
            "Fully update an existing availability window for the product variant. "
            "Only administrative staff can update availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Product Variants"],
        parameters=[
            OpenApiParameter(
                name='window_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Availability window ID to update',
                required=True
            )
        ],
        request={'application/json': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Window name'},
                'description': {'type': 'string', 'description': 'Optional description'},
                'available_from': {'type': 'string', 'format': 'date-time'},
                'available_to': {'type': 'string', 'format': 'date-time'},
                'timezone': {'type': 'string'},
            },
        }},
        responses={
            200: {'description': 'Window updated successfully'},
            400: {'description': 'Invalid data or missing window_id'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Window not found'}
        },
        operation_id="product_variants_update_availability_window_full",
    )
    @action(detail=True, methods=['patch', 'put'], url_path='update-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def update_availability_window(self, request, product_product_id=None, variant_id=None):
        """Update an existing availability window for the product variant."""
        from apps.common.models import AvailabilityWindow
        from apps.common.api.serializers import AvailabilityWindowSerializer
        from django.contrib.contenttypes.models import ContentType
        
        variant = self.get_object()
        
        window_id = request.query_params.get('window_id') or request.data.get('availability_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter or availability_id in request body is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            content_type = ContentType.objects.get_for_model(ProductVariant)
            window = AvailabilityWindow.objects.get(
                availability_id=window_id,
                target_id=variant.id,
                target_type=content_type
            )
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this product variant"},
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
        summary="Remove availability window from product variant",
        description=(
            "Remove an availability window from the product variant by its window ID. "
            "Permanently deletes the window. "
            "Only administrative staff can remove availability windows. "
            "Requires window_id query parameter."
        ),
        tags=["Product Variants"],
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
            204: {'description': 'Window removed successfully'},
            400: {'description': 'Bad request'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Window not found'}
        },
        operation_id="product_variants_remove_availability_window",
    )
    @action(detail=True, methods=['delete'], url_path='remove-availability-window', permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def remove_availability_window(self, request, product_product_id=None, variant_id=None):
        """Remove an availability window from this product variant."""
        from apps.common.models import AvailabilityWindow
        
        variant = self.get_object()
        
        window_id = request.query_params.get('window_id')
        if not window_id:
            return Response(
                {"detail": "window_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            window = AvailabilityWindow.objects.get(availability_id=window_id, target_id=variant.id)
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this product variant"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        window.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# ORDER VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List orders",
        description="Retrieve a paginated list of orders. Users see their own orders, administrators see all orders for their events.",
        parameters=[
            OpenApiParameter(
                name='event',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional event url_safe_title. If provided, event staff can view all orders for that event in addition to their own orders.',
                required=False,
            ),
        ],
        tags=["Orders"],
    ),
    retrieve=extend_schema(
        summary="Retrieve order details",
        description="Get detailed information about a specific order including all items and payment details.",
        parameters=[
            OpenApiParameter(
                name='event',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Optional event url_safe_title used for queryset scoping and event staff access checks.',
                required=False,
            ),
        ],
        tags=["Orders"],
    ),
    create=extend_schema(
        summary="Create order",
        description="Create a new order with items. Order starts in 'draft' status. Items are validated for stock and purchase eligibility.",
        tags=["Orders"],
    ),
    update=extend_schema(
        summary="Update order",
        description="Update order status. Status transitions are validated (e.g., draft → pending → processing → completed).",
        tags=["Orders"],
    ),
    partial_update=extend_schema(
        summary="Partially update order",
        description="Partially update order fields.",
        tags=["Orders"],
    ),
    destroy=extend_schema(
        summary="Delete order",
        description="Delete an order. Only draft orders can be deleted.",
        tags=["Orders"],
    ),
)
class OrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing orders.
    
    Provides:
    - List: Users see their own orders, admins see all
    - Retrieve: Order owner or administrators
    - Create: Authenticated users
    - Update: Order owner or administrators (limited to status changes)
    - Custom actions: submit, cancel, add_item
    
    Permissions:
    - List/Create: Authenticated users
    - Retrieve/Update/Delete: Order owner or administrative staff
    """
    
    queryset = Order.objects.select_related(
        'customer', 'attendee', 'attendee__event', 'payment', 'created_by', 'updated_by'
    )
    permission_classes = [permissions.IsAuthenticated, IsOrderOwnerOrAdministrative]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrderFilterSet
    search_fields = ['order_reference_id', 'customer__email', 'attendee__email']
    ordering_fields = ['created_at', 'updated_at', 'total_amount', 'status']
    ordering = ['-created_at']
    lookup_field = 'order_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return OrderListSerializer
        elif self.action == 'create':
            return OrderCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return OrderUpdateSerializer
        return OrderDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""

        from apps.events.models import Event
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all orders
        if user.is_superuser or user.is_staff:
            return queryset

        # check query params for event, if so check if they are an event staff 
        # event staff can see all orders for their events, even if they are not the customer or attendee
        event_id = self.request.query_params.get('event')

        # if request is a list then require parameter event, if not infer event from order for retrieve, update, delete actions

        if event_id:
            try:
                event = Event.objects.get(Q(url_safe_title=event_id))
                if event.staff_members.filter(user_id=user.id).exists():
                    return queryset.filter(
                        Q(attendee__event__url_safe_title=event_id) |
                        Q(customer=user)
                    )
            except Event.DoesNotExist:
                pass
        
        
        # Regular users see only their own orders
        if self.action in ['retrieve', 'list'] and not self.request.query_params.get('event'):
            return queryset.filter(
                Q(customer=user) |
                Q(attendee__user=user)
            )
        return queryset

    def get_object(self):
        return super().get_object()
    
    def perform_create(self, serializer):
        serializer.context['request'] = self.request  # Pass request to serializer for validation
        return super().perform_create(serializer)

    def _assert_attendee_access(self, attendee, user):
        if user.is_superuser or user.is_staff:
            return

        attendee_owner_match = attendee.user_id == user.id
        attendee_booking_match = bool(attendee.booking_id and attendee.booking and attendee.booking.made_by_id == user.id)
        if not attendee_owner_match and not attendee_booking_match:
            raise PermissionDenied('You do not have permission to access this attendee pricing context.')
    
    @extend_schema(
        summary="Submit order",
        description="Submit an order, transitioning it from 'draft' to 'pending' status. Order must have at least one item. Stock is reserved when the order is submitted.",
        request=None,
        responses={
            200: {
                'description': 'Order submitted successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Order ORD-12345 submitted successfully.',
                            'order': {
                                'id': 1,
                                'order_id': 'uuid-here',
                                'order_reference_id': 'ORD-12345',
                                'status': 'pending',
                                'total_amount': 'GBP 50.00'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Cannot submit order (validation error)',
                'content': {
                    'application/json': {
                        'example': {
                            'error': 'Order must have at least one item before submission.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - not order owner or administrator'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'])
    def submit(self, request, order_id=None):
        """Submit the order (draft → pending)."""
        order = self.get_object()
        
        try:
            order.submit()
            serializer = self.get_serializer(order)
            return Response({
                'status': 'success',
                'message': f'Order {order.order_reference_id} submitted successfully.',
                'order': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Cancel order",
        description="Cancel an order, transitioning it to 'cancelled' status. Stock is automatically restored for all items in the order. Only non-completed orders can be cancelled.",
        request=None,
        responses={
            200: {
                'description': 'Order cancelled successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Order ORD-12345 cancelled successfully.',
                            'order': {
                                'id': 1,
                                'order_id': 'uuid-here',
                                'order_reference_id': 'ORD-12345',
                                'status': 'cancelled',
                                'total_amount': 'GBP 50.00'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Cannot cancel order',
                'content': {
                    'application/json': {
                        'example': {
                            'error': 'Cannot cancel a completed order.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - not order owner or administrator'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'])
    def cancel(self, request, order_id=None):
        """Cancel the order."""
        order = self.get_object()
        
        try:
            order.cancel()
            serializer = self.get_serializer(order)
            return Response({
                'status': 'success',
                'message': f'Order {order.order_reference_id} cancelled successfully.',
                'order': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Complete order",
        description="Mark an order as completed. Only staff members can complete orders. Order must be in 'processing' status. This action is typically performed once payment has been verified and items are ready for fulfillment or have been fulfilled.",
        request=None,
        responses={
            200: {
                'description': 'Order completed successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Order ORD-12345 marked as completed.',
                            'order': {
                                'id': 1,
                                'order_id': 'uuid-here',
                                'order_reference_id': 'ORD-12345',
                                'status': 'completed',
                                'total_amount': 'GBP 50.00'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Cannot complete order',
                'content': {
                    'application/json': {
                        'example': {
                            'error': 'Cannot transition from pending to completed.'
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - staff only'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def complete(self, request, order_id=None):
        """Complete the order (processing → completed). Staff only."""
        order = self.get_object()
        
        try:
            order.transition_to(OrderStatusChoices.COMPLETED)
            serializer = self.get_serializer(order)
            return Response({
                'status': 'success',
                'message': f'Order {order.order_reference_id} marked as completed.',
                'order': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            raise ValidationError({'error': str(e)})
    
    @extend_schema(
        summary="Add item to order",
        description="Add an item to a draft order. Only draft orders can have items added. Stock availability and purchase limits are validated. Order total is automatically recalculated.",
        request=OrderItemCreateSerializer,
        responses={
            200: {
                'description': 'Item added successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'status': 'success',
                            'message': 'Item added to order.',
                            'order_item': {
                                'id': 1,
                                'product_variant': 'uuid-here',
                                'quantity': 2,
                                'unit_price': 'GBP 25.00',
                                'total_price': 'GBP 50.00'
                            },
                            'order_total': 'GBP 50.00'
                        }
                    }
                }
            },
            400: {
                'description': 'Cannot add item (validation error)',
                'content': {
                    'application/json': {
                        'examples': {
                            'not_draft': {
                                'value': {'error': 'Can only add items to draft orders.'}
                            },
                            'insufficient_stock': {
                                'value': {'error': 'Insufficient stock for the selected product variant.'}
                            },
                            'invalid_variant': {
                                'value': {'product_variant_id': ['Product variant does not exist.']}
                            }
                        }
                    }
                }
            },
            403: {'description': 'Permission denied - not order owner or administrator'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsOrderOwnerOrAdministrative], url_path='add-item')
    def add_item(self, request, order_id=None):
        """Add an item to the order."""
        order = self.get_object()
        
        if order.status != OrderStatusChoices.DRAFT:
            raise ValidationError('Can only add items to draft orders.')
        
        serializer = OrderItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        variant_id = serializer.validated_data['product_variant_id']
        quantity = serializer.validated_data['quantity']
        
        try:
            variant = ProductVariant.objects.get(variant_id=variant_id)
            order_item = order.add_order_item(variant, quantity)
            item_serializer = OrderItemSerializer(order_item, context={'request': request})
            return Response({
                'status': 'success',
                'message': 'Item added to order.',
                'order_item': item_serializer.data,
                'order_total': str(order.total_amount)
            }, status=status.HTTP_200_OK)
        except ProductVariant.DoesNotExist:
            raise ValidationError({'product_variant_id': 'Product variant does not exist.'})
        except Exception as e:
            raise ValidationError({'error': str(e)})

    @extend_schema(
        summary='Update order item quantity',
        description='Update quantity of a specific item in a draft order. Stock and order total are reconciled atomically.',
        request=inline_serializer(
            name='OrderUpdateItemQuantityRequest',
            fields={
                'order_item_id': serializers.IntegerField(min_value=1),
                'quantity': serializers.IntegerField(min_value=1),
            },
        ),
        responses={
            200: {'description': 'Order item updated successfully'},
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Order or order item not found'},
        },
        tags=['Orders'],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsOrderOwnerOrAdministrative], url_path='update-item')
    def update_item(self, request, order_id=None):
        """Update quantity for an order item in a draft order."""
        from django.db import transaction

        order = self.get_object()
        if order.status != OrderStatusChoices.DRAFT:
            raise ValidationError('Can only update items in draft orders.')

        serializer = inline_serializer(
            name='OrderUpdateItemQuantityRuntimeSerializer',
            fields={
                'order_item_id': serializers.IntegerField(min_value=1),
                'quantity': serializers.IntegerField(min_value=1),
            },
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        order_item_id = serializer.validated_data['order_item_id']
        new_quantity = serializer.validated_data['quantity']

        with transaction.atomic():
            locked_order = get_object_or_404(Order.objects.select_for_update(), pk=order.pk)
            order_item = get_object_or_404(
                OrderItem.objects.select_for_update(),
                id=order_item_id,
                order=locked_order,
            )

            old_quantity = int(order_item.quantity)
            quantity_delta = int(new_quantity) - old_quantity

            if quantity_delta != 0:
                if not order_item.product_variant:
                    raise ValidationError({'order_item_id': 'This order item has no active product variant.'})

                if quantity_delta > 0:
                    order_item.product_variant.can_attendee_purchase_quantity(
                        locked_order.attendee,
                        quantity_delta,
                        raise_exception=True,
                    )
                    order_item.product_variant.decrement_stock(quantity_delta)
                else:
                    order_item.product_variant.increment_stock(abs(quantity_delta))

            order_item.quantity = new_quantity
            order_item.total_price = (order_item.unit_price.amount * new_quantity).quantize(decimal.Decimal('0.01'))
            order_item.full_clean()
            order_item.save()

            locked_order.total_amount = locked_order.get_total_amount()
            locked_order.save(update_fields=['total_amount', 'updated_at'])

            if locked_order.order_items.count() == 0:
                locked_order.delete()
                return Response({
                    'status': 'success',
                    'message': 'Order item updated. Order has no more items and was deleted.',
                    'order_total': 'GBP 0.00',
                }, status=status.HTTP_200_OK)

            item_serializer = OrderItemSerializer(order_item, context={'request': request})
            return Response({
                'status': 'success',
                'message': 'Order item quantity updated.',
                'order_item': item_serializer.data,
                'order_total': str(locked_order.total_amount),
            }, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Remove order item',
        description='Remove a specific order item from a draft order. Stock is restored and order total recalculated.',
        request=inline_serializer(
            name='OrderRemoveItemRequest',
            fields={
                'order_item_id': serializers.IntegerField(min_value=1),
            },
        ),
        responses={
            200: {'description': 'Order item removed successfully'},
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Order or order item not found'},
        },
        tags=['Orders'],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsOrderOwnerOrAdministrative], url_path='remove-item')
    def remove_item(self, request, order_id=None):
        """Remove an item from a draft order."""
        from django.db import transaction

        order = self.get_object()
        if order.status != OrderStatusChoices.DRAFT:
            raise ValidationError('Can only remove items from draft orders.')

        serializer = inline_serializer(
            name='OrderRemoveItemRuntimeSerializer',
            fields={
                'order_item_id': serializers.IntegerField(min_value=1),
            },
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        order_item_id = serializer.validated_data['order_item_id']

        with transaction.atomic():
            locked_order = get_object_or_404(Order.objects.select_for_update(), pk=order.pk)
            order_item = get_object_or_404(
                OrderItem.objects.select_for_update(),
                id=order_item_id,
                order=locked_order,
            )

            if order_item.product_variant:
                order_item.product_variant.increment_stock(int(order_item.quantity))

            order_item.delete()

            locked_order.total_amount = locked_order.get_total_amount()
            locked_order.save(update_fields=['total_amount', 'updated_at'])

            if locked_order.order_items.count() == 0:
                locked_order.delete()

            return Response({
                'status': 'success',
                'message': 'Order item removed.',
                'order_total': str(locked_order.total_amount),
            }, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Preview order pricing',
        description=(
            'Simulate product order totals and discount impacts for an attendee without creating a persisted order. '
            'Pass an optional discount_code to see code-based discount reductions on top of any existing attendee discounts.'
        ),
        request=inline_serializer(
            name='OrderPricingPreviewRequest',
            fields={
                'attendee_id': serializers.UUIDField(help_text='Attendee UUID used for pricing context'),
                'discount_code': serializers.CharField(
                    required=False,
                    allow_null=True,
                    allow_blank=True,
                    help_text='Optional discount code to apply when previewing pricing.',
                ),
                'items': serializers.ListField(
                    child=inline_serializer(
                        name='OrderPricingPreviewItem',
                        fields={
                            'product_variant_id': serializers.UUIDField(),
                            'quantity': serializers.IntegerField(min_value=1),
                        }
                    ),
                    min_length=1,
                ),
            },
        ),
        responses={
            200: {
                'description': 'Pricing preview result',
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied'},
        },
        tags=['Orders'],
    )
    @action(detail=False, methods=['post'], url_path='preview-pricing')
    def preview_pricing(self, request):
        from apps.attendee.models import Attendee
        from apps.payments.evaluator import discount_applies
        from apps.payments.models.discounts import DiscountType

        attendee_id = request.data.get('attendee_id')
        items = request.data.get('items') or []

        raw_code = request.data.get('discount_code')
        discount_code = raw_code.strip() if isinstance(raw_code, str) and raw_code.strip() else None
        if discount_code and len(discount_code) > 100:
            discount_code = None

        if not attendee_id:
            raise ValidationError({'attendee_id': 'This field is required.'})
        if not isinstance(items, list) or len(items) == 0:
            raise ValidationError({'items': 'Provide at least one item to preview.'})

        attendee = get_object_or_404(Attendee.objects.select_related('booking', 'event', 'user'), attendee_id=attendee_id)
        self._assert_attendee_access(attendee, request.user)

        attendee_context = attendee.pricing_context(code=discount_code)
        currency_code = 'GBP'
        lines = []
        subtotal = decimal.Decimal('0.00')
        total_discount = decimal.Decimal('0.00')

        for index, item in enumerate(items):
            variant_id = item.get('product_variant_id')
            quantity = item.get('quantity')

            if not variant_id:
                raise ValidationError({'items': f'items[{index}].product_variant_id is required.'})

            try:
                quantity_int = int(quantity)
            except (TypeError, ValueError):
                raise ValidationError({'items': f'items[{index}].quantity must be an integer.'})

            if quantity_int < 1:
                raise ValidationError({'items': f'items[{index}].quantity must be at least 1.'})

            variant = get_object_or_404(
                ProductVariant.objects.select_related('product', 'product__event'),
                variant_id=variant_id,
            )
            if variant.product.event_id != attendee.event_id:
                raise ValidationError({'items': f'Variant {variant.variant_id} does not belong to attendee event.'})
            if not variant.can_attendee_purchase(attendee):
                raise ValidationError({'items': f'Attendee cannot purchase variant {variant.variant_id}.'})
            if not variant.can_attendee_purchase_quantity(attendee, quantity_int):
                raise ValidationError({'items': f'Requested quantity exceeds stock or limits for variant {variant.variant_id}.'})

            modified_amount = variant.modified_amount.amount.quantize(decimal.Decimal('0.01'))
            # Use context-aware pricing so that code-based discounts are included.
            final_amount = variant.total_amount_for_context(attendee_context).amount.quantize(decimal.Decimal('0.01'))
            discount_per_unit = max(modified_amount - final_amount, decimal.Decimal('0.00'))

            line_subtotal = (modified_amount * quantity_int).quantize(decimal.Decimal('0.01'))
            line_total = (final_amount * quantity_int).quantize(decimal.Decimal('0.01'))
            line_discount = (discount_per_unit * quantity_int).quantize(decimal.Decimal('0.01'))

            subtotal += line_subtotal
            total_discount += line_discount

            applied_discounts = []
            for discount in variant.discounts:
                if not discount_applies(discount, attendee_context):
                    continue
                if discount.discount_type == DiscountType.PERCENTAGE:
                    discount_amount = variant.modified_amount * (discount.percentage / decimal.Decimal('100'))
                    value = str(discount.percentage)
                else:
                    discount_amount = discount.amount
                    value = str(discount.amount.amount)
                applied_discounts.append({
                    'discount_id': str(discount.discount_id),
                    'name': discount.name,
                    'discount_type': discount.discount_type,
                    'value': value,
                    'amount': str(discount_amount.amount.quantize(decimal.Decimal('0.01'))),
                    'currency': modified_amount and variant.modified_amount.currency.code or 'GBP',
                })

            lines.append({
                'variant_id': str(variant.variant_id),
                'product_title': variant.product.title,
                'quantity': quantity_int,
                'unit_price_before_discount': str(modified_amount),
                'unit_price': str(final_amount),
                'line_subtotal': str(line_subtotal),
                'line_total': str(line_total),
                'line_discount': str(line_discount),
                'applied_discounts': applied_discounts,
            })

        total_amount = (subtotal - total_discount).quantize(decimal.Decimal('0.01'))
        if total_amount < decimal.Decimal('0.00'):
            total_amount = decimal.Decimal('0.00')

        open_order = Order.objects.filter(
            attendee=attendee,
            status__in=OPEN_ORDER_STATUSES,
        ).order_by('-updated_at').first()

        return Response({
            'attendee_id': str(attendee.attendee_id),
            'event_id': str(attendee.event.event_id) if attendee.event else None,
            'currency': currency_code,
            'discount_code_applied': discount_code or None,
            'has_open_order': bool(open_order),
            'open_order_reference': open_order.order_reference_id if open_order else None,
            'subtotal': str(subtotal.quantize(decimal.Decimal('0.01'))),
            'total_discount': str(total_discount.quantize(decimal.Decimal('0.01'))),
            'total_amount': str(total_amount),
            'items': lines,
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Reserve bank transfer reference for order",
        description=(
            "Create or reuse a draft bank transfer payment for a draft order so the customer can see the reference before checkout."
        ),
        request=inline_serializer(
            name='OrderReserveBankTransferRequest',
            fields={
                'payment_method_id': serializers.IntegerField(help_text='Bank transfer payment method ID for this order event.'),
            },
        ),
        responses={
            201: OpenApiResponse(description='Bank transfer reference reserved.'),
            200: OpenApiResponse(description='Existing bank transfer reference reused.'),
            400: OpenApiResponse(description='Validation error.'),
            404: OpenApiResponse(description='Order not found.'),
        },
        tags=["Orders"],
        operation_id="products_orders_reserve_bank_transfer_payment",
    )
    @action(detail=True, methods=['post'], url_path='reserve-bank-transfer-payment')
    def reserve_bank_transfer_payment(self, request, order_id=None):
        # procedure
        # 1. Validate input and permissions
        # 2. Lock order row for update to prevent concurrent modifications
        # 3. Check if order is in draft status and does not already have a payment linked
        # 4. Validate payment method exists, is active, belongs to the same event, and is of type BANK_TRANSFER
        # 5. Check for existing draft payment with matching method and order metadata to
        #   reuse if already reserved, otherwise create new draft payment with bank transfer reference
        # 6. Return payment details including bank transfer reference for customer to use during checkout
        from apps.payments.models import Payment, PaymentMethod, PaymentMethodTypeChoices, PaymentStatusChoices
        from django.db import transaction
        from djmoney.money import Money

        payment_method_id = request.data.get('payment_method_id')
        if not payment_method_id:
            raise ValidationError({'payment_method_id': 'payment_method_id is required.'})

        with transaction.atomic():
            locked_order = get_object_or_404(
                Order.objects.select_for_update(),
                order_id=order_id,
            )
            self.check_object_permissions(request, locked_order)

            if locked_order.status != OrderStatusChoices.DRAFT:
                raise ValidationError({'order': 'Only draft orders can reserve a bank transfer reference.'})

            if locked_order.payment_id:
                raise ValidationError({'order': 'Order already has a payment linked.'})

            if locked_order.total_amount.amount <= 0:
                raise ValidationError({'order': 'Bank transfer reservation is only available for payable orders.'})

            if not locked_order.attendee or not locked_order.attendee.event:
                raise ValidationError({'order': 'Order attendee/event context is required.'})

            try:
                payment_method = PaymentMethod.objects.get(
                    id=payment_method_id,
                    event=locked_order.attendee.event,
                    is_active=True,
                )
            except PaymentMethod.DoesNotExist:
                raise ValidationError({'payment_method_id': 'Payment method not found for this event.'})

            if payment_method.method_type != PaymentMethodTypeChoices.BANK_TRANSFER:
                raise ValidationError({'payment_method_id': 'Only BANK_TRANSFER methods can be reserved.'})

            existing_checkout_payment = Payment.objects.filter(
                user=request.user,
                event=locked_order.attendee.event,
                method=payment_method,
                metadata__order_id=str(locked_order.order_id),
                metadata__payment_type='order_checkout_pending_finalization',
            ).exclude(
                status__in=[PaymentStatusChoices.CANCELLED, PaymentStatusChoices.FAILED]
            ).order_by('-created_at').first()

            if existing_checkout_payment:
                return Response({
                    'order_id': str(locked_order.order_id),
                    'order_reference': locked_order.order_reference_id,
                    'payment_id': str(existing_checkout_payment.payment_id),
                    'payment_reference': existing_checkout_payment.payment_reference,
                    'bank_transfer_reference': existing_checkout_payment.bank_transfer_reference,
                    'status': existing_checkout_payment.status,
                    'message': 'Checkout payment already exists for this order.',
                }, status=status.HTTP_200_OK)

            existing_reservation = Payment.objects.filter(
                user=request.user,
                event=locked_order.attendee.event,
                method=payment_method,
                status=PaymentStatusChoices.DRAFTING,
                metadata__contains={
                    'order_id': str(locked_order.order_id),
                    'payment_type': 'order_checkout_reservation',
                },
            ).order_by('-created_at').first()

            if existing_reservation:
                return Response({
                    'order_id': str(locked_order.order_id),
                    'order_reference': locked_order.order_reference_id,
                    'payment_id': str(existing_reservation.payment_id),
                    'payment_reference': existing_reservation.payment_reference,
                    'bank_transfer_reference': existing_reservation.bank_transfer_reference,
                    'status': existing_reservation.status,
                    'message': 'Bank transfer reference already reserved for this order.',
                }, status=status.HTTP_200_OK)

            payment = Payment.objects.create(
                user=request.user,
                event=locked_order.attendee.event,
                method=payment_method,
                base_amount=Money(locked_order.total_amount.amount, locked_order.total_amount.currency.code),
                percentage_modifier=decimal.Decimal('0.00'),
                description=f"Bank transfer reservation for order {locked_order.order_reference_id}",
                status=PaymentStatusChoices.DRAFTING,
                target=locked_order,
                metadata={
                    'order_id': str(locked_order.order_id),
                    'order_reference': locked_order.order_reference_id,
                    'payment_type': 'order_checkout_reservation',
                    'order_checkout_finalized': False,
                },
            )

            return Response({
                'order_id': str(locked_order.order_id),
                'order_reference': locked_order.order_reference_id,
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'bank_transfer_reference': payment.bank_transfer_reference,
                'status': payment.status,
                'message': 'Bank transfer reference reserved.',
            }, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Checkout order with payment",
        description="Complete order checkout by creating payment. Handles STRIPE (returns client_secret), BANK_TRANSFER (returns reference), and CASH (pending approval at venue). Free orders (£0) skip payment creation. Order must be in PENDING status.",
        request=inline_serializer(
            name='OrderCheckoutRequest',
            fields={
                'payment_method_id': serializers.IntegerField(
                    required=False,
                    allow_null=True,
                    help_text="Optional payment method ID. Required when order total is greater than 0."
                ),
                'payment_id': serializers.UUIDField(
                    required=False,
                    allow_null=True,
                    help_text="Optional reserved bank transfer payment UUID to reuse during checkout."
                ),
                'discount_code': serializers.CharField(
                    required=False,
                    allow_null=True,
                    allow_blank=True,
                    help_text="Optional discount code. When valid, the payment amount will reflect the discounted total."
                ),
            }
        ),
        responses={
            201: {
                'description': 'Checkout successful',
                'content': {
                    'application/json': {
                        'examples': {
                            'stripe': {
                                'summary': 'Stripe payment',
                                'value': {
                                    'order_id': 'uuid-here',
                                    'order_reference': 'ORD-12345',
                                    'payment_reference': 'PAY-1-1-ABC123',
                                    'total_amount': '50.00',
                                    'currency': 'GBP',
                                    'status': 'pending_payment',
                                    'stripe_client_secret': 'pi_xxx_secret_yyy',
                                    '_links': {}
                                }
                            },
                            'bank_transfer': {
                                'summary': 'Bank transfer payment',
                                'value': {
                                    'order_id': 'uuid-here',
                                    'order_reference': 'ORD-12345',
                                    'payment_reference': 'PAY-1-1-ABC123',
                                    'total_amount': '50.00',
                                    'currency': 'GBP',
                                    'status': 'pending_verification',
                                    'bank_transfer_reference': 'BNK-ABC123XYZ',
                                    'bank_transfer_instructions': 'Transfer £50.00 to account...',
                                    '_links': {}
                                }
                            },
                            'cash': {
                                'summary': 'Cash payment',
                                'value': {
                                    'order_id': 'uuid-here',
                                    'order_reference': 'ORD-12345',
                                    'payment_reference': 'PAY-1-1-ABC123',
                                    'total_amount': '50.00',
                                    'currency': 'GBP',
                                    'status': 'pending_approval',
                                    '_links': {}
                                }
                            },
                            'free': {
                                'summary': 'Free order',
                                'value': {
                                    'order_id': 'uuid-here',
                                    'order_reference': 'ORD-12345',
                                    'total_amount': '0.00',
                                    'currency': 'GBP',
                                    'status': 'processing',
                                    'message': 'Free order, no payment required',
                                    '_links': {}
                                }
                            }
                        }
                    }
                }
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied'},
            404: {'description': 'Order not found'}
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=['post'])
    def checkout(self, request, order_id=None):
        """
        Checkout order with payment.
        
        Creates payment for the order and handles different payment methods:
        - STRIPE: Creates Stripe PaymentIntent, returns client_secret
        - BANK_TRANSFER: Generates bank reference, returns instructions
        - CASH: Marks as pending (approved at venue)
        - FREE: Skips payment if order total is £0
        """
        from apps.products.api.serializers import OrderCheckoutSerializer
        from apps.payments.models import BankTransferEvidence, Payment, PaymentStatusChoices, PaymentMethodTypeChoices
        from apps.payments.services.stripe.payment_intents import PaymentIntentService
        from django.db import transaction
        import logging
        
        logger = logging.getLogger(__name__)

        with transaction.atomic():
            # Use a minimal queryset for row locking to avoid FOR UPDATE on nullable outer joins.
            locked_order = get_object_or_404(
                Order.objects.select_for_update(),
                order_id=order_id,
            )
            self.check_object_permissions(request, locked_order)

            serializer = OrderCheckoutSerializer(
                data=request.data,
                context={'request': request, 'order': locked_order}
            )
            serializer.is_valid(raise_exception=True)

            payment_method = serializer.validated_data['payment_method']
            reserved_payment = serializer.validated_data.get('reserved_payment')
            bank_transfer_evidence_payload = serializer.validated_data.get('_bank_transfer_evidence_payload')
            discount_code = serializer.validated_data.get('discount_code') or None

            # Check if order is free (£0 total)
            if locked_order.total_amount.amount == 0:
                logger.info(f"Processing free order {locked_order.order_reference_id}, moving from DRAFT to PROCESSING")
                if locked_order.status == OrderStatusChoices.DRAFT:
                    locked_order.transition_to(OrderStatusChoices.PENDING)
                    logger.info(f"Free order {locked_order.order_reference_id} transitioned to pending")
                    locked_order.transition_to(OrderStatusChoices.PROCESSING)
                    logger.info(f"Free order {locked_order.order_reference_id} transitioned to processing")
                else:
                    raise ValidationError({'order': f'Cannot checkout free order in {locked_order.status} status.'})

                return Response({
                    'order_id': str(locked_order.order_id),
                    'order_reference': locked_order.order_reference_id,
                    'total_amount': str(locked_order.total_amount.amount),
                    'currency': str(locked_order.total_amount.currency.code),
                    'status': 'processing',
                    'message': 'Free order, no payment required',
                    '_links': {
                        'self': request.build_absolute_uri(),
                        'order': request.build_absolute_uri(f'/api/products/orders/list/{locked_order.order_id}/')
                    }
                }, status=status.HTTP_201_CREATED)

            if locked_order.payment_id:
                raise ValidationError({'order': 'Order already has a payment linked. Refresh and continue from existing checkout state.'})

            attendee = locked_order.attendee
            order_event = attendee.event if attendee else None
            if not attendee or not order_event:
                raise ValidationError({
                    'order': 'Order must have an attendee with valid event context before checkout.'
                })

            locked_order.transition_to(OrderStatusChoices.PENDING)

            # ----------------------------------------------------------------
            # Recalculate the payment total using the attendee's pricing context
            # so that code-based discounts (CODE_MATCHES rules) are applied on
            # top of any non-code discounts already captured in order.total_amount.
            # When no code is supplied the result equals order.total_amount.
            # ----------------------------------------------------------------
            

            attendee_context = attendee.pricing_context(code=discount_code)
            discounted_total = Money(0, locked_order.total_amount.currency.code)
            applied_discounts_snapshot = []

            for item_idx, order_item in enumerate(
                locked_order.order_items.select_related('product_variant__product').all()
            ):
                variant = order_item.product_variant
                if not variant:
                    discounted_total += order_item.total_price
                    continue

                item_unit_price = variant.total_amount_for_context(attendee_context)
                item_line_total = item_unit_price * order_item.quantity
                discounted_total += item_line_total

                # Build per-item discount breakdown for metadata snapshot.
                item_discount_breakdown = []
                for disc in variant.discounts:
                    if not _discount_applies(disc, attendee_context):
                        continue
                    if disc.discount_type == _DiscountType.PERCENTAGE:
                        disc_amount = variant.modified_amount * (disc.percentage / decimal.Decimal('100'))
                        disc_value = str(disc.percentage)
                    else:
                        disc_amount = disc.amount
                        disc_value = str(disc.amount.amount)
                    item_discount_breakdown.append({
                        'discount_id': str(disc.discount_id),
                        'name': disc.name,
                        'discount_type': disc.discount_type,
                        'value': disc_value,
                        'amount': str(disc_amount.amount.quantize(decimal.Decimal('0.01'))),
                        'currency': disc_amount.currency.code,
                    })

                per_unit_discount = max(
                    variant.modified_amount.amount - item_unit_price.amount,
                    decimal.Decimal('0.00'),
                )
                applied_discounts_snapshot.append({
                    'item_index': item_idx,
                    'variant_id': str(variant.variant_id),
                    'product_title': variant.product.title if variant.product else '',
                    'quantity': order_item.quantity,
                    'unit_price_before_discount': str(variant.modified_amount.amount.quantize(decimal.Decimal('0.01'))),
                    'unit_price_after_discount': str(item_unit_price.amount.quantize(decimal.Decimal('0.01'))),
                    'total_discount': str((per_unit_discount * order_item.quantity).quantize(decimal.Decimal('0.01'))),
                    'currency': item_unit_price.currency.code,
                    'discount_breakdown': item_discount_breakdown,
                })

            if discounted_total.amount < decimal.Decimal('0.00'):
                discounted_total = Money(decimal.Decimal('0.00'), locked_order.total_amount.currency.code)

            attendee_name = (
                f"{attendee.first_name} {attendee.last_name}".strip()
                or str(attendee.attendee_id)
            )
            payment_description = (
                f"Payment made for attendee {attendee_name} "
                f"for {order_event.title} with price of {discounted_total}"
            )

            payment_metadata_base = {
                **(locked_order.get_metadata() or {}),
                'order_id': str(locked_order.order_id),
                'order_reference': locked_order.order_reference_id,
                'payment_type': 'order_checkout_pending_finalization',
                'discount_code': discount_code,
                'applied_discounts_snapshot': applied_discounts_snapshot,
            }

            if reserved_payment:
                payment = reserved_payment
                payment.base_amount = discounted_total
                payment.description = payment_description
                payment.target = locked_order

                merged_metadata = payment.metadata if isinstance(payment.metadata, dict) else {}
                merged_metadata.update(payment_metadata_base)
                payment.metadata = merged_metadata

                payment.status = PaymentStatusChoices.PENDING
                payment.save()
            else:
                # Create payment for non-free orders
                payment = Payment.objects.create(
                    user=request.user,
                    event=order_event,
                    method=payment_method,
                    base_amount=discounted_total,
                    status=PaymentStatusChoices.PENDING,
                    target=locked_order,
                    description=payment_description,
                    metadata=payment_metadata_base,
                )

            bank_transfer_evidence = None
            if payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER and bank_transfer_evidence_payload:
                evidence_kwargs = {
                    'payment': payment,
                    'transfer_id': payment.bank_transfer_reference,
                    'evidence_file': bank_transfer_evidence_payload['evidence_file'],
                }
                if bank_transfer_evidence_payload.get('payer_name'):
                    evidence_kwargs['payer_name'] = bank_transfer_evidence_payload['payer_name']
                if bank_transfer_evidence_payload.get('payer_account_last4'):
                    evidence_kwargs['payer_account_last4'] = bank_transfer_evidence_payload['payer_account_last4']
                if bank_transfer_evidence_payload.get('amount_on_evidence'):
                    evidence_kwargs['amount_on_evidence'] = bank_transfer_evidence_payload['amount_on_evidence']

                try:
                    bank_transfer_evidence = BankTransferEvidence.objects.create(**evidence_kwargs)
                except Exception as exc:
                    raise ValidationError({'bank_transfer_evidence': str(exc)})
            
            # Link payment to order
            locked_order.payment = payment
            locked_order.save(update_fields=['payment', 'updated_at'])
            
            logger.info(
                f"Created payment {payment.payment_reference} for order {locked_order.order_reference_id}, "
                f"amount: {discounted_total} (original: {locked_order.total_amount})"
            )
            
            # Prepare response data with amount and currency as separate fields
            response_data = {
                'order_id': str(locked_order.order_id),
                'order_reference': locked_order.order_reference_id,
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'payment_description': payment.description,
                'total_amount': str(discounted_total.amount),
                'currency': str(discounted_total.currency.code),
                'discount_code_applied': discount_code or None,
                'bank_transfer_evidence_id': str(bank_transfer_evidence.bank_transfer_id) if bank_transfer_evidence else None,
                '_links': {
                    'self': request.build_absolute_uri(),
                    'order': request.build_absolute_uri(f'/api/products/orders/list/{locked_order.order_id}/'),
                    'payment': request.build_absolute_uri(f'/api/payments/list/{payment.payment_id}/')
                }
            }
            
            # Handle payment method-specific logic.
            # Normalize method type to avoid silent fallthrough for unexpected casing/whitespace.
            method_type = str(payment_method.method_type or '').strip().upper()

            if method_type == PaymentMethodTypeChoices.STRIPE:
                # Create Stripe PaymentIntent
                try:
                    stripe_metadata = payment.prepare_stripe_metadata()
                    payment_intent = PaymentIntentService.create(
                        amount=discounted_total,
                        currency=discounted_total.currency.code,
                        payment_reference=payment.payment_reference,
                        customer_email=request.user.email,
                        metadata=stripe_metadata,
                        description=payment.description,
                        stripe_account_id=payment_method.get_stripe_account_id(),
                    )
                    
                    payment.stripe_payment_intent = payment_intent['id']
                    payment.save()
                    
                    response_data['stripe_client_secret'] = payment_intent['client_secret']
                    response_data['status'] = 'pending_payment'
                    
                    logger.info(f"Created Stripe PaymentIntent {payment_intent['id']} for payment {payment.payment_reference}")
                    
                except Exception as e:
                    logger.error(f"Failed to create Stripe PaymentIntent for payment {payment.payment_reference}: {e}")
                    # Rollback will happen automatically due to atomic block
                    raise ValidationError({'stripe': f'Failed to create payment intent: {str(e)}'})
            
            elif method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
                # Generate bank transfer reference (already done in Payment model)
                response_data['bank_transfer_reference'] = payment.bank_transfer_reference
                response_data['bank_transfer_instructions'] = (
                    f"Please transfer {discounted_total} to the event account using reference: "
                    f"{payment.bank_transfer_reference}. Your order will be processed after verification."
                )
                response_data['status'] = 'pending_verification'
                
                logger.info(f"Generated bank transfer reference {payment.bank_transfer_reference} for payment {payment.payment_reference}")
            
            elif method_type == PaymentMethodTypeChoices.CASH:
                # Cash payment - pending approval at venue
                response_data['status'] = 'pending_approval'
                response_data['message'] = 'Payment will be collected at the venue. Your order will be processed after payment confirmation.'
                
                logger.info(f"Cash payment created for order {locked_order.order_reference_id}, pending venue approval")

            else:
                logger.error(
                    'Unsupported payment method type during checkout. method_id=%s method_type=%s order=%s',
                    payment_method.id,
                    payment_method.method_type,
                    locked_order.order_reference_id,
                )
                raise ValidationError({
                    'payment_method_id': (
                        f'Unsupported payment method type "{payment_method.method_type}". '
                        'Please select a valid payment method.'
                    )
                })

            
            return Response(response_data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Validate a discount code for an order",
        description=(
            "Check whether a discount code is valid for the products in a specific order. "
            "A code is considered valid when at least one active CODE_MATCHES DiscountRule "
            "exists whose parent Discount targets a Product or ProductVariant present in the order. "
            "Returns only {\"valid\": true/false} to prevent code enumeration."
        ),
        request=inline_serializer(
            name='OrderValidateCodeRequest',
            fields={
                'code': serializers.CharField(help_text='Discount code to validate'),
                'order_id': serializers.UUIDField(help_text='UUID of the order to validate the code against'),
            },
        ),
        responses={
            200: {
                'description': 'Validation result',
                'content': {
                    'application/json': {
                        'schema': {
                            'type': 'object',
                            'properties': {'valid': {'type': 'boolean'}},
                        }
                    }
                },
            },
            400: {'description': 'Validation error'},
            429: {'description': 'Rate limit exceeded'},
        },
        tags=['Orders'],
    )
    @action(
        detail=False,
        methods=['post'],
        url_path='validate-code',
        permission_classes=[permissions.IsAuthenticated],
    )
    def validate_code(self, request):
        """
        Validate a discount code against the products in a specific order.
        Returns only {"valid": bool} — no detail to prevent code enumeration.
        """
        from apps.payments.models.discounts import DiscountRuleTypeChoices
        from apps.payments.models import DiscountRule

        code = request.data.get('code')
        order_id = request.data.get('order_id')

        if not code or not isinstance(code, str):
            raise ValidationError({'code': 'A non-empty string code is required.'})

        if not order_id:
            raise ValidationError({'order_id': 'order_id is required.'})

        code = code.strip()
        if len(code) > 100:
            return Response({'valid': False}, status=status.HTTP_200_OK)

        order = get_object_or_404(
            Order.objects.select_related('attendee'),
            order_id=order_id,
        )

        # Ensure the requesting user owns this order (or is staff).
        if not request.user.is_staff and order.customer_id != request.user.id:
            return Response({'valid': False}, status=status.HTTP_200_OK)

        # Collect all product PKs and variant PKs present in the order.
        product_pks = []
        variant_pks = []
        for item in order.order_items.all():
            if item.product_variant:
                variant_pks.append(item.product_variant.pk)
                if item.product_variant.product_id:
                    product_pks.append(item.product_variant.product_id)

        if not product_pks and not variant_pks:
            return Response({'valid': False}, status=status.HTTP_200_OK)

        product_ct = ContentType.objects.get_for_model(Product)
        variant_ct = ContentType.objects.get_for_model(ProductVariant)

        valid = DiscountRule.objects.filter(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            value=code,
            active=True,
            discount__active=True,
        ).filter(
            Q(discount__target_type=product_ct, discount__target_id__in=product_pks)
            | Q(discount__target_type=variant_ct, discount__target_id__in=variant_pks)
        ).exists()

        return Response({'valid': valid}, status=status.HTTP_200_OK)


# ============================================================================
# ORDER ITEM VIEWSETS (Read-only)
# ============================================================================

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
