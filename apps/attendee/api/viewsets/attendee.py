from rest_framework import viewsets, status, filters, serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from django.utils import timezone

from apps.attendee.models import Attendee


from apps.attendee.api.serializers import (
    AttendeeListSerializer, AttendeeDetailSerializer,
    AttendeeCreateSerializer, AttendeeUpdateSerializer,
    AttendeePreRemovalSummarySerializer,
)
from apps.attendee.services.pre_removal import AttendeePreRemovalSummaryService

from apps.attendee.api.filtersets import AttendeeFilterSet
from apps.attendee.api.permissions import IsAttendeeOwnerOrStaff
from apps.common.pagination import StandardPagination

@extend_schema_view(
    list=extend_schema(
        summary="List Attendees",
        description=(
            "Retrieve a paginated list of attendees with comprehensive filtering and search capabilities. "
            "Results include attendee demographics, contact information, event associations, and relationship details. "
            "Staff members can view all attendees, while regular users can only view attendees they own or guard."
        ),
        tags=['Attendees'],
        parameters=[
            OpenApiParameter(
                'search',
                OpenApiTypes.STR,
                description='Search by first name, last name, email, phone number, or attendee display ID'
            ),
            OpenApiParameter(
                'event',
                OpenApiTypes.UUID,
                description='Filter attendees by event UUID'
            ),
            OpenApiParameter(
                'age_min',
                OpenApiTypes.INT,
                description='Filter attendees with minimum age (inclusive)'
            ),
            OpenApiParameter(
                'age_max',
                OpenApiTypes.INT,
                description='Filter attendees with maximum age (inclusive)'
            ),
            OpenApiParameter(
                'is_minor',
                OpenApiTypes.BOOL,
                description='Filter minors only (under 18 years old)'
            ),
            OpenApiParameter(
                'include_deleted',
                OpenApiTypes.BOOL,
                description='Include soft-deleted attendees in results (staff only)'
            ),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Attendee Details",
        description=(
            "Retrieve comprehensive information about a specific attendee including personal details, "
            "event associations, emergency contacts, dietary requirements, medical conditions, "
            "accessibility requirements, and consent records. Includes HATEOAS links for related resources."
        ),
        tags=['Attendees']
    ),
    create=extend_schema(
        summary="Create Attendee",
        description=(
            "Create a new attendee record with personal information and event association. "
            "For attendees with 'SELF' relationship type, the authenticated user will be automatically linked. "
            "Generates a unique attendee display ID for easy reference."
        ),
        tags=['Attendees']
    ),
    update=extend_schema(
        summary="Update Attendee",
        description=(
            "Update all fields of an existing attendee record. Requires full payload with all fields. "
            "Use PATCH for partial updates. Only attendee owners, guardians, or staff can update records."
        ),
        tags=['Attendees']
    ),
    partial_update=extend_schema(
        summary="Partially Update Attendee",
        description=(
            "Update specific fields of an attendee record without providing complete payload. "
            "Ideal for updating individual attributes like contact information or relationship status."
        ),
        tags=['Attendees']
    ),
    destroy=extend_schema(
        summary="Delete Attendee",
        description=(
            "Soft delete an attendee record by marking it as deleted without permanent removal. "
            "Records deleted timestamp and deleting user for audit purposes. "
            "Deleted attendees can be excluded from list queries."
        ),
        tags=['Attendees']
    )
)
class AttendeeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Attendee records with nested resource support.
    
    Provides comprehensive CRUD operations for attendee management including:
    - Personal information (name, DOB, gender, contact details)
    - Event associations and booking references
    - User relationships (self, child, spouse, friend, etc.)
    - Nested resources (emergency contacts, dietary/medical/accessibility requirements)
    - Soft delete functionality for data retention
    - Advanced filtering and search capabilities
    """
    
    queryset = Attendee.objects.select_related(
        'event', 'user', 'area_from', 'booking', 'defined_by'
    ).prefetch_related(
        'emergency_contacts', 'organisations',
        'attendeedietaryrequirement__dietary_requirement',
        'attendeemedicalcondition__medical_condition',
        'attendeeaccessibilityrequirement__accessibility_requirement'
    )
    permission_classes = [IsAttendeeOwnerOrStaff]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeFilterSet
    search_fields = ['first_name', 'last_name', 'email', 'attendee_display_id']
    ordering_fields = ['created_at', 'first_name', 'last_name', 'date_of_birth']
    ordering = ['-created_at']
    lookup_field = 'attendee_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AttendeeListSerializer
        elif self.action in ['create']:
            return AttendeeCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AttendeeUpdateSerializer
        return AttendeeDetailSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions and exclude soft-deleted by default."""
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()
        # Filter out soft-deleted attendees unless explicitly requested

        print("\n SQL Query: ", self.filter_queryset(queryset).query)  # Debug: Print the raw SQL query for inspection
        if not self.request.query_params.get('include_deleted'):
            queryset = queryset.filter(deleted_at__isnull=True)
        
        # Superusers and staff see all
        if user.is_superuser or user.is_staff:
            return queryset
        
        
        # Regular users see their own attendees and those they guard
        return queryset.filter(
            Q(user=user) |
            Q(guardians__user=user) |
            Q(event__staff_members__user=user) |
            Q(booking__made_by=user)
        ).distinct()
    
    def perform_create(self, serializer):
        """Handle attendee creation with automatic user assignment for SELF relationship."""
        from apps.attendee.models import AttendeeRelationship
        
        relationship = serializer.validated_data.get('relationship_to_user')
        user_in_data = serializer.validated_data.get('user')
        
        # If creating a SELF attendee without explicit user (regular user flow)
        # Auto-assign the authenticated user
        if relationship == AttendeeRelationship.SELF and not user_in_data:
            if not (self.request.user.is_staff or self.request.user.is_superuser):
                # Regular users creating SELF attendees get auto-assigned
                serializer.save(user=self.request.user)
                return
        # elif not user_in_data:
        #     # For non-SELF relationships, user must be specified (e.g. parent creating child attendee)
        #     serializer.save(user=self.request.user)
        # Otherwise save normally (admin can specify user, or non-SELF relationships)
        serializer.save()

    def _is_payment_linked_to_attendee(self, attendee, payment):
        service = AttendeePreRemovalSummaryService(request=self.request)
        return service.is_payment_linked_to_attendee(attendee, payment)

    def _build_pre_removal_summary(self, attendee):
        service = AttendeePreRemovalSummaryService(request=self.request)
        return service.build_summary(attendee)
    
    def perform_destroy(self, instance):
        """Perform soft delete by setting deleted_at and deleted_by instead of hard delete."""
        pre_removal = self._build_pre_removal_summary(instance)
        if not pre_removal['can_delete']:
            raise ValidationError({
                'detail': 'Attendee cannot be deleted while unresolved linked objects exist.',
                'pre_removal_summary': pre_removal,
            })

        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save(update_fields=['deleted_at', 'deleted_by'])
        
    @extend_schema(
        summary='Request Attendee Cancellation Refund',
        description=(
            'Create a refund request for a specific attendee with attendee-scoped defaults. '
            'For booking payments, attendee_ids defaults to the current attendee when omitted. '
            'Uses the payments refund validation flow (amount integrity, policy checks, and used-ticket safeguards).'
        ),
        tags=['Attendees'],
        request=inline_serializer(
            name='AttendeeCancellationRefundRequest',
            fields={
                'payment_id': drf_serializers.UUIDField(required=True),
                'amount': drf_serializers.DecimalField(max_digits=10, decimal_places=2, required=True),
                'amount_currency': drf_serializers.CharField(required=False, default='GBP'),
                'reason': drf_serializers.CharField(required=True),
                'reason_code': drf_serializers.CharField(required=False),
                'override_used_ticket_block': drf_serializers.BooleanField(required=False, default=False),
                'override_reason': drf_serializers.CharField(required=False),
                'attendee_ids': drf_serializers.ListField(child=drf_serializers.UUIDField(), required=False),
                'refund_items': drf_serializers.ListField(child=drf_serializers.DictField(), required=False),
            },
        ),
        responses={
            201: inline_serializer(
                name='AttendeeCancellationRefundResponse',
                fields={
                    'refund_id': drf_serializers.UUIDField(),
                    'tracking_reference': drf_serializers.CharField(),
                    'verification_status': drf_serializers.CharField(),
                    'payment_id': drf_serializers.UUIDField(),
                    'amount': drf_serializers.CharField(),
                    'selected_attendee_ids': drf_serializers.ListField(child=drf_serializers.UUIDField()),
                },
            ),
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Permission denied'),
        },
    )
    @action(detail=True, methods=['post'], url_path='request-cancellation-refund')
    def request_cancellation_refund(self, request, attendee_id=None):
        """Create refund request for a specific attendee with strict attendee-payment linkage checks."""
        attendee = self.get_object()

        payment_id = request.data.get('payment_id')
        if not payment_id:
            raise ValidationError({'payment_id': 'payment_id is required.'})

        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        from apps.payments.models import Payment, PaymentHistoryAction, PaymentStatusChoices
        from apps.payments.api.serializers import RefundRequestCreateSerializer
        from apps.payments.services.attendee_refunds import AttendeeRefundService

        payment = get_object_or_404(Payment, payment_id=payment_id)
        if not self._is_payment_linked_to_attendee(attendee, payment):
            raise ValidationError({'payment_id': 'Payment is not linked to the selected attendee.'})

        user = request.user
        is_event_admin = EventRoleAssignment.objects.filter(
            user=user,
            event=payment.event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).exists()
        if not (user.is_superuser or user.is_staff or payment.user_id == user.id or is_event_admin):
            raise PermissionDenied('You do not have permission to request this attendee refund.')

        payload = request.data.copy()
        payload['payment'] = str(payment.payment_id)

        # For booking-linked payments, default attendee_ids to the current attendee when omitted.
        if AttendeeRefundService.is_booking_payment(payment) and not payload.get('attendee_ids'):
            payload['attendee_ids'] = [str(attendee.attendee_id)]

        refund_serializer = RefundRequestCreateSerializer(data=payload, context={'request': request})
        refund_serializer.is_valid(raise_exception=True)
        refund_request = refund_serializer.save()

        if payment.status == PaymentStatusChoices.COMPLETED:
            payment.transition_to(PaymentStatusChoices.PENDING_REFUND)

        PaymentHistoryAction.objects.create(
            payment=payment,
            action='REFUND_REQUESTED_ATTENDEE',
            description=f'Attendee scoped refund requested for {attendee.full_name}',
            metadata={
                'attendee_id': str(attendee.attendee_id),
                'attendee_display_id': attendee.attendee_display_id,
                'refund_id': str(refund_request.refund_id),
                'requested_by_id': request.user.id,
                'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
            },
            notes='Refund requested through attendee endpoint.',
            performed_by=request.user,
        )

        return Response(
            {
                'refund_id': str(refund_request.refund_id),
                'tracking_reference': refund_request.tracking_reference,
                'verification_status': refund_request.verification_status,
                'payment_id': str(payment.payment_id),
                'amount': str(refund_request.amount),
                'selected_attendee_ids': (refund_request.metadata or {}).get('selected_attendee_ids', []),
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary='Get Attendee Pre-Removal Summary',
        description=(
            'Return a comprehensive blocker report explaining why an attendee can or cannot be deleted. '
            'Includes linked payments, outstanding states, active tickets/orders, open attendance, and actionable hints '
            'so frontend can guide the user through required resolution steps.'
        ),
        tags=['Attendees'],
        responses={200: AttendeePreRemovalSummarySerializer},
    )
    @action(detail=True, methods=['get'], url_path='pre-removal-summary')
    def pre_removal_summary(self, request, attendee_id=None):
        '''
        Returns related objects before allowing deletion of an attendee. Returns a summary of related records that would be affected by deletion.
        '''
        attendee = self.get_object()
        return Response(self._build_pre_removal_summary(attendee), status=status.HTTP_200_OK)
    
    @extend_schema(
        summary='Cancel Attendee Registration',
        description=(
            'Cancel an attendee\'s registration for the event. Marks the attendee as cancelled without deleting the record. '
            'Useful for scenarios where the attendee should no longer be considered active but historical data must be retained.'
        ),
        request=inline_serializer(
            name='AttendeeCancellationRequest',
            fields={
                'invalidate': drf_serializers.BooleanField(
                    required=False,
                    default=False,
                )
            }
        ), 
        tags=['Attendees'],
        responses={
            200: OpenApiResponse(description='Attendee registration cancelled successfully.'),
            400: OpenApiResponse(description='Attendee is already cancelled.'),
        },
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, attendee_id):
        """Custom action to cancel an attendee's registration."""
        attendee = self.get_object()

        invalidate = request.data.get('invalidate', False)

        if attendee.is_cancelled:
            return Response({'detail': 'Attendee is already cancelled.'}, status=status.HTTP_400_BAD_REQUEST)

        attendee.mark_cancelled(performed_by=request.user, notes='Cancelled manually')
        if invalidate:
            attendee.invalidate()

        return Response({'detail': 'Attendee registration cancelled successfully.'}, status=status.HTTP_200_OK)

