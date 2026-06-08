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
)
from drf_spectacular.types import OpenApiTypes

from apps.products.models import ProductVariant
from apps.common.models import Resource
from apps.payments.models import Discount, DiscountRule
from apps.payments.api.serializers import (
    DiscountListSerializer, DiscountDetailSerializer, DiscountCreateUpdateSerializer
)
from apps.products.api.serializers import (
    ProductVariantListSerializer, ProductVariantDetailSerializer, ProductVariantCreateUpdateSerializer,
)
from apps.products.api.filtersets import ProductVariantFilterSet
from apps.products.api.permissions import IsAdministrativeStaffOnly, CanManageProducts
from apps.products.api.viewsets.mixins import PurchaseContextMixin

from apps.payments.services.evaluator import discount_applies as _discount_applies
from apps.common.pagination import StandardPagination  
User = get_user_model()

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