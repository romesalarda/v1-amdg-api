"""
Production-grade viewsets for the payments app.

Provides comprehensive viewsets for payment management with proper validation,
business logic separation, schema configuration, and permission classes.

ViewSets:
    - PaymentViewSet: Full CRUD for payments with status transitions
    - PaymentMethodViewSet: Manage payment methods (admin only)
    - DiscountViewSet: Manage discounts
    - DiscountRuleViewSet: Manage discount rules
    - RefundRequestViewSet: Handle refund workflows with verification
    - RefundAssociationViewSet: Manage refund associations
    - RefundPolicyViewSet: Manage refund policies
    - DonationViewSet: Handle donation workflows
    - PaymentHistoryActionViewSet: Read-only payment history

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import viewsets, status, permissions, filters, serializers, exceptions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from django.utils import timezone
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from djmoney.contrib.django_rest_framework import MoneyField
from typing import Any
import logging

from apps.payments.models import (
    Payment, PaymentMethod, PaymentStatusChoices, PaymentMethodTypeChoices,
    Discount, DiscountRule,
    RefundRequest, RefundAssociation, RefundPolicy,
    Donation, PaymentHistoryAction,
    CreditExpense, BankTransferEvidence
)
from apps.common.models import VerificationStatus
from .serializers import (
    PaymentListSerializer, PaymentDetailSerializer, PaymentCreateSerializer, PaymentUpdateSerializer,
    PaymentMethodSerializer, PaymentMethodDetailSerializer, PaymentMethodCreateUpdateSerializer,
    DiscountListSerializer, DiscountDetailSerializer, DiscountCreateUpdateSerializer,
    DiscountRuleSerializer, DiscountRuleCreateUpdateSerializer,
    RefundRequestListSerializer, RefundRequestDetailSerializer, RefundRequestCreateSerializer, RefundRequestUpdateSerializer,
    RefundAssociationSerializer, RefundAssociationCreateSerializer,
    RefundPolicySerializer, RefundPolicyCreateUpdateSerializer,
    DonationListSerializer, DonationDetailSerializer, DonationCreateSerializer,
    PaymentHistoryActionSerializer,
    CreditExpenseListSerializer, CreditExpenseDetailSerializer, CreditExpenseCreateSerializer, CreditExpenseUpdateSerializer,
    BankTransferEvidenceListSerializer, BankTransferEvidenceDetailSerializer, BankTransferEvidenceCreateSerializer, BankTransferEvidenceUpdateSerializer
)
from .filtersets import (
    PaymentFilterSet, PaymentMethodFilterSet, DiscountFilterSet, DiscountRuleFilterSet,
    RefundRequestFilterSet, RefundPolicyFilterSet, DonationFilterSet, PaymentHistoryActionFilterSet,
    CreditExpenseFilterSet, BankTransferEvidenceFilterSet
)
from .permissions import (
    IsAdministrativeStaff, IsAdministrativeStaffOnly, IsPaymentOwnerOrAdministrative,
    IsRefundRequestOwnerOrAdministrative, IsReadOnly,
    IsCreditAccessible, IsBankTransferEvidenceAccessible
)
from apps.payments.services.attendee_refunds import AttendeeRefundService
from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices


logger = logging.getLogger(__name__)


def _user_has_finance_role(user, event) -> bool:
    if not user or not getattr(user, 'is_authenticated', False) or not event:
        return False

    return EventRoleAssignment.objects.filter(
        user=user,
        event=event,
        role__name__icontains='finance'
    ).exists() or EventRoleAssignment.objects.filter(
        user=user,
        event=event,
        role__code__iexact='FIN'
    ).exists()


def _user_can_manage_credits(user, event) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False

    if user.is_superuser or user.is_staff:
        return True

    if EventRoleAssignment.objects.filter(
        user=user,
        event=event,
        role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
    ).exists():
        return True

    return _user_has_finance_role(user, event)


def _user_can_manage_bank_evidence(user, event) -> bool:
    return _user_can_manage_credits(user, event)


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration for payment endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================================
# PAYMENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List payments",
        description="Retrieve a paginated list of payments. Admins see all payments, users see only their own.",
        tags=["Payments"],
    ),
    retrieve=extend_schema(
        summary="Retrieve payment details",
        description="Get detailed information about a specific payment including target, refunds, and history.",
        tags=["Payments"],
    ),
    create=extend_schema(
        summary="Create payment",
        description="Create a new payment in DRAFTING status. Only admins can create payments for other users.",
        tags=["Payments"],
    ),
    update=extend_schema(
        summary="Update payment",
        description="Update payment details. Status transitions are validated.",
        tags=["Payments"],
    ),
    partial_update=extend_schema(
        summary="Partially update payment",
        description="Partially update payment details. Status transitions are validated.",
        tags=["Payments"],
    ),
    destroy=extend_schema(
        summary="Delete payment",
        description=(
            "Delete a payment. Can only delete payments in DRAFTING or PENDING status. "
            "Only administrative staff can delete payments."
        ),
        tags=["Payments"],
    )
)
class PaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payment model operations.
    
    Provides:
    - List: Paginated list with filtering (users see own, admins see all)
    - Retrieve: Detailed view with embedded target and history
    - Create: New payment creation (DRAFTING status)
    - Update: Status transitions and metadata updates
    - Custom actions: mark_completed, mark_failed, cancel
    
    Permissions:
    - List/Retrieve: Owner or administrative staff
    - Create/Update: Administrative staff only
    """
    
    queryset = Payment.objects.select_related(
        'user', 'event', 'method', 'target_type'
    ).prefetch_related(
        'refund_requests', 'donations', 'history_actions'
    )
    permission_classes = [permissions.IsAuthenticated, IsPaymentOwnerOrAdministrative]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PaymentFilterSet
    search_fields = ['payment_reference', 'bank_transfer_reference', 'user__username', 'user__email']
    ordering_fields = ['created_at', 'updated_at', 'base_amount', 'status']
    ordering = ['-created_at']
    lookup_field = 'payment_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return PaymentListSerializer
        elif self.action in ['create']:
            return PaymentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PaymentUpdateSerializer
        return PaymentDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)
        
        # Users see their own payments or payments for events they admin
        return queryset.filter(
            Q(user=user) | Q(event_id__in=admin_event_ids)
        ).distinct()
    
    def perform_create(self, serializer):
        """Create payment and ensure user has permission."""
        user = self.request.user
        payment_user = serializer.validated_data.get('user')
        
        # Non-admins can only create payments for themselves
        # if not (user.is_superuser or user.is_staff) and payment_user != user:
        #     from rest_framework.exceptions import PermissionDenied
        #     raise PermissionDenied("You can only create payments for yourself.")

        self.check_permissions(self.request)
        
        serializer.save()
    
    @extend_schema(
        summary="Mark payment as completed",
        description="Transition payment to COMPLETED status. Only admins can do this.",
        request=None,
        responses={200: PaymentDetailSerializer},
        tags=["Payments"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def mark_completed(self, request, payment_id=None):
        """Mark payment as completed."""
        payment = self.get_object()
        
        if payment.status != PaymentStatusChoices.PENDING:
            return Response(
                {'error': 'Can only mark PENDING payments as completed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment.status = PaymentStatusChoices.COMPLETED
        payment.save()
        
        # Log action
        PaymentHistoryAction.objects.create(
            payment=payment,
            action='MARKED_COMPLETED',
            description='Payment marked as completed by administrator',
            performed_by=request.user
        )
        
        serializer = self.get_serializer(payment)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Mark payment as failed",
        description="Transition payment to FAILED status. Only admins can do this.",
        request=None,
        responses={200: PaymentDetailSerializer},
        tags=["Payments"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def mark_failed(self, request, payment_id=None):
        """Mark payment as failed."""
        payment = self.get_object()
        
        if payment.status != PaymentStatusChoices.PENDING:
            return Response(
                {'error': 'Can only mark PENDING payments as failed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment.status = PaymentStatusChoices.FAILED
        payment.save()
        
        # Log action
        PaymentHistoryAction.objects.create(
            payment=payment,
            action='MARKED_FAILED',
            description='Payment marked as failed by administrator',
            performed_by=request.user
        )
        
        serializer = self.get_serializer(payment)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Cancel payment",
        description="Cancel a pending payment. Only admins can do this.",
        request=None,
        responses={200: PaymentDetailSerializer},
        tags=["Payments"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def cancel(self, request, payment_id=None):
        """Cancel a payment."""
        payment = self.get_object()
        
        if payment.status != PaymentStatusChoices.PENDING:
            return Response(
                {'error': 'Can only cancel PENDING payments'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment.status = PaymentStatusChoices.CANCELLED
        payment.save()
        
        # Log action
        PaymentHistoryAction.objects.create(
            payment=payment,
            action='CANCELLED',
            description='Payment cancelled by administrator',
            performed_by=request.user
        )
        
        serializer = self.get_serializer(payment)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Verify bank transfer payment",
        description=(
            "Verify and complete a bank transfer payment. "
            "This endpoint:\n"
            "1. Validates payment is PENDING and method is BANK_TRANSFER\n"
            "2. Transitions payment to COMPLETED status\n"
            "3. Creates tickets for the booking\n"
            "4. Logs verification action\n"
            "\n"
            "Only accessible by administrative staff."
        ),
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'verified': {
                        'type': 'boolean',
                        'description': 'Set to true to verify payment'
                    },
                    'notes': {
                        'type': 'string',
                        'description': 'Admin notes about verification (e.g., bank reference, date received)'
                    }
                },
                'required': ['verified']
            }
        },
        responses={
            200: PaymentDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
        tags=["Payments"],
    )
    @action(
        detail=True,
        methods=['post'],
        url_path='verify-bank-transfer',
        permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    )
    def verify_bank_transfer(self, request, payment_id=None):
        """
        Verify bank transfer payment and process target.
        
        This is the manual verification endpoint for BANK_TRANSFER payments.
        After admin confirms they received the bank transfer, this endpoint:
        1. Completes the payment
        2. Processes the target (creates tickets for Booking, transitions Order, verifies Donation)
        3. Logs the verification
        
        Supports targets: Booking, Order, Donation
        """
        from apps.bookings.services import TicketCreatorService
        from apps.payments.models import PaymentMethodTypeChoices
        from apps.bookings.models import Booking
        from apps.organisations.models import EventSponsor
        from apps.products.models import Order, OrderStatusChoices
        from apps.payments.models import Donation
        import logging
        logger = logging.getLogger(__name__)
        
        payment = self.get_object()
        
        # Validate input
        verified = request.data.get('verified', False)
        notes = request.data.get('notes', '')
        
        if not verified:
            return Response(
                {'error': 'verified must be set to true to verify payment'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate payment status
        if payment.status != PaymentStatusChoices.PENDING:
            return Response(
                {
                    'error': f'Can only verify PENDING payments. Current status: {payment.status}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate payment method is bank transfer
        if not payment.method or payment.method.method_type != PaymentMethodTypeChoices.BANK_TRANSFER:
            return Response(
                {
                    'error': 'This endpoint is only for BANK_TRANSFER payments. '
                             f'Current method: {payment.method.method_type if payment.method else "None"}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        target = payment.target
        target_type = type(target).__name__

        if target_type is None:
            target_type = "External Payment"
        
        try:
            # Transition payment to completed
            payment.transition_to(PaymentStatusChoices.COMPLETED)
            payment.save()
            
            # Log verification action
            PaymentHistoryAction.objects.create(
                payment=payment,
                action='BANK_TRANSFER_VERIFIED',
                description=f'Bank transfer verified for {target_type} by administrator',
                metadata={
                    'verified_by_id': request.user.id,
                    'verified_by_username': request.user.username,
                    'bank_reference': payment.bank_transfer_reference,
                    'target_type': target_type,
                    'notes': notes,
                },
                notes=notes,
                performed_by=request.user
            )
            
            response_data = {}
            
            # Handle target-specific actions
            if isinstance(target, Booking):
                # Create tickets for booking
                tickets = TicketCreatorService.create_tickets_for_payment(payment)
                
                logger.info(
                    f"Bank transfer verified for booking payment {payment.payment_reference}. "
                    f"Created {len(tickets)} tickets."
                )
                
                response_data['tickets_created'] = len(tickets)
                response_data['message'] = (
                    f'Bank transfer verified. Payment completed and {len(tickets)} ticket(s) created for '
                    f'booking {target.booking_reference}.'
                )
            
            elif isinstance(target, Order):
                # Order will be transitioned by signal handler based on event settings
                logger.info(
                    f"Bank transfer verified for order payment {payment.payment_reference}. "
                    f"Order {target.order_reference_id} will be processed per event settings."
                )
                
                response_data['order_reference'] = target.order_reference_id
                response_data['order_status'] = target.status
                response_data['message'] = (
                    f'Bank transfer verified. Payment completed for order {target.order_reference_id}. '
                    f'Order will be processed according to event settings.'
                )

                if target.can_transition_to(OrderStatusChoices.PROCESSING):
                    target.transition_to(OrderStatusChoices.PROCESSING)
                    target.save()
                    response_data['order_status'] = target.status
                
                
            
            elif isinstance(target, Donation):
                # Donation payment verified - still needs admin verification via verify_donation
                logger.info(
                    f"Bank transfer verified for donation payment {payment.payment_reference}. "
                    f"Donation {target.tracking_reference} awaits verification."
                )
                
                response_data['donation_tracking_reference'] = target.tracking_reference
                response_data['donation_status'] = target.verification_status
                response_data['message'] = (
                    f'Bank transfer verified. Payment completed for donation {target.tracking_reference}. '
                    f'Donation still requires verification via verify_donation endpoint.'
                )

            elif isinstance(target, EventSponsor):
                if not target.is_verified:
                    target.mark_verified(verifier=request.user)
                if not target.is_processed:
                    target.mark_processed(processor=request.user)

                response_data['sponsor_id'] = str(target.sponsor_id)
                response_data['sponsor_verification_status'] = target.verification_status
                response_data['message'] = (
                    f'Bank transfer verified. Payment completed and sponsor {target.name} is now official.'
                )
            
            else:
                response_data['message'] = (
                    f'Bank transfer verified. Payment completed for {target_type}.'
                )
            
            # Return payment details with target-specific info
            serializer = self.get_serializer(payment)
            response_data.update(serializer.data)
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(
                f"Error verifying bank transfer for payment {payment.payment_reference}: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': f'Failed to verify payment: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================================
# REFUND REQUEST VIEWSETS
# ============================================================================
            
            return Response(
                {
                    'error': f'Failed to verify bank transfer: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================================
# PAYMENT METHOD VIEWSETS
# ============================================================================

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


# ============================================================================
# DISCOUNT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List discounts",
        description="Retrieve all discounts. Only accessible by administrative staff.",
        parameters=[
            OpenApiParameter(
                name='event',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter discounts by event URL-safe title (shows discounts for objects within this event)'
            ),
            OpenApiParameter(
                name='event_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Filter discounts by event UUID (alias of event__event_id)'
            ),
            OpenApiParameter(
                name='discount_type',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by discount type (PERCENTAGE or FIXED)'
            ),
            OpenApiParameter(
                name='active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter active/inactive discounts'
            ),
        ],
        tags=["Discounts"],
    ),
    retrieve=extend_schema(
        summary="Retrieve discount",
        description="Get detailed discount information including rules.",
        tags=["Discounts"],
    ),
    create=extend_schema(
        summary="Create discount",
        description=(
            "Create a new discount with specified type, value, and rules. "
            "Only administrative staff can create discounts."
        ),
        tags=["Discounts"],
    ),
    update=extend_schema(
        summary="Update discount",
        description=(
            "Update a discount with complete payload including all rules. "
            "Use PATCH for partial updates. Only administrative staff can update discounts."
        ),
        tags=["Discounts"],
    ),
    partial_update=extend_schema(
        summary="Partially update discount",
        description=(
            "Partially update a discount such as changing status or rules. "
            "Only administrative staff can update discounts."
        ),
        tags=["Discounts"],
    ),
    destroy=extend_schema(
        summary="Delete discount",
        description=(
            "Delete a discount. Use with caution as this affects pricing and promotions. "
            "Only administrative staff can delete discounts."
        ),
        tags=["Discounts"],
    )
)
class DiscountViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Discount model operations.
    
    Permissions: Administrative staff only (includes event managers with ADMINISTRATIVE role)
    Provides full CRUD for discount management with event-scoped filtering.
    
    Event Filtering:
    - Use ?event=<event_id>, ?event_id=<event_uuid>, or ?event__event_id=<event_uuid> to filter discounts
    - Only shows discounts targeting objects within the specified event
    - Event managers can only manage discounts for their events
    """
    
    queryset = Discount.objects.select_related('created_by', 'target_type').prefetch_related('rules')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DiscountFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name', 'discount_type']
    ordering = ['-created_at']
    lookup_field = 'discount_id'
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions and event access.
        
        - Superusers/staff see all discounts
        - Event managers see only discounts for events they manage
        - Supports ?event=<id>, ?event_id=<uuid>, and ?event__event_id=<uuid> query parameters
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        # Superusers and staff see everything
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check for event filter in query params
        event_id = self.request.query_params.get('event')
        event_uuid = self.request.query_params.get('event_id') or self.request.query_params.get('event__event_id')
        
        if event_id or event_uuid:
            # Event-specific filtering handled by filterset
            # Just ensure user has access to that event
            from apps.events.models import Event, EventRoleAssignment, EventRoleCategoryChoices
            
            try:
                if event_uuid:
                    event = Event.objects.get(event_id=event_uuid)
                else:
                    event = Event.objects.get(url_safe_title=event_id)
                
                # Check if user has administrative role for this event
                has_admin_role = EventRoleAssignment.objects.filter(
                    user=user,
                    event=event,
                    role__category=EventRoleCategoryChoices.ADMINISTRATIVE
                ).exists()
                
                if not has_admin_role:
                    # User doesn't have access to this event
                    return queryset.none()
            except Event.DoesNotExist:
                return queryset.none()
        else:
            # No event filter - show discounts for events user manages
            from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
            from django.contrib.contenttypes.models import ContentType
            from apps.bookings.models import BookingPackage
            
            # Get events where user has ADMINISTRATIVE role
            managed_events = EventRoleAssignment.objects.filter(
                user=user,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE
            ).values_list('event_id', flat=True)
            
            if not managed_events:
                return queryset.none()
            
            # Filter discounts targeting objects within managed events
            # Currently supporting BookingPackage as the main target
            booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
            package_ids = BookingPackage.objects.filter(
                event_id__in=managed_events
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                target_type=booking_package_ct,
                target_id__in=package_ids
            )
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return DiscountListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return DiscountCreateUpdateSerializer
        return DiscountDetailSerializer
    
    def perform_create(self, serializer):
        """Set created_by to current user."""
        serializer.save(created_by=self.request.user)

    @extend_schema(
        summary='Discount eligibility preview',
        description='Evaluate active discounts against an attendee pricing context and return rule-level pass/fail diagnostics.',
        parameters=[
            OpenApiParameter(
                name='attendee_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Attendee UUID to evaluate discount eligibility for',
                required=True,
            ),
            OpenApiParameter(
                name='event_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Optional event UUID to limit results',
                required=False,
            ),
        ],
        responses={
            200: {'description': 'Discount eligibility diagnostics'},
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied'},
        },
        tags=['Discounts'],
    )
    @action(detail=False, methods=['get'], url_path='eligibility-preview')
    def eligibility_preview(self, request):
        from apps.attendee.models import Attendee
        from apps.payments.evaluator import DiscountRuleEvaluator
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage, PackageProduct
        from apps.products.models import Product, ProductVariant

        attendee_id = request.query_params.get('attendee_id')
        if not attendee_id:
            raise ValidationError({'attendee_id': 'attendee_id query parameter is required.'})

        attendee = get_object_or_404(
            Attendee.objects.select_related('event', 'booking', 'user'),
            attendee_id=attendee_id,
        )

        if not (request.user.is_superuser or request.user.is_staff):
            attendee_owner_match = attendee.user_id == request.user.id
            attendee_booking_match = bool(attendee.booking_id and attendee.booking and attendee.booking.made_by_id == request.user.id)
            if not attendee_owner_match and not attendee_booking_match:
                raise ValidationError({'attendee_id': 'You do not have access to this attendee.'})

        event_uuid = request.query_params.get('event_id')
        if event_uuid and attendee.event and str(attendee.event.event_id) != event_uuid:
            raise ValidationError({'event_id': 'attendee does not belong to the provided event_id.'})

        discount_qs = self.get_queryset().filter(active=True).prefetch_related('rules', 'target_type')
        evaluator = DiscountRuleEvaluator()
        context = attendee.pricing_context()

        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        package_product_ct = ContentType.objects.get_for_model(PackageProduct)
        product_ct = ContentType.objects.get_for_model(Product)
        variant_ct = ContentType.objects.get_for_model(ProductVariant)

        package_event_map = {
            row['id']: row['event_id']
            for row in BookingPackage.objects.values('id', 'event_id')
        }
        package_product_map = {
            row['id']: row['booking_package_id']
            for row in PackageProduct.objects.values('id', 'booking_package_id')
        }
        product_event_map = {
            row['id']: row['event_id']
            for row in Product.objects.values('id', 'event_id')
        }
        variant_product_map = {
            row['id']: row['product_id']
            for row in ProductVariant.objects.values('id', 'product_id')
        }

        def discount_event_id(discount):
            if discount.target_type_id == booking_package_ct.id:
                return package_event_map.get(discount.target_id)
            if discount.target_type_id == package_product_ct.id:
                package_id = package_product_map.get(discount.target_id)
                return package_event_map.get(package_id)
            if discount.target_type_id == product_ct.id:
                return product_event_map.get(discount.target_id)
            if discount.target_type_id == variant_ct.id:
                product_id = variant_product_map.get(discount.target_id)
                return product_event_map.get(product_id)
            return None

        applicable = []
        unavailable = []

        for discount in discount_qs:
            target_event_id = discount_event_id(discount)
            if attendee.event_id and target_event_id and target_event_id != attendee.event_id:
                continue

            rules = discount.rules.filter(active=True)
            rule_results = []
            all_passed = True

            for rule in rules:
                passed = evaluator.evaluate(rule, context)
                rule_results.append({
                    'rule_id': str(rule.rule_id),
                    'rule_type': rule.rule_type,
                    'value': rule.value,
                    'passed': passed,
                })
                all_passed = all_passed and passed

            payload = {
                'discount_id': str(discount.discount_id),
                'name': discount.name,
                'discount_type': discount.discount_type,
                'value': str(discount.percentage if discount.discount_type == 'PERCENTAGE' else discount.amount),
                'target_type': discount.target_type.model,
                'target_id': discount.target_id,
                'rules': rule_results,
            }
            if all_passed:
                applicable.append(payload)
            else:
                unavailable.append(payload)

        return Response({
            'attendee_id': str(attendee.attendee_id),
            'event_id': str(attendee.event.event_id) if attendee.event else None,
            'context': context.metadata,
            'applicable_discounts': applicable,
            'unavailable_discounts': unavailable,
        }, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        summary="List discount rules",
        description="Retrieve all discount rules. Only accessible by administrative staff.",
        parameters=[
            OpenApiParameter(
                name='event',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Filter rules by event ID (shows rules for discounts in this event)'
            ),
            OpenApiParameter(
                name='event__event_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Filter rules by event UUID'
            ),
            OpenApiParameter(
                name='event_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Filter rules by event UUID (alias of event__event_id)'
            ),
            OpenApiParameter(
                name='discount',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Filter rules by discount ID'
            ),
            OpenApiParameter(
                name='rule_type',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by rule type'
            ),
        ],
        tags=["Discounts"],
    ),
    retrieve=extend_schema(
        summary="Retrieve discount rule",
        description=(
            "Get detailed information about a specific discount rule including "
            "rule type, value, and conditions for discount application."
        ),
        tags=["Discounts"],
    ),
    create=extend_schema(
        summary="Create discount rule",
        description=(
            "Create a new discount rule for a discount. "
            "Rules define conditions and criteria for discount application. "
            "Only administrative staff can create discount rules."
        ),
        tags=["Discounts"],
    ),
    update=extend_schema(
        summary="Update discount rule",
        description=(
            "Update a discount rule with complete payload. "
            "Use PATCH for partial updates. Only administrative staff can update discount rules."
        ),
        tags=["Discounts"],
    ),
    partial_update=extend_schema(
        summary="Partially update discount rule",
        description=(
            "Partially update a discount rule such as changing value or conditions. "
            "Only administrative staff can update discount rules."
        ),
        tags=["Discounts"],
    ),
    destroy=extend_schema(
        summary="Delete discount rule",
        description=(
            "Delete a discount rule. Affects how discounts are applied. "
            "Only administrative staff can delete discount rules."
        ),
        tags=["Discounts"],
    )
)
class DiscountRuleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for DiscountRule model operations.
    
    Permissions: Administrative staff only (includes event managers with ADMINISTRATIVE role)
    Manages rules for discount application with event-scoped filtering.
    
    Event Filtering:
    - Use ?event=<event_id>, ?event_id=<event_uuid>, or ?event__event_id=<event_uuid> to filter rules
    - Filters based on the event of the discount's target object
    """
    
    queryset = DiscountRule.objects.select_related('discount', 'added_by')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DiscountRuleFilterSet
    search_fields = ['name', 'description', 'value']
    ordering_fields = ['created_at', 'name', 'rule_type']
    ordering = ['-created_at']
    lookup_field = 'rule_id'
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions and event access.
        
        - Superusers/staff see all rules
        - Event managers see only rules for discounts targeting their events
        - Supports ?event=<id>, ?event_id=<uuid>, and ?event__event_id=<uuid> query parameters
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        # Superusers and staff see everything
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check for event filter in query params
        event_id = self.request.query_params.get('event')
        event_uuid = self.request.query_params.get('event_id') or self.request.query_params.get('event__event_id')
        
        if event_id or event_uuid:
            # Event-specific filtering
            from apps.events.models import Event, EventRoleAssignment, EventRoleCategoryChoices
            from django.contrib.contenttypes.models import ContentType
            from apps.bookings.models import BookingPackage
            
            try:
                if event_uuid:
                    event = Event.objects.get(event_id=event_uuid)
                else:
                    event = Event.objects.get(id=event_id)
                
                # Check if user has administrative role for this event
                has_admin_role = EventRoleAssignment.objects.filter(
                    user=user,
                    event=event,
                    role__category=EventRoleCategoryChoices.ADMINISTRATIVE
                ).exists()
                
                if not has_admin_role:
                    return queryset.none()
                
                # Filter rules for discounts targeting objects in this event
                booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
                package_ids = BookingPackage.objects.filter(
                    event=event
                ).values_list('id', flat=True)
                
                queryset = queryset.filter(
                    discount__target_type=booking_package_ct,
                    discount__target_id__in=package_ids
                )
            except Event.DoesNotExist:
                return queryset.none()
        else:
            # No event filter - show rules for discounts in events user manages
            from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
            from django.contrib.contenttypes.models import ContentType
            from apps.bookings.models import BookingPackage
            
            # Get events where user has ADMINISTRATIVE role
            managed_events = EventRoleAssignment.objects.filter(
                user=user,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE
            ).values_list('event_id', flat=True)
            
            if not managed_events:
                return queryset.none()
            
            # Filter rules for discounts targeting objects within managed events
            booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
            package_ids = BookingPackage.objects.filter(
                event_id__in=managed_events
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                discount__target_type=booking_package_ct,
                discount__target_id__in=package_ids
            )
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return DiscountRuleCreateUpdateSerializer
        return DiscountRuleSerializer
    
    def perform_create(self, serializer):
        """Set added_by to current user."""
        serializer.save(added_by=self.request.user)


# ============================================================================
# REFUND VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List refund requests",
        description="List refund requests. Users see their own, admins see all.",
        tags=["Refunds"],
    ),
    retrieve=extend_schema(
        summary="Retrieve refund request",
        description="Get detailed refund request information with associations.",
        tags=["Refunds"],
    ),
    create=extend_schema(
        summary="Create refund request",
        description="Request a refund for a completed payment. Must be payment owner or admin.",
        tags=["Refunds"],
    ),
    update=extend_schema(
        summary="Update refund request",
        description=(
            "Update a refund request with complete payload. "
            "Only administrative staff can update refund requests. "
            "Use PATCH for partial updates."
        ),
        tags=["Refunds"],
    ),
    partial_update=extend_schema(
        summary="Partially update refund request",
        description=(
            "Partially update a refund request such as amount or reason. "
            "Only administrative staff can update refund requests."
        ),
        tags=["Refunds"],
    ),
    destroy=extend_schema(
        summary="Delete refund request",
        description=(
            "Delete a refund request. Can only delete pending refund requests. "
            "Only administrative staff can delete refund requests."
        ),
        tags=["Refunds"],
    )
)
class RefundRequestViewSet(viewsets.ModelViewSet):
    """
    ViewSet for RefundRequest model operations.
    
    Permissions:
    - List/Retrieve: Payment owner or administrative staff
    - Create: Payment owner or administrative staff
    - Update/Actions: Administrative staff only
    
    Custom Actions:
    - verify: Mark refund as verified
    - process: Mark refund as processed
    - reject: Reject refund request
    """
    
    queryset = RefundRequest.objects.select_related(
        'payment', 'payment__user', 'payment__event',
        'requested_by', 'verified_by', 'processed_by'
    ).prefetch_related('associations')
    permission_classes = [permissions.IsAuthenticated, IsRefundRequestOwnerOrAdministrative]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = RefundRequestFilterSet
    search_fields = ['tracking_reference', 'reason']
    ordering_fields = ['requested_at', 'processed_at', 'amount']
    ordering = ['-requested_at']
    lookup_field = 'refund_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return RefundRequestListSerializer
        elif self.action == 'create':
            return RefundRequestCreateSerializer
        elif self.action in ['update', 'partial_update', 'verify', 'process', 'reject']:
            return RefundRequestUpdateSerializer
        return RefundRequestDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)
        
        # Users see refunds for their own payments or events they admin
        return queryset.filter(
            Q(payment__user=user) | Q(payment__event_id__in=admin_event_ids)
        ).distinct()
    
    def perform_create(self, serializer):
        """Validate user can create refund for this payment."""
        user = self.request.user
        payment = serializer.validated_data.get('payment')
        
        # Check if user owns the payment or is admin
        if not (user.is_superuser or user.is_staff) and payment.user != user:
            # Check if user is admin for the event
            from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
            is_event_admin = EventRoleAssignment.objects.filter(
                user=user,
                event=payment.event,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE
            ).exists()
            
            if not is_event_admin:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You can only create refund requests for your own payments.")
        print(serializer.validated_data)
        refund_request = serializer.save()
        payment.transition_to(PaymentStatusChoices.PENDING_REFUND)

        PaymentHistoryAction.objects.create(
            payment=payment,
            action='REFUND_REQUESTED',
            description=(
                f"Refund requested with {refund_request.amount} for payment "
                f"{payment.payment_reference} by {user.username}"
            ),
            metadata={
                'requested_by_id': user.id,
                'requested_by_username': user.username,
                'bank_reference': payment.bank_transfer_reference,
                'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
            },
            notes="Refund request created and payment marked as pending refund.",
            performed_by=user
        )

        logger.info(
            "Refund request created",
            extra={
                'payment_reference': payment.payment_reference,
                'refund_tracking_reference': refund_request.tracking_reference,
                'requested_by': user.username,
            }
        )
    
    @extend_schema(
        summary="Verify refund request",
        description="Mark refund request as verified. Only admins.",
        request=RefundRequestUpdateSerializer,
        responses={200: RefundRequestDetailSerializer},
        tags=["Refunds"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def verify(self, request, refund_id=None):
        """Verify a refund request."""
        refund_request = self.get_object()
        
        if refund_request.verification_status != VerificationStatus.PENDING:
            return Response(
                {'error': 'Can only verify PENDING refund requests'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        refund_request.mark_verified(request.user)
        blocked_summary = AttendeeRefundService.apply_verify_block(refund_request)
        verify_status = AttendeeRefundService.determine_payment_status_after_verify(refund_request)
        refund_request.payment.transition_to(verify_status)

        PaymentHistoryAction.objects.create(
            payment=refund_request.payment,
            action='REFUND_VERIFIED',
            description=f'Refund verified with {refund_request.amount} for payment {refund_request.payment.payment_reference}',
            metadata={
                'verified_by_id': request.user.id,
                'requested_by': request.user.username,
                'bank_reference': refund_request.payment.bank_transfer_reference,
                'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
                'blocked_orders': blocked_summary.get('blocked_orders', 0),
            },
            notes="Refund request marked as verified and payment marked as pending refund.",
            performed_by=request.user
        )
        
        serializer = RefundRequestDetailSerializer(refund_request, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Process refund request",
        description="Mark refund request as processed. Only admins.",
        request=RefundRequestUpdateSerializer,
        responses={200: RefundRequestDetailSerializer},
        tags=["Refunds"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def process(self, request, refund_id=None):
        """Process a verified refund request."""
        refund_request = self.get_object()
        
        if refund_request.verification_status != VerificationStatus.VERIFIED:
            return Response(
                {'error': 'Can only process VERIFIED refund requests'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        refund_request.mark_processed(request.user)
        finalized_summary = AttendeeRefundService.apply_process_finalize(refund_request)
        target_status = AttendeeRefundService.determine_payment_status_after_process(refund_request)
        refund_request.payment.transition_to(target_status)

        action_name = 'REFUND_FULLY_PROCESSED' if refund_request.is_full else 'REFUND_PARTIALLY_PROCESSED'

        PaymentHistoryAction.objects.create(
                payment=refund_request.payment,
                action=action_name,
                description=(
                    f"Refund processed with {refund_request.amount} for payment "
                    f"{refund_request.payment.payment_reference}"
                ),
                metadata={
                    'processed_by_id': request.user.id,
                    'requested_by': request.user.username,
                    'bank_reference': refund_request.payment.bank_transfer_reference,
                    'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
                    'finalized_tickets': finalized_summary.get('finalized_tickets', 0),
                    'finalized_orders': finalized_summary.get('finalized_orders', 0),
                },
                notes="Refund request marked as processed and entities invalidated for selected attendees.",
                performed_by=request.user
            )
        
        serializer = RefundRequestDetailSerializer(refund_request, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Reject refund request",
        description="Reject a pending refund request. Only admins.",
        request=RefundRequestUpdateSerializer,
        responses={200: RefundRequestDetailSerializer},
        tags=["Refunds"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly])
    def reject(self, request, refund_id=None):
        """Reject a refund request."""
        refund_request = self.get_object()
        
        if refund_request.verification_status != VerificationStatus.PENDING:
            return Response(
                {'error': 'Can only reject PENDING refund requests'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        refund_request.mark_rejected(request.user)
        refund_request.payment.transition_to(PaymentStatusChoices.COMPLETED)    

        PaymentHistoryAction.objects.create(
            payment=refund_request.payment,
            action='REFUND_REJECTED',
            description=f'Refund rejected with {refund_request.amount} for payment {refund_request.payment.payment_reference}',
            metadata={
                'rejected_by_id': request.user.id,
                'requested_by': request.user.username,
                'bank_reference': refund_request.payment.bank_transfer_reference,
            },
            notes="Refund request marked as rejected and payment marked as completed.",
            performed_by=request.user
        )
        
        serializer = RefundRequestDetailSerializer(refund_request, context={'request': request})
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="List refund associations",
        description="List refund associations. Only accessible by administrative staff.",
        tags=["Refunds"],
    ),
    retrieve=extend_schema(
        summary="Retrieve refund association",
        description=(
            "Get detailed information about a specific refund association including "
            "linked refund request and associated refundable items."
        ),
        tags=["Refunds"],
    ),
    create=extend_schema(
        summary="Create refund association",
        description=(
            "Create a new refund association linking a refund request to refundable items. "
            "Only administrative staff can create refund associations."
        ),
        tags=["Refunds"],
    ),
    update=extend_schema(
        summary="Update refund association",
        description=(
            "Update a refund association with complete payload. "
            "Use PATCH for partial updates. Only administrative staff can update refund associations."
        ),
        tags=["Refunds"],
    ),
    partial_update=extend_schema(
        summary="Partially update refund association",
        description=(
            "Partially update a refund association. "
            "Only administrative staff can update refund associations."
        ),
        tags=["Refunds"],
    ),
    destroy=extend_schema(
        summary="Delete refund association",
        description=(
            "Delete a refund association. Removes link between refund request and refundable item. "
            "Only administrative staff can delete refund associations."
        ),
        tags=["Refunds"],
    )
)
class RefundAssociationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for RefundAssociation model operations.
    
    Permissions: Administrative staff only
    Manages associations between refund requests and refundable items.
    """
    
    queryset = RefundAssociation.objects.select_related('refund_request')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['id']
    ordering = ['-id']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return RefundAssociationCreateSerializer
        return RefundAssociationSerializer


@extend_schema_view(
    list=extend_schema(
        summary="List refund policies",
        description="List refund policies. Only accessible by administrative staff.",
        tags=["Refunds"],
    ),
    retrieve=extend_schema(
        summary="Retrieve refund policy",
        description=(
            "Get detailed information about a specific refund policy including "
            "policy type, terms, and associated event."
        ),
        tags=["Refunds"],
    ),
    create=extend_schema(
        summary="Create refund policy",
        description=(
            "Create a new refund policy for an event. "
            "Defines refund terms and conditions. Only administrative staff can create refund policies."
        ),
        tags=["Refunds"],
    ),
    update=extend_schema(
        summary="Update refund policy",
        description=(
            "Update a refund policy with complete payload. "
            "Use PATCH for partial updates. Only administrative staff can update refund policies."
        ),
        tags=["Refunds"],
    ),
    partial_update=extend_schema(
        summary="Partially update refund policy",
        description=(
            "Partially update a refund policy such as changing terms or policy type. "
            "Only administrative staff can update refund policies."
        ),
        tags=["Refunds"],
    ),
    destroy=extend_schema(
        summary="Delete refund policy",
        description=(
            "Delete a refund policy. Affects refund eligibility for associated event. "
            "Only administrative staff can delete refund policies."
        ),
        tags=["Refunds"],
    )
)
class RefundPolicyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for RefundPolicy model operations.
    
    Permissions: Administrative staff only
    Manages refund policies for events.
    """
    
    queryset = RefundPolicy.objects.select_related('event')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = RefundPolicyFilterSet
    search_fields = ['notes']
    ordering_fields = ['id', 'policy_type']
    ordering = ['-id']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return RefundPolicyCreateUpdateSerializer
        return RefundPolicySerializer


# ============================================================================
# DONATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List donations",
        description="List donations. Users see their own, admins see all.",
        tags=["Donations"],
    ),
    retrieve=extend_schema(
        summary="Retrieve donation",
        description="Get detailed donation information.",
        tags=["Donations"],
    ),
    create=extend_schema(
        summary="Create donation",
        description="Create a donation on a completed payment.",
        tags=["Donations"],
    ),
    update=extend_schema(
        summary="Update donation",
        description=(
            "Update a donation with complete payload. "
            "Only administrative staff can update donations for verification purposes. "
            "Use PATCH for partial updates."
        ),
        tags=["Donations"],
    ),
    partial_update=extend_schema(
        summary="Partially update donation",
        description=(
            "Partially update a donation such as amount or message. "
            "Only administrative staff can update donations."
        ),
        tags=["Donations"],
    ),
    destroy=extend_schema(
        summary="Delete donation",
        description=(
            "Delete a donation. Can only delete pending donations. "
            "Only administrative staff can delete donations."
        ),
        tags=["Donations"],
    )
)
class DonationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Donation model operations.
    
    Permissions:
    - List/Retrieve: Payment owner or administrative staff
    - Create: Payment owner or administrative staff
    - Update: Administrative staff only (for verification)
    """
    
    queryset = Donation.objects.select_related(
        'payment', 'payment__user', 'donated_by', 'verified_by', 'processed_by'
    )
    permission_classes = [permissions.IsAuthenticated, IsPaymentOwnerOrAdministrative]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DonationFilterSet
    search_fields = ['tracking_reference']
    ordering_fields = ['donated_at', 'amount']
    ordering = ['-donated_at']
    lookup_field = 'donation_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return DonationListSerializer
        elif self.action == 'create':
            return DonationCreateSerializer
        return DonationDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)
        
        # Users see donations for their own payments or events they admin
        return queryset.filter(
            Q(payment__user=user) | Q(payment__event_id__in=admin_event_ids)
        ).distinct()
    
    def perform_create(self, serializer):
        """Validate user can create donation for this payment."""
        user = self.request.user
        payment = serializer.validated_data.get('payment')
        
        # Check if user owns the payment or is admin
        if not (user.is_superuser or user.is_staff) and payment.user != user:
            # Check if user is admin for the event
            from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
            is_event_admin = EventRoleAssignment.objects.filter(
                user=user,
                event=payment.event,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE
            ).exists()
            
            if not is_event_admin:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You can only create donations for your own payments.")
        
        serializer.save()
    
    @extend_schema(
        summary="Create donation with payment",
        description="Create a donation and payment in one transaction. Handles STRIPE (returns client_secret), BANK_TRANSFER (returns reference), and CASH (pending approval). Supports both event-specific and general donations.",
        request=inline_serializer(
            name='DonationCheckoutRequest',
            fields={
                'amount': MoneyField(max_digits=10, decimal_places=2, help_text="Donation amount"),
                'payment_method_id': serializers.IntegerField(help_text="Payment method ID"),
                'user_id': serializers.IntegerField(required=False, help_text="Optional donor user ID (admins only when not self)"),
                'event_id': serializers.UUIDField(required=False, help_text="Optional event ID"),
                'message': serializers.CharField(required=False, max_length=500, help_text="Optional donor message")
            }
        ),
        responses={
            201: {
                'description': 'Donation created successfully',
                'content': {
                    'application/json': {
                        'examples': {
                            'stripe': {
                                'summary': 'Stripe donation',
                                'value': {
                                    'donation_id': 'uuid-here',
                                    'tracking_reference': 'DON-ABC123',
                                    'payment_reference': 'PAY-1-1-XYZ456',
                                    'amount': '100.00',
                                    'currency': 'GBP',
                                    'status': 'pending_payment',
                                    'stripe_client_secret': 'pi_xxx_secret_yyy',
                                    '_links': {}
                                }
                            },
                            'bank_transfer': {
                                'summary': 'Bank transfer donation',
                                'value': {
                                    'donation_id': 'uuid-here',
                                    'tracking_reference': 'DON-ABC123',
                                    'payment_reference': 'PAY-1-1-XYZ456',
                                    'amount': '100.00',
                                    'currency': 'GBP',
                                    'status': 'pending_verification',
                                    'bank_transfer_reference': 'BNK-XYZ789',
                                    'bank_transfer_instructions': 'Transfer £100.00 to account...',
                                    '_links': {}
                                }
                            }
                        }
                    }
                }
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Permission denied'}
        },
        tags=["Donations"],
    )
    @action(detail=False, methods=['post'], url_path='create-with-payment')
    def create_with_payment(self, request):
        """
        Create donation with payment in one transaction.
        
        Creates both Donation and Payment atomically, handling different payment methods:
        - STRIPE: Creates Stripe PaymentIntent, returns client_secret
        - BANK_TRANSFER: Generates reference, returns instructions
        - CASH: Marks as pending approval
        """
        from apps.payments.api.serializers import DonationCheckoutSerializer
        from apps.payments.services.stripe.payment_intents import PaymentIntentService
        from django.db import transaction
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Validate request data
        serializer = DonationCheckoutSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        
        amount = serializer.validated_data['amount']
        donor_user = serializer.validated_data['donor_user']
        payment_method = serializer.validated_data['payment_method']
        event = serializer.validated_data['event']
        message = serializer.validated_data.get('message', '')
        
        # Create donation and payment atomically
        with transaction.atomic():
            # Create donation (status PENDING by default)
            donation = Donation.objects.create(
                amount=amount,
                donated_by=donor_user,
                payment=None  # Will be linked after payment creation
            )
            
            logger.info(
                f"Created donation {donation.tracking_reference} for user {donor_user.id}, "
                f"amount: {amount}"
            )
            
            # Create payment with donation as target
            payment = Payment.objects.create(
                user=donor_user,
                event=event,
                method=payment_method,
                base_amount=amount,
                status=PaymentStatusChoices.PENDING,
                target=donation,
                metadata={
                    'donation': {
                        'donation_id': str(donation.donation_id),
                        'tracking_reference': donation.tracking_reference,
                        'amount': str(donation.amount.amount),
                        'currency': donation.amount.currency.code,
                        'message': message,
                        'donated_by': donor_user.username,
                        'created_by': request.user.username,
                        'event': event.title if event else 'General'
                    }
                }
            )
            
            # Link payment to donation
            donation.payment = payment
            donation.save()
            
            logger.info(
                f"Created payment {payment.payment_reference} for donation {donation.tracking_reference}"
            )
            
            # Prepare response with amount and currency as separate fields
            response_data = {
                'donation_id': str(donation.donation_id),
                'tracking_reference': donation.tracking_reference,
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'amount': str(donation.amount.amount),
                'currency': str(donation.amount.currency.code),
                'donation': DonationListSerializer(donation, context={'request': request}).data,
                '_links': {
                    'self': request.build_absolute_uri(),
                    'donation': request.build_absolute_uri(f'/api/payments/donations/list/{donation.donation_id}/'),
                    'payment': request.build_absolute_uri(f'/api/payments/list/{payment.payment_id}/')
                }
            }
            
            # Handle payment method-specific logic
            if payment_method.method_type == PaymentMethodTypeChoices.STRIPE:
                try:
                    stripe_metadata = payment.prepare_stripe_metadata()
                    payment_intent = PaymentIntentService.create(
                        amount=donation.amount,
                        currency=donation.amount.currency.code,
                        payment_reference=payment.payment_reference,
                        metadata=stripe_metadata,
                        customer_email=donor_user.email
                    )
                    
                    payment.stripe_payment_intent = payment_intent['id']
                    payment.save()
                    
                    response_data['stripe_client_secret'] = payment_intent['client_secret']
                    response_data['status'] = 'pending_payment'
                    
                    logger.info(f"Created Stripe PaymentIntent for donation {donation.tracking_reference}")
                    
                except Exception as e:
                    logger.error(f"Failed to create Stripe PaymentIntent for donation {donation.tracking_reference}: {e}")
                    raise ValidationError({'stripe': f'Failed to create payment intent: {str(e)}'})
            
            elif payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
                response_data['bank_transfer_reference'] = payment.bank_transfer_reference
                response_data['bank_transfer_instructions'] = (
                    f"Please transfer {donation.amount} using reference: {payment.bank_transfer_reference}. "
                    f"Your donation will be processed after verification."
                )
                response_data['status'] = 'pending_verification'
                
                logger.info(f"Generated bank transfer for donation {donation.tracking_reference}")
            
            elif payment_method.method_type == PaymentMethodTypeChoices.CASH:
                response_data['status'] = 'pending_approval'
                response_data['message'] = 'Cash donation will be collected at the venue.'
                
                logger.info(f"Cash donation created: {donation.tracking_reference}")
            
            return Response(response_data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Verify donation",
        description="Admin endpoint to verify or reject a donation after payment is received. Marks donation as VERIFIED or REJECTED based on admin review.",
        request=inline_serializer(
            name='DonationVerificationRequest',
            fields={
                'verified': serializers.BooleanField(help_text="True to verify, False to reject"),
                'notes': serializers.CharField(required=False, help_text="Optional verification notes")
            }
        ),
        responses={
            200: {
                'description': 'Donation verified successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'donation_id': 'uuid-here',
                            'tracking_reference': 'DON-ABC123',
                            'verification_status': 'verified',
                            'message': 'Donation verified successfully',
                            '_links': {}
                        }
                    }
                }
            },
            400: {'description': 'Validation error'},
            403: {'description': 'Admin access required'},
            404: {'description': 'Donation not found'}
        },
        tags=["Donations"],
    )
    @action(
        detail=True, 
        methods=['post'], 
        url_path='verify-donation',
        permission_classes=[permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    )
    def verify_donation(self, request, donation_id=None):
        """
        Verify or reject a donation.
        
        Admin reviews donation and marks as VERIFIED or REJECTED.
        Payment must be completed before donation can be verified.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"Donation verification attempt for donation_id={donation_id} by user={request.user.username}"
        )
        donation = self.get_object()
        
        # Validate input
        verified = request.data.get('verified')
        notes = request.data.get('notes', '')
        
        if verified is None:
            return Response(
                {'error': 'verified field is required (true or false)'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if payment is completed
        if donation.payment.status != PaymentStatusChoices.COMPLETED:
            return Response(
                {
                    'error': f'Cannot verify donation until payment is completed. '
                             f'Current payment status: {donation.payment.status}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if already processed
        if donation.is_processed or donation.is_verified or donation.is_rejected:
            logger.warning(
                f"Attempt to re-verify already processed donation {donation.tracking_reference} "
                f"by {request.user.username}"
            )
            return Response(
                {
                    'error': f'Donation has already been processed. Current status: {donation.verification_status}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            if verified:
                # Mark as verified
                donation.mark_verified(request.user)
                logger.info(
                    f"Donation {donation.tracking_reference} verified by {request.user.username}"
                )
                message = 'Donation verified successfully'
            else:
                # Mark as rejected
                donation.mark_rejected(request.user)
                logger.info(
                    f"Donation {donation.tracking_reference} rejected by {request.user.username}"
                )
                message = 'Donation rejected'
            
            # Log action in payment history
            PaymentHistoryAction.objects.create(
                payment=donation.payment,
                action='DONATION_VERIFIED' if verified else 'DONATION_REJECTED',
                description=f'Donation {donation.tracking_reference} {"verified" if verified else "rejected"} by administrator',
                metadata={
                    'donation_id': str(donation.donation_id),
                    'tracking_reference': donation.tracking_reference,
                    'verified_by_id': request.user.id,
                    'verified_by_username': request.user.username,
                    'verified': verified,
                    'notes': notes,
                },
                notes=notes,
                performed_by=request.user
            )
            
            # Return donation details
            serializer = self.get_serializer(donation)
            response_data = serializer.data
            response_data['message'] = message
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(
                f"Error verifying donation {donation.tracking_reference}: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': f'Failed to verify donation: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================================
# PAYMENT HISTORY VIEWSETS
# ============================================================================# ============================================================================
# PAYMENT HISTORY VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List payment history actions",
        description="List payment history. Only accessible by administrative staff.",
        tags=["Payment History"],
    ),
    retrieve=extend_schema(
        summary="Retrieve payment history action",
        description=(
            "Get detailed information about a specific payment history action including "
            "action type, timestamp, performer, and associated metadata for audit trails."
        ),
        tags=["Payment History"],
    )
)
class PaymentHistoryActionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for PaymentHistoryAction model.
    
    Permissions: Administrative staff only
    Provides audit trail of payment actions.
    """
    
    queryset = PaymentHistoryAction.objects.select_related('payment', 'performed_by')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    serializer_class = PaymentHistoryActionSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PaymentHistoryActionFilterSet
    search_fields = ['description', 'notes', 'action']
    ordering_fields = ['timestamp', 'action']
    ordering = ['-timestamp']


class CreditExpenseViewSet(viewsets.ModelViewSet):
    """CRUD viewset for credit expenses."""

    queryset = CreditExpense.objects.select_related('event', 'created_by', 'verified_by', 'processed_by', 'target_type')
    permission_classes = [permissions.IsAuthenticated, IsCreditAccessible]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CreditExpenseFilterSet
    search_fields = ['credit_id', 'description', 'event__name', 'created_by__username']
    ordering_fields = ['created_at', 'updated_at', 'amount', 'paid_date', 'expense_type', 'is_settled']
    ordering = ['-created_at']
    lookup_field = 'credit_id'

    def get_serializer_class(self):
        if self.action == 'list':
            return CreditExpenseListSerializer
        if self.action == 'create':
            return CreditExpenseCreateSerializer
        if self.action in ['update', 'partial_update']:
            return CreditExpenseUpdateSerializer
        return CreditExpenseDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        accessible_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).values_list('event_id', flat=True)

        finance_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__name__icontains='finance'
        ).values_list('event_id', flat=True)

        return queryset.filter(
            Q(created_by=user) |
            Q(event_id__in=accessible_event_ids) |
            Q(event_id__in=finance_event_ids)
        ).distinct()

    def perform_create(self, serializer):
        event = serializer.validated_data.get('event')
        if not _user_can_manage_credits(self.request.user, event):
            raise exceptions.PermissionDenied('You do not have permission to create credits for this event.')

        serializer.save(created_by=self.request.user)


class BankTransferEvidenceViewSet(viewsets.ModelViewSet):
    """CRUD viewset for bank transfer evidence uploads and confirmation."""

    queryset = BankTransferEvidence.objects.select_related('payment', 'verified_by', 'processed_by')
    permission_classes = [permissions.IsAuthenticated, IsBankTransferEvidenceAccessible]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BankTransferEvidenceFilterSet
    search_fields = ['transfer_id', 'payer_name', 'payment__payment_reference']
    ordering_fields = ['uploaded_at', 'updated_at', 'verification_status', 'auto_expiry_date']
    ordering = ['-uploaded_at']
    lookup_field = 'bank_transfer_id'

    def get_serializer_class(self):
        if self.action == 'list':
            return BankTransferEvidenceListSerializer
        if self.action == 'create':
            return BankTransferEvidenceCreateSerializer
        if self.action in ['update', 'partial_update']:
            return BankTransferEvidenceUpdateSerializer
        return BankTransferEvidenceDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        managed_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).values_list('event_id', flat=True)

        finance_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__name__icontains='finance'
        ).values_list('event_id', flat=True)

        return queryset.filter(
            Q(payment__user=user) |
            Q(payment__event_id__in=managed_event_ids) |
            Q(payment__event_id__in=finance_event_ids)
        ).distinct()

    def perform_create(self, serializer):
        payment = serializer.validated_data.get('payment')
        if payment and not _user_can_manage_bank_evidence(self.request.user, payment.event) and payment.user != self.request.user:
            raise exceptions.PermissionDenied('You do not have permission to attach evidence to this payment.')

        if not payment and not self.request.user.is_superuser and not self.request.user.is_staff:
            raise exceptions.PermissionDenied('A payment is required unless you are an administrative user.')

        serializer.save()

    @action(detail=True, methods=['post'])
    def confirm_payment_match(self, request, bank_transfer_id=None):
        evidence = self.get_object()

        if not _user_can_manage_bank_evidence(request.user, evidence.payment.event if evidence.payment else None):
            raise exceptions.PermissionDenied('You do not have permission to confirm this evidence record.')

        if not evidence.payment:
            matched_payment = Payment.objects.filter(bank_transfer_reference__icontains=evidence.transfer_id).first()
            if matched_payment:
                evidence.payment = matched_payment
                evidence.save(update_fields=['payment'])

        evidence.mark_verified(request.user)
        serializer = self.get_serializer(evidence)
        return Response(serializer.data)
