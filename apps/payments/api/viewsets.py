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
from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from django.utils import timezone
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any

from apps.payments.models import (
    Payment, PaymentMethod, PaymentStatusChoices,
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


# ============================================================================
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
