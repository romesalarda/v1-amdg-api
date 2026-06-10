from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from apps.payments.models import (
    PaymentStatusChoices,
    RefundRequest, RefundAssociation, RefundPolicy,
    PaymentHistoryAction,
)
from apps.common.models import VerificationStatus
from apps.payments.api.serializers import (
    RefundRequestListSerializer, RefundRequestDetailSerializer, RefundRequestCreateSerializer, RefundRequestUpdateSerializer,
    RefundAssociationSerializer, RefundAssociationCreateSerializer,
    RefundPolicySerializer, RefundPolicyCreateUpdateSerializer,
)
from apps.payments.api.filtersets import RefundRequestFilterSet, RefundPolicyFilterSet
from apps.payments.api.permissions import IsAdministrativeStaffOnly, IsRefundRequestOwnerOrAdministrative

from apps.payments.services.attendee_refunds import AttendeeRefundService
from apps.payments.tasks import send_refund_email
from apps.common.pagination import StandardPagination
from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices

from apps.events.services.notifications import create_notification, NotificationPriorityChoices, NotificationTypeChoices

from rest_framework.exceptions import PermissionDenied

import logging

logger = logging.getLogger(__name__)


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
        if not (user.is_superuser or user.is_staff) and payment.user != user: # TODO: this should be implemented in object perms
            # Check if user is admin for the event
            is_event_admin = EventRoleAssignment.objects.filter(
                user=user,
                event=payment.event,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE
            ).exists()
            
            if not is_event_admin:
                raise PermissionDenied("You can only create refund requests for your own payments.")
            
        with transaction.atomic():
            refund_request = serializer.save()
            payment.transition_to(PaymentStatusChoices.PENDING_REFUND)

            PaymentHistoryAction.objects.create(
                payment=payment,
                action='REFUND_REQUESTED',
                description=( # TODO: more descriptive into what was refunded (tickets, whole payment, etc.)
                    f"Refund requested with {refund_request.amount} for payment "
                    f"{payment.payment_reference} by {user.username}"
                ),
                metadata={
                    'requested_by_id': user.id,
                    'requested_by_username': user.username,
                    'bank_reference': payment.bank_transfer_reference,
                    'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
                    'target_kind': (refund_request.metadata or {}).get('target_kind'),
                    'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                },
                notes="Refund request created and payment marked as pending refund.",
                performed_by=user
            )

            create_notification(
                payment=payment,
                locked_order=None,
                booking=None,
                event=payment.event,
                notif_type=NotificationTypeChoices.REFUND_REQUEST,
                priority=NotificationPriorityChoices.HIGH,
                metadata={
                    'refund_request_id': refund_request.pk,
                    'refund_request_tracking_reference': refund_request.tracking_reference,
                    'requested_by_id': user.id,
                    'requested_by_username': user.username,
                    'bank_reference': payment.bank_transfer_reference,
                    'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
                    'target_kind': (refund_request.metadata or {}).get('target_kind'),
                    'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                },
                message=f"Refund request {refund_request.tracking_reference} created for payment {payment.payment_reference} by {user.username}"
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
        
        with transaction.atomic():
            try:
                refund_request.mark_verified(request.user)
            except ValidationError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
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
                    'target_kind': (refund_request.metadata or {}).get('target_kind'),
                    'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                    'blocked_orders': blocked_summary.get('blocked_orders', 0),
                },
                notes="Refund request marked as verified and payment marked as pending refund.",
                performed_by=request.user
            )

            create_notification(
                payment=refund_request.payment,
                locked_order=None,
                booking=None,
                event=refund_request.payment.event,
                priority=NotificationPriorityChoices.HIGH,
                notification_type=NotificationTypeChoices.REFUND_UPDATE,
                metadata={
                    'refund_request_id': refund_request.pk,
                    'refund_request_tracking_reference': refund_request.tracking_reference,
                    'verified_by_id': request.user.id,
                    'verified_by_username': request.user.username,
                    'bank_reference': refund_request.payment.bank_transfer_reference,
                    'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
                    'target_kind': (refund_request.metadata or {}).get('target_kind'),
                    'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                    'blocked_orders': blocked_summary.get('blocked_orders', 0),
                },
                message=f"Refund request {refund_request.tracking_reference} verified for payment {refund_request.payment.payment_reference} by {request.user.username}"
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
        
        with transaction.atomic():
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
                        'target_kind': (refund_request.metadata or {}).get('target_kind'),
                        'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                        'finalized_tickets': finalized_summary.get('finalized_tickets', 0),
                        'finalized_orders': finalized_summary.get('finalized_orders', 0),
                    },
                    notes="Refund request marked as processed and entities invalidated for selected attendees.",
                    performed_by=request.user
                )

            _refund_pk = refund_request.pk
            transaction.on_commit(lambda: send_refund_email.delay(_refund_pk))

            create_notification(
                payment=refund_request.payment,
                locked_order=None,
                booking=None,
                event=refund_request.payment.event,
                priority=NotificationPriorityChoices.HIGH,
                notification_type=NotificationTypeChoices.REFUND_UPDATE,
                metadata={
                    'refund_request_id': refund_request.pk,
                    'refund_request_tracking_reference': refund_request.tracking_reference,
                    'processed_by_id': request.user.id,
                    'processed_by_username': request.user.username,
                    'bank_reference': refund_request.payment.bank_transfer_reference,
                    'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
                    'target_kind': (refund_request.metadata or {}).get('target_kind'),
                    'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                    'finalized_tickets': finalized_summary.get('finalized_tickets', 0),
                    'finalized_orders': finalized_summary.get('finalized_orders', 0),
                },
                message=f"Refund request {refund_request.tracking_reference} processed for payment {refund_request.payment.payment_reference} by {request.user.username}"
            )
            logger.info(
                "Queued refund email for refund_request pk=%s (payment %s)",
                _refund_pk,
                refund_request.payment.payment_reference,
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
        
        with transaction.atomic():
            refund_request.mark_rejected(request.user)

            rollback_summary = AttendeeRefundService.apply_reject_rollback(refund_request)
            restored_payment_status = rollback_summary.get('restored_payment_status', PaymentStatusChoices.COMPLETED)
            try:
                refund_request.payment.transition_to(restored_payment_status)
            except DjangoValidationError:
                # Defensive fallback for legacy data without rollback snapshots.
                fallback_status = PaymentStatusChoices.COMPLETED
                if restored_payment_status == PaymentStatusChoices.COMPLETED:
                    fallback_status = PaymentStatusChoices.PARTIALLY_REFUNDED
                if refund_request.payment.status != fallback_status:
                    refund_request.payment.transition_to(fallback_status)
                restored_payment_status = fallback_status

            PaymentHistoryAction.objects.create(
                payment=refund_request.payment,
                action='REFUND_REJECTED',
                description=f'Refund rejected with {refund_request.amount} for payment {refund_request.payment.payment_reference}',
                metadata={
                    'rejected_by_id': request.user.id,
                    'requested_by': request.user.username,
                    'bank_reference': refund_request.payment.bank_transfer_reference,
                    'target_kind': (refund_request.metadata or {}).get('target_kind'),
                    'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                    'restored_payment_status': restored_payment_status,
                    'restored_orders': rollback_summary.get('restored_orders', 0),
                    'skipped_orders': rollback_summary.get('skipped_orders', 0),
                    'failed_order_ids': rollback_summary.get('failed_order_ids', []),
                },
                notes="Refund request marked as rejected and linked entities restored to pre-refund state where possible.",
                performed_by=request.user
            )

            create_notification(
                payment=refund_request.payment,
                locked_order=None,
                booking=None,
                event=refund_request.payment.event,
                priority=NotificationPriorityChoices.HIGH,
                notification_type=NotificationTypeChoices.REFUND_REJECTION,
                metadata={
                    'refund_request_id': refund_request.pk,
                    'refund_request_tracking_reference': refund_request.tracking_reference,
                    'rejected_by_id': request.user.id,
                    'rejected_by_username': request.user.username,
                    'bank_reference': refund_request.payment.bank_transfer_reference,
                    'target_kind': (refund_request.metadata or {}).get('target_kind'),
                    'refund_scope': (refund_request.metadata or {}).get('refund_scope'),
                    'restored_payment_status': restored_payment_status,
                    'restored_orders': rollback_summary.get('restored_orders', 0),
                    'skipped_orders': rollback_summary.get('skipped_orders', 0),
                    'failed_order_ids': rollback_summary.get('failed_order_ids', []),
                },
                message=f"Refund request {refund_request.tracking_reference} rejected for payment {refund_request.payment.payment_reference} by {request.user.username}"
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