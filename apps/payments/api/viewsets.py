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
from rest_framework import viewsets, status, permissions, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from django.utils import timezone
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

from apps.payments.models import (
    Payment, PaymentMethod, PaymentStatusChoices, PaymentMethodTypeChoices,
    Discount, DiscountRule,
    RefundRequest, RefundAssociation, RefundPolicy,
    Donation, PaymentHistoryAction
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
    PaymentHistoryActionSerializer
)
from .filtersets import (
    PaymentFilterSet, PaymentMethodFilterSet, DiscountFilterSet, DiscountRuleFilterSet,
    RefundRequestFilterSet, RefundPolicyFilterSet, DonationFilterSet, PaymentHistoryActionFilterSet
)
from .permissions import (
    IsAdministrativeStaff, IsAdministrativeStaffOnly, IsPaymentOwnerOrAdministrative,
    IsRefundRequestOwnerOrAdministrative, IsReadOnly
)


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
        'user', 'event', 'method'
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
        if not (user.is_superuser or user.is_staff) and payment_user != user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only create payments for yourself.")
        
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
        tags=["Discounts"],
    ),
    retrieve=extend_schema(
        summary="Retrieve discount",
        description="Get detailed discount information including rules.",
        tags=["Discounts"],
    ),
)
class DiscountViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Discount model operations.
    
    Permissions: Administrative staff only
    Provides full CRUD for discount management.
    """
    
    queryset = Discount.objects.select_related('created_by').prefetch_related('rules')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DiscountFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name', 'discount_type']
    ordering = ['-created_at']
    lookup_field = 'discount_id'
    
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


@extend_schema_view(
    list=extend_schema(
        summary="List discount rules",
        description="Retrieve all discount rules. Only accessible by administrative staff.",
        tags=["Discounts"],
    ),
)
class DiscountRuleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for DiscountRule model operations.
    
    Permissions: Administrative staff only
    Manages rules for discount application.
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
        
        serializer.save()
    
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
        
        serializer = RefundRequestDetailSerializer(refund_request, context={'request': request})
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="List refund associations",
        description="List refund associations. Only accessible by administrative staff.",
        tags=["Refunds"],
    ),
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
        
        payment_method = serializer.validated_data['payment_method']
        event = serializer.validated_data['event']
        message = serializer.validated_data.get('message', '')
        
        # Create donation and payment atomically
        with transaction.atomic():
            # Create donation (status PENDING by default)
            donation = Donation.objects.create(
                amount=amount,
                donated_by=request.user,
                payment=None  # Will be linked after payment creation
            )
            
            logger.info(
                f"Created donation {donation.tracking_reference} for user {request.user.id}, "
                f"amount: {amount}"
            )
            
            # Create payment with donation as target
            payment = Payment.objects.create(
                user=request.user,
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
                        'donated_by': request.user.username,
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
                        customer_email=request.user.email
                    )
                    
                    payment.stripe_payment_intent_id = payment_intent['id']
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
