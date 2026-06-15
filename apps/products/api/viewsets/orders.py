
from rest_framework import viewsets, status, permissions, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
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

from apps.products.models import (
    Product, ProductVariant,
    Order, OrderItem, OrderStatusChoices, OPEN_ORDER_STATUSES,
)

from apps.products.api.serializers import (
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer, OrderUpdateSerializer,
    OrderItemSerializer, OrderItemCreateSerializer,
)
from apps.products.api.filtersets import OrderFilterSet
from apps.products.api.permissions import IsAdministrativeStaffOnly, IsOrderOwnerOrAdministrative
from apps.payments.services.evaluator import discount_applies as _discount_applies
from apps.payments.models.discounts import DiscountType as _DiscountType
from apps.common.pagination import StandardPagination
from djmoney.money import Money

from apps.events.services.notifications import create_notification, NotificationTypeChoices, NotificationPriorityChoices
from apps.products.tasks import send_order_pending_bank_transfer_email

from django.db import transaction
import logging

import decimal

User = get_user_model()

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
        from apps.payments.services.evaluator import discount_applies
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
            # if not variant.can_attendee_purchase_quantity(attendee, quantity_int):
            #     raise ValidationError({'items': f'Requested quantity exceeds stock or limits for variant {variant.variant_id}.'})
            variant.can_attendee_purchase_quantity(attendee, quantity_int, raise_exception=True)

            modified_amount = variant.modified_amount.amount.quantize(decimal.Decimal('0.01'))
            # Discounts are attached to the parent Product; apply them against
            # the variant's own price so that per-variant pricing is respected.
            product_discount_money = variant.product.calculate_total_discounts(
                discount_base=variant.modified_amount,
                context=attendee_context,
            )
            final_money = variant.modified_amount - product_discount_money
            if final_money.amount < decimal.Decimal('0.00'):
                final_money = Money(decimal.Decimal('0.00'), final_money.currency)
            final_amount = final_money.amount.quantize(decimal.Decimal('0.01'))
            discount_per_unit = max(modified_amount - final_amount, decimal.Decimal('0.00'))

            line_subtotal = (modified_amount * quantity_int).quantize(decimal.Decimal('0.01'))
            line_total = (final_amount * quantity_int).quantize(decimal.Decimal('0.01'))
            line_discount = (discount_per_unit * quantity_int).quantize(decimal.Decimal('0.01'))

            subtotal += line_subtotal
            total_discount += line_discount

            applied_discounts = []
            for discount in variant.product.discounts:
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

                # Discounts are attached to the parent Product; apply them against
                # the variant's own price so that per-variant pricing is respected.
                product_discount_money = variant.product.calculate_total_discounts(
                    discount_base=variant.modified_amount,
                    context=attendee_context,
                )
                item_unit_price = variant.modified_amount - product_discount_money
                if item_unit_price.amount < decimal.Decimal('0.00'):
                    item_unit_price = Money(decimal.Decimal('0.00'), item_unit_price.currency)
                rounded_unit_price = Money(
                    item_unit_price.amount.quantize(decimal.Decimal('0.01')),
                    item_unit_price.currency,
                )
                item_line_total = rounded_unit_price * order_item.quantity
                discounted_total += item_line_total

                # Persist the discounted price on the item so the order record
                # stays consistent with the actual charged amount.
                if rounded_unit_price != order_item.unit_price:
                    order_item.set_unit_price(rounded_unit_price)

                # Build per-item discount breakdown for metadata snapshot.
                item_discount_breakdown = []
                for disc in variant.product.discounts:
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
                    variant.modified_amount.amount - rounded_unit_price.amount,
                    decimal.Decimal('0.00'),
                )
                applied_discounts_snapshot.append({
                    'item_index': item_idx,
                    'variant_id': str(variant.variant_id),
                    'product_title': variant.product.title if variant.product else '',
                    'quantity': order_item.quantity,
                    'unit_price_before_discount': str(variant.modified_amount.amount.quantize(decimal.Decimal('0.01'))),
                    'unit_price_after_discount': str(rounded_unit_price.amount),
                    'total_discount': str((per_unit_discount * order_item.quantity).quantize(decimal.Decimal('0.01'))),
                    'currency': rounded_unit_price.currency.code,
                    'discount_breakdown': item_discount_breakdown,
                })

            if discounted_total.amount < decimal.Decimal('0.00'):
                discounted_total = Money(decimal.Decimal('0.00'), locked_order.total_amount.currency.code)

            # Bring the order total in line with the updated item prices.
            locked_order.recalculate_total_amount()

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
                'total_amount': str(discounted_total.amount.quantize(decimal.Decimal('0.01'))),
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

                _order_pk = locked_order.pk
                _payment_pk = payment.pk
                transaction.on_commit(
                    lambda: send_order_pending_bank_transfer_email.delay(_order_pk, _payment_pk)
                )
                logger.info(
                    "Queued pending bank transfer email for order %s (payment %s)",
                    locked_order.order_reference_id,
                    payment.payment_reference,
                )

                create_notification(
                    payment=payment,
                    locked_order=locked_order,
                    event=order_event,
                    message=(
                        f"New order {locked_order.order_reference_id} is pending bank transfer payment. "
                        f"Amount: {discounted_total}, Reference: {payment.bank_transfer_reference}"
                    ),
                    notification_type=NotificationTypeChoices.ORDER_FULFILLMENT,
                    priority=NotificationPriorityChoices.HIGH,
                )
            
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

        # Discounts are attached to Products only — collect the product PKs for
        # every variant in the order.
        product_pks = []
        for item in order.order_items.all():
            if item.product_variant and item.product_variant.product_id:
                product_pks.append(item.product_variant.product_id)

        if not product_pks:
            return Response({'valid': False}, status=status.HTTP_200_OK)

        product_ct = ContentType.objects.get_for_model(Product)

        valid = DiscountRule.objects.filter(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            value=code,
            active=True,
            discount__active=True,
            discount__target_type=product_ct,
            discount__target_id__in=product_pks,
        ).exists()

        return Response({'valid': valid}, status=status.HTTP_200_OK)