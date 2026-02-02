"""
Production-grade viewsets for the bookings app.

Provides comprehensive viewsets for booking management with proper validation,
business logic separation, schema configuration, nested routes, and permission classes.

ViewSets:
    - BookingViewSet: Full CRUD for bookings with nested attendees and tickets routes
    - TicketTypeViewSet: Manage ticket types
    - TicketViewSet: Read-only ticket viewing (tickets created server-side)
    - BookingPackageViewSet: Manage booking packages with eligibility checks
    - EventAlternativeSigninViewSet: Admin-only management of event alternative signins
    - AttendeeAlternativeSigninViewSet: Admin-only management of attendee alternative signins

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any

from apps.bookings.models import (
    Booking, BookingIntent, BookingIntentStatusChoices,
    BookingPackage, BookingPackageRule,
    TicketType, Ticket,
    EventAlternativeSigninIdentifier, AttendeeAlternativeSigninIdentifier,
)
from .serializers import (
    BookingListSerializer, BookingDetailSerializer, BookingCreateSerializer, BookingUpdateSerializer,
    BookingIntentListSerializer, BookingIntentDetailSerializer, BookingIntentCreateSerializer, BookingIntentUpdateSerializer,
    TicketTypeListSerializer, TicketTypeDetailSerializer, TicketTypeCreateUpdateSerializer,
    TicketListSerializer, TicketDetailSerializer,
    BookingPackageListSerializer, BookingPackageDetailSerializer, BookingPackageCreateUpdateSerializer,
    BookingPackageRuleSerializer, BookingPackageRuleCreateUpdateSerializer,
    EventAlternativeSigninListSerializer, EventAlternativeSigninDetailSerializer, EventAlternativeSigninCreateUpdateSerializer,
    AttendeeAlternativeSigninListSerializer, AttendeeAlternativeSigninDetailSerializer, AttendeeAlternativeSigninCreateUpdateSerializer,
    CheckoutSerializer,
)
from .filtersets import (
    BookingFilterSet, BookingIntentFilterSet,
    TicketFilterSet, TicketTypeFilterSet, BookingPackageFilterSet,
    EventAlternativeSigninFilterSet, AttendeeAlternativeSigninFilterSet,
)
from .permissions import (
    IsAdministrativeStaff, IsAdministrativeStaffOnly, IsBookingOwnerOrAdministrative,
    IsTicketOwnerOrAdministrative, IsReadOnly,
)


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration for booking endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================================
# BOOKING VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List bookings",
        description="Retrieve a paginated list of bookings. Users see their own bookings, admins see all.",
        tags=["Bookings"],
    ),
    retrieve=extend_schema(
        summary="Retrieve booking details",
        description="Get detailed information about a specific booking including attendees, tickets, and payments.",
        tags=["Bookings"],
    ),
    create=extend_schema(
        summary="Create booking",
        description="Create a new booking for an event. Booking reference is auto-generated. Requires a valid booking intent ID passed as query parameter 'intent'. The intent must be pending, not expired, and belong to the requesting user. Admin users can bypass this requirement.",
        tags=["Bookings"],
        parameters=[
            OpenApiParameter(
                name='intent',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='UUID of the booking intent. Required for non-admin users.',
                required=False,
            ),
        ],
    ),
    update=extend_schema(
        summary="Update booking",
        description="Update an existing booking. Only certain fields can be modified.",
        tags=["Bookings"],
    ),
    partial_update=extend_schema(
        summary="Partially update booking",
        description="Partially update a booking. Only certain fields can be modified.",
        tags=["Bookings"],
    ),
    destroy=extend_schema(
        summary="Delete booking",
        description="Delete a booking. Only allowed if no tickets have been issued.",
        tags=["Bookings"],
    ),
)
class BookingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing bookings.
    
    Provides:
    - List/Retrieve: Users see their own bookings, admins see all
    - Create: Create new bookings (auto-generates reference)
    - Nested routes: /bookings/{id}/attendees/ and /bookings/{id}/tickets/
    
    Permissions:
    - List/Create: Authenticated users
    - Retrieve/Update/Delete: Booking owner or administrative staff
    """
    
    queryset = Booking.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingFilterSet
    search_fields = ['booking_reference', 'attendees__first_name', 'attendees__last_name', 'attendees__email']
    ordering_fields = ['booked_at', 'booking_reference']
    ordering = ['-booked_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return BookingListSerializer
        elif self.action == 'create':
            return BookingCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BookingUpdateSerializer
        return BookingDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action == 'create':
            return [permissions.IsAuthenticated()]
        elif self.action in ['retrieve', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsBookingOwnerOrAdministrative()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions.
        
        Regular users see only their own bookings.
        Admins see all bookings.
        """
        user = self.request.user
        queryset = super().get_queryset()
        
        # Optimize with select_related and prefetch_related
        queryset = queryset.select_related('event', 'made_by').prefetch_related('attendees')
        
        # If user is superuser or staff, return all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_events = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)
        
        # Return bookings made by user or for events they administer
        return queryset.filter(
            Q(made_by=user) |
            Q(attendees__user=user) |
            Q(event_id__in=admin_events)
        ).distinct()
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.event
            except:
                pass
        return context
    
    def perform_create(self, serializer):
        """
        Create booking with intent validation.
        
        Validates that a valid booking intent is provided (unless user is admin).
        The intent must be:
        - Pending status
        - Not expired
        - Belonging to the requesting user
        - For the same event as the booking
        - Have sufficient capacity
        
        After successful creation, marks the intent as completed.
        """
        user = self.request.user
        intent_id = self.request.query_params.get('intent')
        
        # Admin bypass: superusers and staff can create bookings without intent
        is_admin = user.is_superuser or user.is_staff
        
        if not is_admin:
            # Non-admin users must provide a valid intent
            if not intent_id:
                raise ValidationError({
                    'intent': 'A valid booking intent is required to create a booking. Please create a booking intent first.'
                })
            
            # Validate and retrieve the intent
            try:
                intent = BookingIntent.objects.get(booking_intent_id=intent_id)
            except BookingIntent.DoesNotExist:
                raise ValidationError({
                    'intent': f'Booking intent with ID {intent_id} does not exist.'
                })
            
            # Validate intent status
            if intent.status != BookingIntentStatusChoices.PENDING:
                raise ValidationError({
                    'intent': f'Booking intent must be in PENDING status. Current status: {intent.get_status_display()}.'
                })
            
            # Validate intent is not expired
            if intent.is_expired:
                raise ValidationError({
                    'intent': 'Booking intent has expired. Please create a new intent.'
                })
            
            # Validate intent belongs to user
            if intent.made_by != user:
                raise ValidationError({
                    'intent': 'This booking intent does not belong to you.'
                })
            
            # Get event from intent
            event = intent.event
            
            # Validate intent event matches booking event (if event provided in body)
            if 'event' in serializer.validated_data and serializer.validated_data['event'] != event:
                raise ValidationError({
                    'intent': f'Booking intent is for event "{event.title}" but booking is for a different event.'
                })
            
            # Set event from intent
            serializer.validated_data['event'] = event
            
            # Validate capacity using intent's can_create_booking method
            if not intent.can_create_booking():
                raise ValidationError({
                    'intent': 'Cannot create booking from this intent. Capacity may have been exhausted or intent is not valid.'
                })
            
            # Create the booking
            booking = serializer.save()
            
            # Mark intent as completed
            intent.mark_completed(save=True)
        else:
            # Admin users: if event not provided in body, check if intent is provided
            if 'event' not in serializer.validated_data or not serializer.validated_data['event']:
                if intent_id:
                    # Try to use intent if provided
                    try:
                        intent = BookingIntent.objects.get(booking_intent_id=intent_id)
                        serializer.validated_data['event'] = intent.event
                        booking = serializer.save()
                        intent.mark_completed(save=True)
                    except BookingIntent.DoesNotExist:
                        raise ValidationError({
                            'event': 'Event is required when no valid intent is provided.'
                        })
                else:
                    raise ValidationError({
                        'event': 'Event is required for admin bookings without an intent.'
                    })
            else:
                # Admin with event provided
                booking = serializer.save()
                
                # If intent provided, mark it as completed
                if intent_id:
                    try:
                        intent = BookingIntent.objects.get(booking_intent_id=intent_id)
                        intent.mark_completed(save=True)
                    except BookingIntent.DoesNotExist:
                        pass  # Intent not found, ignore for admin users
    
    @extend_schema(
        summary="List attendees for booking",
        description="Retrieve all attendees associated with this booking.",
        tags=["Bookings"],
        responses={200: OpenApiResponse(description="List of attendees")},
        operation_id="bookings_booking_attendees_list",
    )
    @action(detail=True, methods=['get'], url_path='attendees')
    def attendees(self, request, pk=None):
        """Return all attendees for this booking."""
        booking = self.get_object()
        from apps.attendee.api.serializers import AttendeeListSerializer
        
        attendees = booking.attendees.all()
        serializer = AttendeeListSerializer(attendees, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="List tickets for booking",
        description="Retrieve all tickets across all attendees for this booking.",
        tags=["Bookings"],
        responses={200: TicketListSerializer(many=True)},
        operation_id="bookings_booking_tickets_list",
    )
    @action(detail=True, methods=['get'], url_path='tickets')
    def tickets(self, request, pk=None):
        """Return all tickets for all attendees in this booking."""
        booking = self.get_object()
        
        # Get all tickets through attendees
        tickets = Ticket.objects.filter(
            attendee__booking=booking
        ).select_related('attendee', 'ticket_type', 'package', 'payment')
        
        serializer = TicketListSerializer(tickets, many=True, context={'request': request, 'event': booking.event})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Checkout booking with payment",
        description=(
            "Complete booking checkout flow with payment creation. "
            "This endpoint:\n"
            "1. Validates booking intent and extends expiry\n"
            "2. Creates booking and orders atomically\n"
            "3. Calculates all prices server-side (frontend prices are ignored)\n"
            "4. Creates payment and handles method-specific flows:\n"
            "   - STRIPE: Returns client_secret for frontend payment\n"
            "   - BANK_TRANSFER: Returns bank reference for manual payment\n"
            "   - CASH/FREE: Creates tickets immediately\n"
            "5. Handles failures with automatic cleanup and stock restoration"
        ),
        tags=["Bookings"],
        request={'application/json': CheckoutSerializer},
        responses={
            201: OpenApiResponse(
                description="Checkout successful",
                response={
                    'type': 'object',
                    'properties': {
                        'booking_id': {'type': 'string', 'format': 'uuid'},
                        'booking_reference': {'type': 'string'},
                        'payment_id': {'type': 'integer'},
                        'payment_reference': {'type': 'string'},
                        'total_amount': {'type': 'string'},
                        'currency': {'type': 'string'},
                        'status': {'type': 'string'},
                        'orders': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'order_id': {'type': 'string', 'format': 'uuid'},
                                    'order_reference': {'type': 'string'},
                                    'attendee_id': {'type': 'string', 'format': 'uuid'},
                                    'total_amount': {'type': 'string'},
                                    '_links': {'type': 'object'},
                                }
                            }
                        },
                        'stripe_client_secret': {'type': 'string', 'nullable': True},
                        'bank_transfer_reference': {'type': 'string', 'nullable': True},
                        'bank_transfer_instructions': {'type': 'string', 'nullable': True},
                        'tickets': {'type': 'array', 'nullable': True},
                        '_links': {'type': 'object'},
                    }
                }
            ),
            400: OpenApiResponse(description="Validation error or checkout failed"),
        },
        operation_id="bookings_checkout",
    )
    @action(detail=False, methods=['post'], url_path='checkout')
    def checkout(self, request):
        """
        Complete booking checkout with payment.
        
        This is the unified checkout endpoint that handles the complete registration flow.
        All operations are atomic - if any step fails, everything rolls back.
        """
        from .serializers import CheckoutSerializer
        from apps.bookings.services import TicketCreatorService
        import logging
        logger = logging.getLogger(__name__)
        
        # Validate input data
        serializer = CheckoutSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        # Extract validated data
        intent = serializer.validated_data['_intent']
        payment_method = serializer.validated_data['_payment_method']
        attendee_selections = serializer.validated_data['attendees']
        user = request.user
        
        # Import models
        from django.db import transaction
        from apps.products.models import Order, OrderStatusChoices
        from apps.payments.models import Payment, PaymentStatusChoices, PaymentMethodTypeChoices
        from djmoney.money import Money
        from core.utils.display import generate_human_readable_id
        from decimal import Decimal
        
        try:
            with transaction.atomic():
                # Lock the intent to prevent race conditions
                intent = BookingIntent.objects.select_for_update().get(
                    booking_intent_id=intent.booking_intent_id
                )
                
                # Extend intent expiry during checkout
                from django.utils import timezone
                intent.expires_at = timezone.now() + timezone.timedelta(minutes=30)
                intent.save(update_fields=['expires_at'])
                
                # Revalidate intent is still active
                if not intent.is_active or not intent.can_create_booking():
                    raise ValidationError({
                        'booking_intent_id': 'Booking intent is no longer valid for checkout.'
                    })
                
                # === STEP 1: Create Booking ===
                booking_reference = generate_human_readable_id(
                    50, 'BKG', intent.event.display_code[:10]
                )
                
                booking = Booking.objects.create(
                    event=intent.event,
                    booking_reference=booking_reference,
                    made_by=user
                )
                
                logger.info(f"Created booking {booking.booking_reference} for user {user.id}")
                
                # Update all attendees to point to the new booking
                for selection in attendee_selections:
                    attendee = selection['_attendee']
                    attendee.booking = booking
                    attendee.save(update_fields=['booking'])
                
                # === STEP 2: Calculate Prices and Create Orders ===
                total_amount = Money(0, 'GBP')
                orders_data = []
                attendee_selections_metadata = []
                
                for selection in attendee_selections:
                    attendee = selection['_attendee']
                    package = selection['_package']
                    product_selections = selection.get('product_selections', [])
                    
                    # Calculate package price for attendee
                    attendee_context = attendee.pricing_context()
                    package_price = package.total_amount_for_context(attendee_context)
                    
                    # Store metadata for payment
                    selection_metadata = {
                        'attendee_id': str(attendee.attendee_id),
                        'attendee_name': attendee.full_name,
                        'package_id': package.id,
                        'package_name': package.name,
                        'frozen_price': str(package_price.amount),
                        'currency': package_price.currency.code,
                    }
                    
                    # Create order for this attendee if there are products
                    if product_selections:
                        order = Order.objects.create(
                            customer=user,
                            attendee=attendee,
                            booking_package=package,
                            status=OrderStatusChoices.DRAFT,
                            total_amount=Money(0, 'GBP'),
                            created_by=user
                        )
                        
                        order_total = Money(0, 'GBP')
                        product_items = []
                        
                        for prod_selection in product_selections:
                            package_product = prod_selection['_package_product']
                            variant = prod_selection['_variant']
                            quantity = prod_selection['quantity']
                            
                            # Calculate price with variant and package discount
                            item_price = package_product.total_amount_with_variant(
                                variant=variant,
                                context=attendee_context
                            )
                            
                            # Add item to order (this handles stock decrement)
                            try:
                                order_item = order.add_order_item(variant, quantity)
                                order_total += order_item.total_price
                                
                                product_items.append({
                                    'package_product_id': package_product.id,
                                    'variant_id': str(variant.id),
                                    'quantity': quantity,
                                    'unit_price': str(order_item.unit_price.amount),
                                    'total_price': str(order_item.total_price.amount),
                                })
                            except Exception as e:
                                logger.error(
                                    f"Failed to add order item for attendee {attendee.attendee_id}: {str(e)}"
                                )
                                raise ValidationError({
                                    'product_selections': f'Failed to add product: {str(e)}'
                                })
                        
                        # Submit order
                        order.transition_to(OrderStatusChoices.PENDING)
                        
                        orders_data.append({
                            'order_id': str(order.order_id),
                            'order_reference': order.order_reference_id,
                            'attendee_id': str(attendee.attendee_id),
                            'total_amount': str(order.total_amount.amount),
                            'currency': order.total_amount.currency.code,
                            'product_items': product_items,
                            '_order_object': order,
                        })
                        
                        # Add order total to running total
                        total_amount += order.total_amount
                        selection_metadata['order_id'] = str(order.order_id)
                        selection_metadata['order_total'] = str(order.total_amount.amount)
                    
                    # Add package price to total
                    total_amount += package_price
                    attendee_selections_metadata.append(selection_metadata)
                
                # === STEP 3: Create Payment ===
                # Skip payment creation if total is zero (free event)
                payment = None
                if total_amount.amount > 0:
                    payment_metadata = {
                        'booking_id': str(booking.id),
                        'booking_reference': booking.booking_reference,
                        'attendee_selections': attendee_selections_metadata,
                        'payment_type': 'booking_with_packages',
                        'total_attendees': len(attendee_selections),
                    }
                    
                    payment = Payment.objects.create(
                        user=user,
                        event=intent.event,
                        method=payment_method,
                        base_amount=total_amount,
                        percentage_modifier=Decimal('0.00'),
                        description=f"Booking {booking.booking_reference} - {intent.event.title}",
                        status=PaymentStatusChoices.PENDING,
                        metadata=payment_metadata,
                        target=booking
                    )
                    
                    # Link payment to all orders
                    for order_data in orders_data:
                        order_obj = order_data['_order_object']
                        order_obj.payment = payment
                        order_obj.save(update_fields=['payment'])
                    
                    logger.info(
                        f"Created payment {payment.payment_reference} for booking {booking.booking_reference}, "
                        f"amount: {payment.base_amount}"
                    )
                
                # === STEP 4: Mark Intent as Completed ===
                intent.mark_completed(save=True)
                
                # === STEP 5: Handle Payment Method Specific Logic ===
                response_data = {
                    'booking_id': str(booking.id),
                    'booking_reference': booking.booking_reference,
                    'payment_id': payment.id if payment else None,
                    'payment_reference': payment.payment_reference if payment else None,
                    'total_amount': str(total_amount.amount),
                    'currency': total_amount.currency.code,
                    'orders': [
                        {
                            'order_id': od['order_id'],
                            'order_reference': od['order_reference'],
                            'attendee_id': od['attendee_id'],
                            'total_amount': od['total_amount'],
                            '_links': {
                                'self': request.build_absolute_uri(f'/api/products/orders/{od["order_id"]}/'),
                            }
                        }
                        for od in orders_data
                    ],
                    '_links': {
                        'self': request.build_absolute_uri(f'/api/bookings/list/{booking.id}/'),
                        'attendees': request.build_absolute_uri(f'/api/bookings/list/{booking.id}/attendees/'),
                        'tickets': request.build_absolute_uri(f'/api/bookings/list/{booking.id}/tickets/'),
                    }
                }
                
                if not payment:
                    # Free event - create tickets immediately
                    response_data['status'] = 'confirmed'
                    response_data['message'] = 'Booking confirmed. This is a free event.'
                    # Note: Tickets will be created by signal handler if payment status changes
                    
                elif payment_method.method_type == PaymentMethodTypeChoices.STRIPE:
                    # STRIPE: Create PaymentIntent and return client_secret
                    from apps.payments.services.stripe import PaymentIntentService
                    
                    try:
                        stripe_metadata = payment.prepare_stripe_metadata()
                        payment_intent = PaymentIntentService.create(
                            amount=payment.base_amount,
                            currency=payment.base_amount.currency.code,
                            payment_reference=payment.payment_reference,
                            metadata=stripe_metadata,
                            customer_email=user.email,
                            description=payment.description
                        )
                        
                        # Store Stripe references
                        payment.stripe_payment_intent = payment_intent.id
                        payment.save(update_fields=['stripe_payment_intent'])
                        
                        response_data['stripe_client_secret'] = payment_intent.client_secret
                        response_data['status'] = 'pending_payment'
                        response_data['message'] = (
                            'Booking created. Complete payment with Stripe to confirm.'
                        )
                        
                        logger.info(
                            f"Created Stripe PaymentIntent {payment_intent.id} for "
                            f"payment {payment.payment_reference}"
                        )
                    
                    except Exception as e:
                        logger.error(
                            f"Failed to create Stripe PaymentIntent for payment "
                            f"{payment.payment_reference}: {str(e)}",
                            exc_info=True
                        )
                        raise ValidationError({
                            'payment': f'Failed to initialize Stripe payment: {str(e)}'
                        })
                
                elif payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
                    # BANK TRANSFER: Return bank reference and instructions
                    response_data['bank_transfer_reference'] = payment.bank_transfer_reference
                    response_data['bank_transfer_instructions'] = (
                        f"Please transfer {payment.base_amount} to our bank account with "
                        f"reference: {payment.bank_transfer_reference}. "
                        f"Your tickets will be issued after payment verification."
                    )
                    response_data['status'] = 'pending_verification'
                    response_data['message'] = (
                        'Booking created. Complete bank transfer to confirm. '
                        'Tickets will be issued after admin verification.'
                    )
                    
                elif payment_method.method_type == PaymentMethodTypeChoices.CASH:
                    # CASH: Mark as completed immediately and create tickets
                    payment.transition_to(PaymentStatusChoices.COMPLETED)
                    payment.save()
                    
                    # Create tickets
                    tickets = TicketCreatorService.create_tickets_for_payment(payment)
                    
                    response_data['status'] = 'confirmed'
                    response_data['message'] = 'Booking confirmed. Pay cash on arrival.'
                    response_data['tickets'] = [
                        {
                            'ticket_id': str(t.ticket_id),
                            'ticket_code': t.ticket_code,
                            'attendee_name': t.attendee.full_name,
                            '_links': {
                                'self': request.build_absolute_uri(f'/api/bookings/tickets/{t.ticket_id}/'),
                            }
                        }
                        for t in tickets
                    ]
                
                return Response(response_data, status=status.HTTP_201_CREATED)
        
        except ValidationError:
            # Re-raise validation errors
            raise
        
        except Exception as e:
            # Log unexpected errors
            logger.error(
                f"Checkout failed for user {user.id}, intent {intent.booking_intent_id}: {str(e)}",
                exc_info=True,
                extra={
                    'user_id': user.id,
                    'intent_id': str(intent.booking_intent_id),
                    'event_id': intent.event_id,
                    'attendee_count': len(attendee_selections),
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                }
            )
            
            # Return generic error (transaction will auto-rollback)
            raise ValidationError({
                'checkout': (
                    'Checkout failed due to an unexpected error. '
                    'All changes have been rolled back. Please try again or contact support.'
                )
            })


# ============================================================================
# BOOKING INTENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List booking intents",
        description="Retrieve a paginated list of booking intents. Users see only their own intents, admins see all.",
        tags=["Booking Intents"],
        parameters=[
            OpenApiParameter(
                name='is_active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter by active status (pending and not expired)',
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve booking intent details",
        description="Get detailed information about a specific booking intent.",
        tags=["Booking Intents"],
    ),
    create=extend_schema(
        summary="Create booking intent",
        description="Create a new booking intent to reserve capacity for event tickets. Intent expires after 20 minutes.",
        tags=["Booking Intents"],
    ),
    update=extend_schema(
        summary="Update booking intent",
        description="Update an existing booking intent. Only ticket count can be modified and only for pending intents.",
        tags=["Booking Intents"],
    ),
    partial_update=extend_schema(
        summary="Partially update booking intent",
        description="Partially update a booking intent. Only ticket count can be modified and only for pending intents.",
        tags=["Booking Intents"],
    ),
    destroy=extend_schema(
        summary="Delete booking intent",
        description="Delete a booking intent. Only allowed for pending intents.",
        tags=["Booking Intents"],
    ),
)
class BookingIntentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing booking intents.
    
    Booking intents reserve capacity before payment to prevent race conditions.
    They expire after 20 minutes and are cleaned up by background tasks.
    
    Provides:
    - List/Retrieve: Users see their own intents, admins see all
    - Create: Reserve capacity for tickets (max 20 tickets per intent)
    - Update: Modify ticket count (only for pending intents)
    - Cancel: Release reserved capacity
    - Delete: Remove intent (only pending intents)
    
    Permissions:
    - List/Create: Authenticated users
    - Retrieve/Update/Delete/Cancel: Intent creator or administrative staff
    """
    
    queryset = BookingIntent.objects.select_related('event', 'made_by').all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingIntentFilterSet
    search_fields = ['booking_intent_id', 'event__title', 'event__display_code']
    ordering_fields = ['created_at', 'expires_at', 'status']
    ordering = ['-created_at']
    lookup_field = 'booking_intent_id'
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action in ['list', 'create']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            # For retrieve, update, partial_update, destroy, cancel
            permission_classes = [permissions.IsAuthenticated, IsBookingOwnerOrAdministrative]
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()
        
        # Non-admin users only see their own intents
        if not self.request.user.is_staff:
            queryset = queryset.filter(made_by=self.request.user)
        
        # Exclude soft-deleted intents from list view
        if self.action == 'list':
            queryset = queryset.filter(deleted_at__isnull=True)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return BookingIntentListSerializer
        elif self.action == 'retrieve':
            return BookingIntentDetailSerializer
        elif self.action == 'create':
            return BookingIntentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BookingIntentUpdateSerializer
        return BookingIntentDetailSerializer
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.event
            except:
                pass
        return context
    
    def perform_create(self, serializer):
        """Create booking intent with authenticated user."""
        serializer.save(made_by=self.request.user)
    
    def perform_destroy(self, instance):
        """Only allow deletion of pending intents."""
        if instance.status != BookingIntentStatusChoices.PENDING:
            raise ValidationError("Cannot delete a non-pending booking intent.")
        instance.delete()
    
    @extend_schema(
        summary="Cancel booking intent",
        description="Cancel a pending booking intent, releasing the reserved capacity. Cannot be undone.",
        tags=["Booking Intents"],
        request=None,
        responses={
            200: OpenApiResponse(
                description="Intent successfully cancelled",
                response=BookingIntentDetailSerializer
            ),
            400: OpenApiResponse(description="Intent cannot be cancelled (not pending)"),
            404: OpenApiResponse(description="Intent not found"),
        },
        operation_id="bookings_intent_cancel",
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, booking_intent_id=None):
        """Cancel a booking intent."""
        intent = self.get_object()
        
        if intent.status != BookingIntentStatusChoices.PENDING:
            return Response(
                {'detail': 'Only pending intents can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if intent.is_expired:
            return Response(
                {'detail': 'Cannot cancel an expired intent.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Cancel the intent
        intent.cancel(save=True)
        
        serializer = self.get_serializer(intent)
        return Response(serializer.data)


# ============================================================================
# TICKET TYPE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List ticket types",
        description="Retrieve a list of ticket types. Filter by event, scope, or validity.",
        tags=["Ticket Types"],
    ),
    retrieve=extend_schema(
        summary="Retrieve ticket type details",
        description="Get detailed information about a specific ticket type.",
        tags=["Ticket Types"],
    ),
    create=extend_schema(
        summary="Create ticket type",
        description="Create a new ticket type for an event. Requires administrative access.",
        tags=["Ticket Types"],
    ),
    update=extend_schema(
        summary="Update ticket type",
        description="Update an existing ticket type. Requires administrative access.",
        tags=["Ticket Types"],
    ),
    partial_update=extend_schema(
        summary="Partially update ticket type",
        description="Partially update a ticket type. Requires administrative access.",
        tags=["Ticket Types"],
    ),
    destroy=extend_schema(
        summary="Delete ticket type",
        description="Delete a ticket type. Requires administrative access.",
        tags=["Ticket Types"],
    ),
)
class TicketTypeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing ticket types.
    
    Provides:
    - List/Retrieve: Any authenticated user can view ticket types
    - Create/Update/Delete: Administrative staff only
    
    Permissions:
    - List/Retrieve: Authenticated + ReadOnly
    - Create/Update/Delete: Administrative staff
    """
    
    queryset = TicketType.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TicketTypeFilterSet
    search_fields = ['title', 'code']
    ordering_fields = ['created_at', 'title', 'valid_from']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return TicketTypeListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return TicketTypeCreateUpdateSerializer
        return TicketTypeDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated(), IsReadOnly()]
        return [permissions.IsAuthenticated(), IsAdministrativeStaff()]
    
    def get_queryset(self):
        """Optimize queryset with select_related."""
        return super().get_queryset().select_related('event', 'created_by')
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.event
            except:
                pass
        return context
    
    def perform_create(self, serializer):
        """Set created_by when creating ticket type."""
        serializer.save(created_by=self.request.user)


# ============================================================================
# TICKET VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List tickets",
        description="Retrieve a list of tickets. Filter by status, attendee, booking, or type.",
        tags=["Tickets"],
    ),
    retrieve=extend_schema(
        summary="Retrieve ticket details",
        description="Get detailed information about a specific ticket.",
        tags=["Tickets"],
    ),
)
class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for tickets.
    
    Tickets are created automatically server-side when payments are completed.
    Users can view their own tickets, admins can view all tickets.
    
    Permissions:
    - List/Retrieve: Ticket owner or administrative staff
    """
    
    queryset = Ticket.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TicketFilterSet
    search_fields = ['ticket_code', 'attendee__first_name', 'attendee__last_name']
    ordering_fields = ['issued_at', 'status']
    ordering = ['-issued_at']
    lookup_field = 'ticket_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return TicketListSerializer
        return TicketDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action."""
        return [permissions.IsAuthenticated(), IsTicketOwnerOrAdministrative()]
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions.
        
        Regular users see only their own tickets.
        Admins see all tickets.
        """
        user = self.request.user
        queryset = super().get_queryset()
        
        # Optimize with select_related
        queryset = queryset.select_related('attendee', 'ticket_type', 'package', 'payment')
        
        # If user is superuser or staff, return all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_events = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)
        
        # Return tickets for user's attendees or events they administer
        return queryset.filter(
            Q(attendee__user=user) |
            Q(attendee__booking__made_by=user) |
            Q(ticket_type__event_id__in=admin_events)
        ).distinct()
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.ticket_type.event if obj.ticket_type else None
            except:
                pass
        return context


# ============================================================================
# BOOKING PACKAGE VIEWSETS
# ============================================================================

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
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdministrativeStaff()]
    
    def get_queryset(self):
        """Optimize queryset with select_related and prefetch rules."""
        return super().get_queryset().select_related(
            'event', 'ticket_type', 'created_by'
        ).prefetch_related('rules')
    
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


# ============================================================================
# ALTERNATIVE SIGNIN VIEWSETS (ADMIN ONLY)
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List event alternative signin identifiers",
        description="Retrieve event alternative signin identifiers. Admin only.",
        tags=["Alternative Signins"],
    ),
    retrieve=extend_schema(
        summary="Retrieve event alternative signin details",
        description="Get detailed information about an event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    create=extend_schema(
        summary="Create event alternative signin",
        description="Create a new event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    update=extend_schema(
        summary="Update event alternative signin",
        description="Update an existing event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    partial_update=extend_schema(
        summary="Partially update event alternative signin",
        description="Partially update an event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    destroy=extend_schema(
        summary="Delete event alternative signin",
        description="Delete an event alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
)
class EventAlternativeSigninViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event alternative signin identifiers.
    
    Admin-only access for managing alternative check-in methods.
    
    Permissions:
    - All actions: Administrative staff only
    """
    
    queryset = EventAlternativeSigninIdentifier.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventAlternativeSigninFilterSet
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'title']
    ordering = ['-created_at']
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventAlternativeSigninListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventAlternativeSigninCreateUpdateSerializer
        return EventAlternativeSigninDetailSerializer
    
    def get_queryset(self):
        """Optimize queryset with select_related."""
        return super().get_queryset().select_related(
            'event', 'verified_by', 'processed_by'
        )


@extend_schema_view(
    list=extend_schema(
        summary="List attendee alternative signin identifiers",
        description="Retrieve attendee alternative signin identifiers. Admin only.",
        tags=["Alternative Signins"],
    ),
    retrieve=extend_schema(
        summary="Retrieve attendee alternative signin details",
        description="Get detailed information about an attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    create=extend_schema(
        summary="Create attendee alternative signin",
        description="Create a new attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    update=extend_schema(
        summary="Update attendee alternative signin",
        description="Update an existing attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    partial_update=extend_schema(
        summary="Partially update attendee alternative signin",
        description="Partially update an attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
    destroy=extend_schema(
        summary="Delete attendee alternative signin",
        description="Delete an attendee alternative signin identifier. Admin only.",
        tags=["Alternative Signins"],
    ),
)
class AttendeeAlternativeSigninViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing attendee alternative signin identifiers.
    
    Admin-only access for linking alternative IDs to attendee tickets.
    
    Permissions:
    - All actions: Administrative staff only
    """
    
    queryset = AttendeeAlternativeSigninIdentifier.objects.all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AttendeeAlternativeSigninFilterSet
    search_fields = ['identifier', 'attendee__first_name', 'attendee__last_name']
    ordering_fields = ['defined_at', 'identifier']
    ordering = ['-defined_at']
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    lookup_field = 'sign_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AttendeeAlternativeSigninListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return AttendeeAlternativeSigninCreateUpdateSerializer
        return AttendeeAlternativeSigninDetailSerializer
    
    def get_queryset(self):
        """Optimize queryset with select_related."""
        return super().get_queryset().select_related(
            'attendee', 'ticket', 'event_alternative_signin', 'defined_by'
        )
