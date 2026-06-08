from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes

from apps.common.models import Resource
from apps.payments.models import Discount, DiscountRule
from apps.products.models import Product
from apps.payments.api.serializers import (
    DiscountListSerializer, DiscountDetailSerializer, DiscountCreateUpdateSerializer
)
from apps.products.api.serializers import (
    ProductListSerializer, ProductDetailSerializer, ProductCreateSerializer, ProductUpdateSerializer,
EventInventoryBreakdownSerializer, InventoryAttendeeSerializer
)
from apps.products.api.filtersets import ProductFilterSet
from apps.products.api.permissions import IsAdministrativeStaffOnly, CanManageProducts
from apps.payments.services.evaluator import discount_applies as _discount_applies
from apps.common.pagination import StandardPagination
from apps.products.api.viewsets.mixins import PurchaseContextMixin

User = get_user_model()


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

    @extend_schema(
        summary="Event inventory breakdown",
        description=(
            "Returns a complete inventory breakdown for every product in the specified event. "
            "For each variant the response includes: current stock, in-flight live order units "
            "and their cost, units to reorder (when a max_stock_quantity cap is set), unit price, "
            "and the cost to fully restock. Aggregate totals are provided at the product and "
            "event level. Intended for end-of-day admin restocking reports."
        ),
        parameters=[
            OpenApiParameter(
                name='event',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="URL-safe title of the event (`url_safe_title` field). Required.",
                required=True,
            ),
            OpenApiParameter(
                name='is_active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter products by active status (true or false).",
                required=False,
            ),
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Filter products by category ID.",
                required=False,
            ),
            OpenApiParameter(
                name='product',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Narrow results to a single product by its UUID.",
                required=False,
            ),
            OpenApiParameter(
                name='size',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filter variants by size code (e.g. SM, LG, OS). Case-insensitive.",
                required=False,
            ),
            OpenApiParameter(
                name='color',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filter variants by hex colour (e.g. #FF0000). Case-insensitive.",
                required=False,
            ),
            OpenApiParameter(
                name='needs_reorder',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="If true, only return variants where quantity_to_order > 0.",
                required=False,
            ),
            OpenApiParameter(
                name='has_stock',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="If true, only return variants where current_stock > 0.",
                required=False,
            ),
        ],
        responses={
            200: EventInventoryBreakdownSerializer,
            400: OpenApiResponse(description="Missing or invalid `event` query parameter."),
            403: OpenApiResponse(description="Permission denied – administrative access required."),
            404: OpenApiResponse(description="No event found matching the supplied slug."),
        },
        tags=["Products"],
        operation_id="products_inventory_breakdown",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="inventory",
        permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly],
    )
    def inventory(self, request):
        """Return the inventory breakdown for an event (admin-only)."""
        from apps.events.models import Event
        from apps.products.services.inventory import compute_event_inventory

        event_slug = request.query_params.get("event", "").strip()
        if not event_slug:
            raise ValidationError({"event": "The 'event' query parameter is required."})

        try:
            event = Event.objects.get(url_safe_title=event_slug)
        except Event.DoesNotExist:
            return Response(
                {"detail": f"No event found with url_safe_title '{event_slug}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        def _parse_bool(key: str):
            val = request.query_params.get(key)
            if val is None:
                return None
            return val.lower() in ("true", "1", "yes")

        def _parse_int(key: str):
            val = request.query_params.get(key)
            if val is None:
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                raise ValidationError({key: f"'{val}' is not a valid integer."})

        summary = compute_event_inventory(
            event,
            is_active=_parse_bool("is_active"),
            category_id=_parse_int("category"),
            product_id=request.query_params.get("product") or None,
            size=request.query_params.get("size") or None,
            color=request.query_params.get("color") or None,
            needs_reorder=_parse_bool("needs_reorder"),
            has_stock=_parse_bool("has_stock"),
        )
        serializer = EventInventoryBreakdownSerializer(summary)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Attendees by product variant",
        description=(
            "Returns a paginated list of attendees who have purchased a specific product variant, "
            "enriched with order context (order reference, status, quantity, price). "
            "Requires both `event` and `product_variant` parameters."
        ),
        parameters=[
            OpenApiParameter(
                name='event',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="URL-safe title of the event (`url_safe_title` field). Required.",
                required=True,
            ),
            OpenApiParameter(
                name='product_variant',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="UUID of the product variant to query. Required.",
                required=True,
            ),
            OpenApiParameter(
                name='order_status',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter by order status. One of: draft, pending, processing, "
                    "completed, cancelled, pending_refund, partially_refunded, refunded."
                ),
                required=False,
            ),
            OpenApiParameter(
                name='item_status',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter by order item status. One of: pending, completed, cancelled, "
                    "pending_refund, refunded."
                ),
                required=False,
            ),
            OpenApiParameter(
                name='attendee_status',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filter by attendee registration status (e.g. registered, checked_in).",
                required=False,
            ),
        ],
        responses={
            200: InventoryAttendeeSerializer(many=True),
            400: OpenApiResponse(description="Missing required query parameters."),
            403: OpenApiResponse(description="Permission denied – administrative access required."),
            404: OpenApiResponse(description="Event or variant not found."),
        },
        tags=["Products"],
        operation_id="products_inventory_attendees",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="inventory/attendees",
        permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly],
    )
    def inventory_attendees(self, request):
        """Return a paginated list of attendees who hold a specific product variant (admin-only)."""
        from apps.events.models import Event
        from apps.products.models.orders import OrderItem

        event_slug = request.query_params.get("event", "").strip()
        variant_uuid = request.query_params.get("product_variant", "").strip()

        if not event_slug:
            raise ValidationError({"event": "The 'event' query parameter is required."})
        if not variant_uuid:
            raise ValidationError({"product_variant": "The 'product_variant' query parameter is required."})

        try:
            event = Event.objects.get(url_safe_title=event_slug)
        except Event.DoesNotExist:
            return Response(
                {"detail": f"No event found with url_safe_title '{event_slug}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            from apps.products.models import ProductVariant
            variant = ProductVariant.objects.get(variant_id=variant_uuid, product__event=event)
        except ProductVariant.DoesNotExist:
            return Response(
                {"detail": f"No variant found with id '{variant_uuid}' for this event."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = (
            OrderItem.objects
            .filter(
                product_variant=variant,
                order__attendee__isnull=False,
            )
            .select_related(
                "order",
                "order__attendee",
            )
            .values(
                "order__attendee__attendee_id",
                "order__attendee__attendee_display_id",
                "order__attendee__first_name",
                "order__attendee__last_name",
                "order__attendee__email",
                "order__attendee__status",
                "order__order_id",
                "order__order_reference_id",
                "order__status",
                "status",
                "quantity",
                "unit_price",
                "unit_price_currency",
                "total_price",
                "total_price_currency",
            )
            .order_by("order__attendee__last_name", "order__attendee__first_name")
        )

        # Optional filters
        order_status = request.query_params.get("order_status")
        item_status = request.query_params.get("item_status")
        attendee_status = request.query_params.get("attendee_status")

        if order_status:
            qs = qs.filter(order__status=order_status)
        if item_status:
            qs = qs.filter(status=item_status)
        if attendee_status:
            qs = qs.filter(order__attendee__status=attendee_status)

        # Paginate
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = InventoryAttendeeSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)