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
    OpenApiResponse,
    inline_serializer,
)

from apps.payments.models import (
    Payment, PaymentStatusChoices, PaymentMethodTypeChoices,
    Donation, PaymentHistoryAction,
)
from apps.common.models import VerificationStatus
from apps.payments.api.serializers import (
    PaymentListSerializer, PaymentDetailSerializer, PaymentCreateSerializer, PaymentUpdateSerializer,
    PaymentMethodSerializer, PaymentMethodDetailSerializer, PaymentMethodCreateUpdateSerializer,
)
from apps.payments.api.filtersets import PaymentFilterSet, PaymentMethodFilterSet
from apps.payments.api.permissions import IsAdministrativeStaffOnly, IsPaymentOwnerOrAdministrative
   
from apps.bookings.services import TicketCreatorService
from apps.payments.models import PaymentMethodTypeChoices
from apps.bookings.models import Booking
from apps.organisations.models import EventSponsor
from apps.products.models import Order, OrderStatusChoices
from apps.payments.models import Donation
from apps.common.pagination import StandardPagination

from apps.events.services.notifications import create_notification, NotificationPriorityChoices, NotificationTypeChoices

import logging

logger = logging.getLogger(__name__)


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

    def get_permissions(self):
        """Restrict write actions to administrative staff only."""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsAdministrativeStaffOnly()]
        return [permissions.IsAuthenticated(), IsPaymentOwnerOrAdministrative()]
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admins see all
        # if user.is_superuser or user.is_staff:
        #     return queryset
        
        # Check if user has administrative role for any event
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        admin_event_ids = EventRoleAssignment.objects.filter(
            user=user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).values_list('event_id', flat=True)

        # Exclude all inflight/abandoned reservation DRAFTING payments from non-admin views.
        # These are internal checkout artefacts (bank transfer references not yet confirmed)
        # and must not be visible or mutable via the public API.
        _RESERVATION_PAYMENT_TYPES = [
            'booking_checkout_reservation',
            'order_checkout_reservation',
        ]
        reservation_q = Q()
        for pt in _RESERVATION_PAYMENT_TYPES:
            reservation_q |= Q(metadata__contains={'payment_type': pt}) & Q(status=PaymentStatusChoices.DRAFTING)
        # Users see their own payments or payments for events they admin
        # return queryset.filter(
        #     Q(user=user) | Q(event_id__in=admin_event_ids)
        # ).exclude(reservation_q).distinct()
        # return payments that admins can see
        # if event= provided, return payments for that event that ADMINS can see
        # if not event=, return only the payments the user owns
        event_id = self.request.query_params.get('event')
        if event_id:
            if event_id in admin_event_ids:
                return queryset.filter(event_id=event_id).exclude(reservation_q).distinct()
            else:
                return queryset.none()
        return queryset.filter(user=user).exclude(reservation_q).distinct()
    
    def perform_create(self, serializer):
        """Create payment — only administrative staff may call this endpoint."""
        # Payment creation is restricted to admins via get_permissions().
        # Internal checkout flows bypass the API layer entirely.
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
        
        try:
            payment.transition_to(PaymentStatusChoices.COMPLETED)
        except DjangoValidationError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        
        # Log action
        PaymentHistoryAction.objects.create(
            payment=payment,
            action='MARKED_COMPLETED',
            description='Payment marked as completed by administrator',
            performed_by=request.user
        )

        create_notification(
            payment=payment,
            locked_order=payment.orders.first() if payment.orders.exists() else None,
            booking=payment.target if isinstance(payment.target, Booking) else None,
            event=payment.event,
            message=f'Payment marked as completed by {request.user.username}',
            metadata={
                'action': 'MARKED_COMPLETED',
                'performed_by_id': request.user.id,
                'performed_by_username': request.user.username,
            },
            priority=NotificationPriorityChoices.HIGH,
            notification_type=NotificationTypeChoices.PAYMENT_UPDATE
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
            description=f'Payment marked as failed by {request.user.username}',
            performed_by=request.user
        )

        create_notification(
            payment=payment,
            locked_order=payment.target if isinstance(payment.target, Order) else None,
            booking=payment.target if isinstance(payment.target, Booking) else None,
            event=payment.event,
            message=f'Payment marked as failed by {request.user.username}',
            metadata={
                'action': 'MARKED_FAILED',
                'performed_by_id': request.user.id,
                'performed_by_username': request.user.username,
            },
            priority=NotificationPriorityChoices.HIGH,
            notification_type=NotificationTypeChoices.PAYMENT_UPDATE
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

        cancelled_order_ids = []
        with transaction.atomic():
            payment.status = PaymentStatusChoices.CANCELLED
            payment.save()

            try:
                from apps.products.models import OrderStatusChoices

                related_orders = list(payment.orders.select_for_update().all())
                if payment.target and hasattr(payment.target, 'transition_to') and hasattr(payment.target, 'status'):
                    if all(getattr(o, 'pk', None) != payment.target.pk for o in related_orders):
                        related_orders.append(payment.target)

                for order in related_orders:
                    if order.status in [OrderStatusChoices.CANCELLED, OrderStatusChoices.REFUNDED]:
                        continue

                    if order.can_transition_to(OrderStatusChoices.CANCELLED):
                        order.updated_by = request.user
                        order.transition_to(OrderStatusChoices.CANCELLED)
                        cancelled_order_ids.append(str(order.order_id))
                    else:
                        logger.warning(
                            "Order %s linked to Payment %s could not transition to cancelled from %s",
                            order.id,
                            payment.id,
                            order.status,
                        )
            except Exception as exc:
                logger.exception("Failed to cancel related orders for payment %s", payment.id)
                raise ValidationError(
                    f"Payment cancellation aborted because linked order rollback failed: {str(exc)}"
                )
        
        # Log action
        PaymentHistoryAction.objects.create(
            payment=payment,
            action='CANCELLED',
            description=f'Payment cancelled by {request.user.username}. Cancelled orders: {cancelled_order_ids}',
            performed_by=request.user,
            metadata={
                'cancelled_order_ids': cancelled_order_ids,
            },
        )

        create_notification(
            payment=payment,
            locked_order=payment.target if isinstance(payment.target, Order) else None,
            booking=payment.target if isinstance(payment.target, Booking) else None,
            event=payment.event,
            message=f'Payment cancelled by {request.user.username}',
            metadata={
                'action': 'CANCELLED',
                'performed_by_id': request.user.id,
                'performed_by_username': request.user.username,
                'cancelled_order_ids': cancelled_order_ids,
            },
            priority=NotificationPriorityChoices.HIGH,
            notification_type=NotificationTypeChoices.PAYMENT_UPDATE
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
        
        payment = self.get_object()
        
        # Validate input
        verified = request.data.get('verified', False)
        notes = request.data.get('notes', '')
        
        target = payment.target
        target_type = type(target).__name__  
        if target_type is None:
            target_type = "External Payment"

        # Validate payment status
        if payment.status != PaymentStatusChoices.PENDING:
            return Response(
                {
                    'error': f'Can only verify PENDING payments. Current status: {payment.status}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if not verified:
            payment.transition_to(PaymentStatusChoices.FAILED)
            PaymentHistoryAction.objects.create(
                payment=payment,
                action='BANK_TRANSFER_FAILED',
                description=f'Bank transfer failed for {target_type} by administrator',
                metadata={
                    'failed_by_id': request.user.id,
                    'failed_by_username': request.user.username,
                    'bank_reference': payment.bank_transfer_reference,
                    'target_type': target_type,
                    'notes': notes,
                },
                notes=notes,
                performed_by=request.user
            )

            create_notification(
                payment=payment,
                locked_order=payment.target if isinstance(payment.target, Order) else None,
                booking=payment.target if isinstance(payment.target, Booking) else None,
                event=payment.event,
                message=f'Bank transfer failed for {target_type} by {request.user.username}',
                metadata={
                    'action': 'BANK_TRANSFER_FAILED',
                    'failed_by_id': request.user.id,
                    'failed_by_username': request.user.username,
                    'bank_reference': payment.bank_transfer_reference,
                    'target_type': target_type,
                    'notes': notes,
                },
                priority=NotificationPriorityChoices.HIGH,
                notification_type=NotificationTypeChoices.PAYMENT_UPDATE
            )

            serializer = self.get_serializer(payment)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        # Validate payment method is bank transfer
        if not payment.method or payment.method.method_type != PaymentMethodTypeChoices.BANK_TRANSFER:
            return Response(
                {
                    'error': 'This endpoint is only for BANK_TRANSFER payments. '
                             f'Current method: {payment.method.method_type if payment.method else "None"}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not payment.bank_transfer_evidence.filter(verification_status=VerificationStatus.VERIFIED).exists():
            return Response(
                {
                    'error': (
                        'Cannot verify/complete bank transfer payment without a VERIFIED bank transfer evidence record.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        


        if target_type is None:
            target_type = "External Payment"
        
        try:
            # Transition payment to completed
            payment.transition_to(PaymentStatusChoices.COMPLETED)
            
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

            create_notification(
                payment=payment,
                locked_order=payment.target if isinstance(payment.target, Order) else None,
                booking=payment.target if isinstance(payment.target, Booking) else None,
                event=payment.event,
                message=f'Bank transfer verified for {target_type} by {request.user.username}',
                metadata={
                    'action': 'BANK_TRANSFER_VERIFIED',
                    'verified_by_id': request.user.id,
                    'verified_by_username': request.user.username,
                    'bank_reference': payment.bank_transfer_reference,
                    'target_type': target_type,
                    'notes': notes,
                },
                priority=NotificationPriorityChoices.HIGH,
                notification_type=NotificationTypeChoices.PAYMENT_UPDATE
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
            
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(
                f"Error verifying bank transfer for payment {payment.payment_reference}: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': f'Failed to verify payment: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

