from rest_framework import viewsets, status, permissions, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from djmoney.contrib.django_rest_framework import MoneyField

from apps.payments.models import (
    Payment, PaymentStatusChoices, PaymentMethodTypeChoices,
    Donation, PaymentHistoryAction,
)
from apps.payments.api.serializers import (
    DonationListSerializer, DonationDetailSerializer, DonationCreateSerializer,
)
from apps.payments.api.filtersets import DonationFilterSet
from apps.payments.api.permissions import IsAdministrativeStaffOnly, IsPaymentOwnerOrAdministrative
from apps.payments.models import PaymentMethodTypeChoices
from apps.payments.models import Donation
from apps.common.pagination import StandardPagination

import logging

logger = logging.getLogger(__name__)


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
                    stripe_account_id = payment_method.get_stripe_account_id() if hasattr(payment_method, 'get_stripe_account_id') else None

                    payment_intent = PaymentIntentService.create(
                        amount=donation.amount,
                        currency=donation.amount.currency.code,
                        payment_reference=payment.payment_reference,
                        metadata=stripe_metadata,
                        customer_email=donor_user.email,
                        stripe_account_id=stripe_account_id,
                    )
                    
                    payment.stripe_payment_intent = getattr(payment_intent, 'id', None) or payment_intent['id']
                    payment.save()
                    
                    response_data['stripe_client_secret'] = getattr(payment_intent, 'client_secret', None) or payment_intent['client_secret']
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