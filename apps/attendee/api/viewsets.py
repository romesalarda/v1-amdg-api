"""
ViewSets for the attendee app.

Provides comprehensive API endpoints for attendee management with HATEOAS,
nested resources, and proper schema documentation.
"""
from rest_framework import viewsets, status, filters, serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError, PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Prefetch
from django.core.paginator import Paginator
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

from apps.attendee.models import (
    Attendee, AttendeeGuardian, AttendeeAction,
    FamilyGroup, FamilyAttendee, AttendeeMessage,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    EmergencyContact, Consent, AttendeeConsent,
    EventAttendance, AttendeeOrganisation
)

from .serializers import (
    AttendeeListSerializer, AttendeeDetailSerializer,
    AttendeeCreateSerializer, AttendeeUpdateSerializer,
    AttendeeGuardianSerializer, AttendeeActionSerializer,
    FamilyGroupListSerializer, FamilyGroupDetailSerializer,
    FamilyGroupCreateUpdateSerializer, FamilyAttendeeSerializer,
    AttendeeMessageListSerializer, AttendeeMessageDetailSerializer,
    AttendeeMessageCreateSerializer, AttendeeMessageUpdateSerializer,
    AccessibilityRequirementSerializer, AttendeeAccessibilityRequirementSerializer,
    DietaryRequirementSerializer, AttendeeDietaryRequirementSerializer,
    MedicalConditionSerializer, AttendeeMedicalConditionSerializer,
    EmergencyContactSerializer, ConsentSerializer, AttendeeConsentSerializer,
    EventAttendanceSerializer, AttendeeOrganisationSerializer,
    AttendeePreRemovalBlockerItemSerializer, AttendeePreRemovalSummarySerializer,
)

from .filtersets import (
    AttendeeFilterSet, AttendeeGuardianFilterSet, AttendeeActionFilterSet,
    FamilyGroupFilterSet, FamilyAttendeeFilterSet, AttendeeMessageFilterSet,
    AccessibilityRequirementFilterSet, AttendeeAccessibilityRequirementFilterSet,
    DietaryRequirementFilterSet, AttendeeDietaryRequirementFilterSet,
    MedicalConditionFilterSet, AttendeeMedicalConditionFilterSet,
    EmergencyContactFilterSet, ConsentFilterSet, AttendeeConsentFilterSet,
    EventAttendanceFilterSet, AttendeeOrganisationFilterSet,
)

from .permissions import (
    IsAttendeeOwnerOrStaff, IsAttendeeOwnerOrReadOnly,
    IsEventStaffOrReadOnly, CanManageAttendeePersonalInfo,
    CanAccessMessages, IsStaffOrReadOnly, CanAccessFamilyInfo
)


class StandardPagination(PageNumberPagination):
    """Standard pagination configuration."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class NestedAttendeeViewSetMixin:
    """
    Mixin to filter queryset by attendee_id from nested URL.
    
    For use with nested URLs like: /attendees/{attendee_id}/resource/
    """
    
    def get_attendee(self):
        """Get the parent attendee from the URL."""
        attendee_id = self.kwargs.get('attendee_id')
        if attendee_id:
            return get_object_or_404(Attendee, attendee_id=attendee_id, deleted_at__isnull=True)
        return None
    
    def get_queryset(self):
        """Filter queryset by attendee from URL parameters."""
        queryset = super().get_queryset()
        attendee = self.get_attendee()
        if attendee:
            queryset = queryset.filter(attendee=attendee)
        return queryset
    
    def perform_create(self, serializer):
        """Automatically set attendee on create."""
        attendee = self.get_attendee()
        if attendee:          
            serializer.save(attendee=attendee)
        else:
            serializer.save()


# ============================================================================
# ATTENDEE VIEWSETS
# ============================================================================

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
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
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
        if not self.request.query_params.get('include_deleted'):
            queryset = queryset.filter(deleted_at__isnull=True)
        
        # Superusers and staff see all
        if user.is_superuser or user.is_staff:
            return queryset
        
        # Regular users see their own attendees and those they guard
        return queryset.filter(
            Q(user=user) |
            Q(guardians__user=user) |
            Q(event__staff_members__user=user)
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
        
        # Otherwise save normally (admin can specify user, or non-SELF relationships)
        serializer.save()

    def _get_linked_payments(self, attendee):
        """Get payments linked to attendee via booking, tickets, or orders."""
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import Booking
        from apps.payments.models import Payment

        booking_payment_ids = []
        if attendee.booking_id:
            booking_ct = ContentType.objects.get_for_model(Booking)
            booking_payment_ids = Payment.objects.filter(
                target_type=booking_ct,
                target_id=str(attendee.booking_id),
            ).values_list('id', flat=True)

        ticket_payment_ids = attendee.tickets.exclude(payment__isnull=True).values_list('payment_id', flat=True)
        order_payment_ids = attendee.orders.exclude(payment__isnull=True).values_list('payment_id', flat=True)

        return Payment.objects.filter(
            Q(id__in=booking_payment_ids) |
            Q(id__in=ticket_payment_ids) |
            Q(id__in=order_payment_ids)
        ).select_related('event', 'user').distinct()

    def _get_page_and_page_size(self):
        """Read page and page_size using standard pagination query parameters."""
        query_params = getattr(self.request, 'query_params', None) or getattr(self.request, 'GET', {}) or {}

        try:
            page = int(query_params.get('page', 1) or 1)
        except (TypeError, ValueError):
            page = 1

        default_size = StandardPagination.page_size
        max_size = StandardPagination.max_page_size
        page_size_key = StandardPagination.page_size_query_param

        try:
            page_size = int(query_params.get(page_size_key, default_size) or default_size)
        except (TypeError, ValueError):
            page_size = default_size

        page = max(page, 1)
        page_size = min(max(page_size, 1), max_size)
        return page, page_size

    def _serialize_blocker_item(self, payload):
        serializer = AttendeePreRemovalBlockerItemSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _serialize_pre_removal_summary(self, payload):
        serializer = AttendeePreRemovalSummarySerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _get_payment_type(self, payment):
        """Return a stable payment type label for UI grouping."""
        if payment.target_type:
            target_model = payment.target_type.model.lower()
            if target_model == 'eventsponsor':
                return 'sponsorship'
            return {
                'booking': 'booking',
                'order': 'order',
                'ticket': 'ticket',
            }.get(target_model, target_model)

        metadata = payment.metadata if isinstance(payment.metadata, dict) else {}
        payment_type = str(metadata.get('payment_type') or '').lower()
        if 'booking' in payment_type:
            return 'booking'
        if 'order' in payment_type:
            return 'order'
        if 'ticket' in payment_type:
            return 'ticket'
        if 'donation' in payment_type:
            return 'donation'
        if 'sponsor' in payment_type:
            return 'sponsorship'
        return 'unknown'

    def _get_payment_descriptor(self, payment):
        payment_type = self._get_payment_type(payment)
        return {
            'booking': 'Booking Payment',
            'order': 'Order Payment',
            'ticket': 'Ticket Payment',
            'donation': 'Donation Payment',
            'sponsorship': 'Sponsorship Payment',
        }.get(payment_type, 'Payment')

    def _get_payment_status_bucket(self, status):
        return {
            'DRAFTING': 'in_flight',
            'PENDING': 'outstanding',
            'COMPLETED': 'settled',
            'PENDING_REFUND': 'refund_pending',
            'REFUNDED': 'refunded',
            'PARTIALLY_REFUNDED': 'partially_refunded',
            'CANCELLED': 'cancelled',
            'FAILED': 'failed',
        }.get(status, 'unknown')

    def _get_payment_links(self, payment):
        request = getattr(self, 'request', None)
        if not request:
            return {}

        links = {
            'self': request.build_absolute_uri(f"/api/payments/list/{payment.payment_id}/"),
        }
        if payment.refund_requests.exists():
            links['refund_requests'] = request.build_absolute_uri(f"/api/payments/refunds/?payment={payment.payment_id}")
        if payment.method:
            links['method'] = request.build_absolute_uri(f"/api/payments/methods/{payment.method.id}/")
        return links

    def _can_request_attendee_refund(self, payment):
        from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
        from apps.payments.models import PaymentStatusChoices

        user = getattr(self.request, 'user', None)
        if not user or user.is_anonymous:
            return False, 'Sign in as an eligible user to request this refund.'

        if payment.status != PaymentStatusChoices.COMPLETED:
            return False, 'Refund requests can only be created for completed payments.'

        if payment.refund_requests.filter(is_active=True).exists():
            return False, 'This payment already has an active refund request.'

        is_event_admin = EventRoleAssignment.objects.filter(
            user=user,
            event=payment.event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).exists()
        if user.is_superuser or user.is_staff or payment.user_id == user.id or is_event_admin:
            return True, None

        return False, 'You do not have permission to request this attendee refund.'

    def _serialize_payment_blocker_item(self, attendee, payment, blocker_code, *, refund_summaries=None):
        payment_type = self._get_payment_type(payment)
        payment_descriptor = self._get_payment_descriptor(payment)
        can_request_refund, refund_block_reason = self._can_request_attendee_refund(payment)

        item = {
            'payment_id': str(payment.payment_id),
            'payment_reference': payment.payment_reference,
            'payment_type': payment_type,
            'payment_descriptor': payment_descriptor,
            'payment_status': payment.status,
            'payment_status_bucket': self._get_payment_status_bucket(payment.status),
            'amount': str(payment.base_amount) if payment.base_amount else None,
            'currency': payment.base_amount.currency.code if payment.base_amount else None,
            'method_type': payment.method.method_type if payment.method else None,
            'method_title': payment.method.title if payment.method else None,
            'can_request_refund': can_request_refund,
            'refund_block_reason': refund_block_reason,
            '_links': self._get_payment_links(payment),
        }

        if payment.target_type and payment.target:
            if payment_type == 'booking':
                booking = payment.target
                item.update({
                    'booking_id': str(booking.id),
                    'booking_reference': booking.booking_reference,
                    'booking_attendee_count': booking.attendees.filter(deleted_at__isnull=True).count(),
                })
            elif payment_type == 'order':
                order = payment.target
                item.update({
                    'order_id': str(order.order_id),
                    'order_reference': order.order_reference_id,
                    'order_status': order.status,
                    'order_amount': str(order.total_amount),
                    'order_attendee_id': str(order.attendee.attendee_id) if order.attendee else None,
                })

        if blocker_code == 'active_refunds':
            item['active_refunds'] = refund_summaries or []
            item['active_refund_count'] = len(refund_summaries or [])

        return self._serialize_blocker_item(item)

    def _serialize_ticket_blocker_item(self, ticket):
        item = {
            'ticket_id': str(ticket.ticket_id),
            'ticket_code': ticket.ticket_code,
            'ticket_type': ticket.ticket_type.title if ticket.ticket_type else None,
            'ticket_scope': ticket.ticket_type.scope if ticket.ticket_type else None,
            'status': ticket.status,
        }

        if ticket.payment:
            payment = ticket.payment
            item.update({
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'payment_type': self._get_payment_type(payment),
                'payment_descriptor': self._get_payment_descriptor(payment),
                'payment_status': payment.status,
                'payment_status_bucket': self._get_payment_status_bucket(payment.status),
                'amount': str(payment.base_amount) if payment.base_amount else None,
                'currency': payment.base_amount.currency.code if payment.base_amount else None,
                'method_type': payment.method.method_type if payment.method else None,
                'method_title': payment.method.title if payment.method else None,
                '_links': self._get_payment_links(payment),
            })

        return self._serialize_blocker_item(item)

    def _serialize_order_blocker_item(self, order):
        item = {
            'order_id': str(order.order_id),
            'order_reference': order.order_reference_id,
            'status': order.status,
            'order_amount': str(order.total_amount),
            'order_attendee_id': str(order.attendee.attendee_id) if order.attendee else None,
            'order_attendee_name': order.attendee.full_name if order.attendee else None,
        }

        if order.payment:
            payment = order.payment
            item.update({
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'payment_type': self._get_payment_type(payment),
                'payment_descriptor': self._get_payment_descriptor(payment),
                'payment_status': payment.status,
                'payment_status_bucket': self._get_payment_status_bucket(payment.status),
                'amount': str(payment.base_amount) if payment.base_amount else None,
                'currency': payment.base_amount.currency.code if payment.base_amount else None,
                'method_type': payment.method.method_type if payment.method else None,
                'method_title': payment.method.title if payment.method else None,
                '_links': self._get_payment_links(payment),
            })

        return self._serialize_blocker_item(item)

    def _serialize_refund_blocker_item(self, payment):
        active_refunds = payment.refund_requests.filter(is_active=True).select_related('requested_by').order_by('-requested_at')
        refund_summaries = [
            {
                'refund_id': str(refund.refund_id),
                'tracking_reference': refund.tracking_reference,
                'verification_status': refund.verification_status,
                'is_active': refund.is_active,
                'amount': str(refund.amount),
                'requested_at': refund.requested_at.isoformat() if refund.requested_at else None,
                'requested_by_name': refund.requested_by.username if refund.requested_by else None,
                'reason': refund.reason,
            }
            for refund in active_refunds[:10]
        ]

        return self._serialize_payment_blocker_item(
            attendee=None,
            payment=payment,
            blocker_code='active_refunds',
            refund_summaries=refund_summaries,
        )

    def _paginate_items(self, items):
        page, page_size = self._get_page_and_page_size()
        paginator = Paginator(items, page_size)
        page_obj = paginator.get_page(page)

        return list(page_obj.object_list), {
            'count': paginator.count,
            'page': page_obj.number,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
            'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
        }

    def _is_payment_linked_to_attendee(self, attendee, payment):
        return self._get_linked_payments(attendee).filter(id=payment.id).exists()

    def _build_pre_removal_summary(self, attendee):
        """
        Build a summary of what will happen if the attendee is deleted.
        This includes identifying any blocking issues.
        """
        from apps.payments.models import PaymentStatusChoices

        blockers = []
        summary_counts = {
            'linked_payments': 0,
            'linked_tickets': 0,
            'linked_orders': 0,
            'event_attendances': 0,
            'outstanding_payments': 0,
            'active_refund_requests': 0,
            'active_tickets': 0,
            'unresolved_orders': 0,
            'family_memberships': 0,
            'open_attendance': 0,
        }
        suggested_actions = []

        # Get all linked payments first
        linked_payments = self._get_linked_payments(attendee)

        # Define payments that should NOT block deletion but might still be useful to show.
        # These are payments in a terminal state that don't represent an ongoing financial obligation.
        non_blocking_payment_statuses = [
            PaymentStatusChoices.REFUNDED,
            PaymentStatusChoices.CANCELLED,
            PaymentStatusChoices.FAILED,
        ]

        # Filter for payments that ARE considered blockers.
        blocking_payments = linked_payments.exclude(status__in=non_blocking_payment_statuses)

        # 1. Block if there are outstanding payments
        # These are payments that are in-flight, completed, or pending a refund.
        outstanding_payments = blocking_payments.filter(
            status__in=[
                PaymentStatusChoices.DRAFTING,
                PaymentStatusChoices.PENDING,
                PaymentStatusChoices.COMPLETED,
                PaymentStatusChoices.PENDING_REFUND,
                PaymentStatusChoices.PARTIALLY_REFUNDED,
            ]
        )
        if outstanding_payments.exists():
            outstanding_payment_items, outstanding_payment_pagination = self._paginate_items([
                self._serialize_payment_blocker_item(attendee, payment, 'outstanding_payments')
                for payment in outstanding_payments
            ])
            blockers.append({
                'code': 'outstanding_payments',
                'severity': 'high',
                'count': outstanding_payments.count(),
                'message': 'Attendee has outstanding payments that must be resolved before deletion.',
                'items': outstanding_payment_items,
                'pagination': outstanding_payment_pagination,
                'action_hint': 'Review each payment and request a refund if applicable.',
            })

        # 2. Warn about general linked payment history (excluding non-blocking ones)
        # This serves as a review step for any other potentially relevant payments.
        if blocking_payments.exists():
            linked_payment_items, linked_payment_pagination = self._paginate_items([
                self._serialize_payment_blocker_item(attendee, payment, 'linked_payments')
                for payment in blocking_payments
            ])

            if linked_payment_items:
                blockers.append({
                    'code': 'linked_payments',
                    'severity': 'high',
                    'count': blocking_payments.count(),
                    'message': 'Attendee has linked payment history that may require review before deletion.',
                    'items': linked_payment_items,
                    'pagination': linked_payment_pagination,
                    'action_hint': 'Review each payment and request a refund from the specific payment row when eligible.',
                })
        return self._serialize_pre_removal_summary({
            'attendee': {
                'attendee_id': str(attendee.attendee_id),
                'attendee_display_id': attendee.attendee_display_id,
                'full_name': attendee.full_name,
            },
            'can_delete': len(blockers) == 0,
            'blockers': blockers,
            'summary_counts': summary_counts,
            'suggested_actions': suggested_actions,
        })
    
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



# ============================================================================
# ATTENDEE GUARDIAN VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Guardians",
        description=(
            "Retrieve a list of guardian relationships linking users to attendees they are responsible for. "
            "Guardians have permission to view and manage attendee information for minors or dependents."
        ),
        tags=['Attendee Guardians']
    ),
    retrieve=extend_schema(
        summary="Get Guardian Details",
        description=(
            "Retrieve detailed information about a specific guardian relationship including "
            "the user serving as guardian, the attendee under their care, and the relationship timestamp."
        ),
        tags=['Attendee Guardians']
    ),
    create=extend_schema(
        summary="Create Guardian Relationship",
        description=(
            "Establish a new guardian relationship between a user and an attendee. "
            "This grants the user permission to manage the attendee's information and make decisions on their behalf."
        ),
        tags=['Attendee Guardians']
    ),
    update=extend_schema(
        summary="Update Guardian Relationship",
        description="Update details of an existing guardian relationship.",
        tags=['Attendee Guardians']
    ),
    partial_update=extend_schema(
        summary="Partially Update Guardian Relationship",
        description="Partially update a guardian relationship without providing complete payload.",
        tags=['Attendee Guardians']
    ),
    destroy=extend_schema(
        summary="Delete Guardian Relationship",
        description=(
            "Remove a guardian relationship, revoking the user's permission to manage the attendee. "
            "This action does not delete the user or attendee records."
        ),
        tags=['Attendee Guardians']
    )
)
class AttendeeGuardianViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeGuardian relationships.
    
    Handles the many-to-many relationship between users and attendees they are responsible for.
    Guardians typically manage minors or dependents and have elevated permissions for those attendees.
    """
    
    queryset = AttendeeGuardian.objects.select_related('user', 'attendee').all()
    serializer_class = AttendeeGuardianSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeGuardianFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        return queryset.filter(
            Q(user=user) |
            Q(attendee__user=user) |
            Q(attendee__guardians__user=user) |
            Q(attendee__event__staff_members__user=user)
        ).distinct()


# ============================================================================
# ATTENDEE ACTION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Actions",
        description=(
            "Retrieve an audit log of actions performed on attendees. "
            "Tracks check-ins, check-outs, registrations, and other attendee-related events. "
            "Useful for compliance, reporting, and activity monitoring."
        ),
        tags=['Attendee Actions']
    ),
    retrieve=extend_schema(
        summary="Get Action Details",
        description=(
            "Retrieve detailed information about a specific attendee action including "
            "the action type, performer, timestamp, and associated attendee."
        ),
        tags=['Attendee Actions']
    ),
    create=extend_schema(
        summary="Create Attendee Action",
        description=(
            "Log a new action performed on an attendee such as check-in, check-out, or status change. "
            "Creates an immutable audit trail entry for compliance and tracking purposes."
        ),
        tags=['Attendee Actions']
    )
)
class AttendeeActionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeAction records.
    
    Provides an audit trail of actions performed on attendees throughout their lifecycle.
    Actions are immutable once created (no update/delete) to maintain audit integrity.
    Restricted to event staff for action creation.
    """
    
    queryset = AttendeeAction.objects.select_related('attendee', 'performed_by').all()
    serializer_class = AttendeeActionSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeActionFilterSet
    ordering_fields = ['performed_at']
    ordering = ['-performed_at']
    http_method_names = ['get', 'post', 'head', 'options']  # No update/delete


# ============================================================================
# FAMILY GROUP VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Family Groups",
        description=(
            "Retrieve a list of family groups with their associated members. "
            "Family groups organize attendees into related units for easier management and communication. "
            "Results include family name, creation details, and member count."
        ),
        tags=['Family Groups']
    ),
    retrieve=extend_schema(
        summary="Get Family Group Details",
        description=(
            "Retrieve comprehensive information about a specific family group including all members, "
            "their relationships within the family (parent, child, sibling, etc.), "
            "and primary guardian designations."
        ),
        tags=['Family Groups']
    ),
    create=extend_schema(
        summary="Create Family Group",
        description=(
            "Create a new family group to organize related attendees. "
            "Family groups facilitate bulk operations and communication with multiple attendees "
            "who share family relationships."
        ),
        tags=['Family Groups']
    ),
    update=extend_schema(
        summary="Update Family Group",
        description=(
            "Update family group information such as the family name or designation. "
            "Use member management endpoints to add or remove attendees from the group."
        ),
        tags=['Family Groups']
    ),
    partial_update=extend_schema(
        summary="Partially Update Family Group",
        description="Partially update family group information without providing complete payload.",
        tags=['Family Groups']
    ),
    destroy=extend_schema(
        summary="Delete Family Group",
        description=(
            "Delete a family group and remove all member associations. "
            "This does not delete the individual attendee records, only the grouping relationship."
        ),
        tags=['Family Groups']
    )
)
class FamilyGroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing FamilyGroup records.
    
    Family groups organize related attendees (family members) for easier management.
    Supports grouping attendees by family relationships and designating primary guardians.
    """
    
    queryset = FamilyGroup.objects.prefetch_related('family_attendees__attendee').all()
    permission_classes = [CanAccessFamilyInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = FamilyGroupFilterSet
    search_fields = ['family_name']
    ordering_fields = ['created_at', 'family_name']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        return queryset.filter(
            Q(created_by=user) |
            Q(family_attendees__attendee__user=user) |
            Q(family_attendees__attendee__guardians__user=user) |
            Q(family_attendees__attendee__event__staff_members__user=user)
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return FamilyGroupListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return FamilyGroupCreateUpdateSerializer
        return FamilyGroupDetailSerializer
    
    @extend_schema(
        summary="Get Family Group Members",
        description=(
            "Retrieve all members of a specific family group with their relationships and roles. "
            "Shows which attendees belong to the family and their relationships (parent, child, sibling, etc.), "
            "including primary guardian designations."
        ),
        tags=['Family Groups'],
        responses={200: FamilyAttendeeSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='members')
    def members(self, request, pk=None):
        """Get all members of a family group."""
        family_group = self.get_object()
        members = family_group.family_attendees.select_related('attendee').all()
        serializer = FamilyAttendeeSerializer(members, many=True, context={'request': request})
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="List Family Attendee Memberships",
        description=(
            "Retrieve a list of family attendee memberships showing how attendees are associated with family groups. "
            "Includes relationship types (parent, child, sibling) and primary guardian status."
        ),
        tags=['Family Attendees']
    ),
    retrieve=extend_schema(
        summary="Get Family Membership Details",
        description=(
            "Retrieve details of a specific family attendee membership including "
            "the attendee, family group, relationship type, and whether they are designated as primary guardian."
        ),
        tags=['Family Attendees']
    ),
    create=extend_schema(
        summary="Add Attendee to Family",
        description=(
            "Add an attendee to a family group with a specified relationship (parent, child, sibling, spouse, etc.). "
            "Optionally designate them as the primary guardian for the family."
        ),
        tags=['Family Attendees']
    ),
    update=extend_schema(
        summary="Update Family Membership",
        description=(
            "Update a family attendee membership to change relationship type or primary guardian status."
        ),
        tags=['Family Attendees']
    ),
    partial_update=extend_schema(
        summary="Partially Update Family Membership",
        description="Partially update family membership details without providing complete payload.",
        tags=['Family Attendees']
    ),
    destroy=extend_schema(
        summary="Remove Attendee from Family",
        description=(
            "Remove an attendee from a family group. "
            "This does not delete the attendee record, only the family association."
        ),
        tags=['Family Attendees']
    )
)
class FamilyAttendeeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing FamilyAttendee relationships.
    
    Handles the many-to-many relationship between family groups and attendees,
    including relationship types and primary guardian designations.
    """
    
    queryset = FamilyAttendee.objects.select_related('family_group', 'attendee').all()
    serializer_class = FamilyAttendeeSerializer
    permission_classes = [CanAccessFamilyInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = FamilyAttendeeFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_anonymous:
            return queryset.none()

        if user.is_superuser or user.is_staff:
            return queryset

        return queryset.filter(
            Q(family_group__created_by=user) |
            Q(attendee__user=user) |
            Q(attendee__guardians__user=user) |
            Q(attendee__event__staff_members__user=user)
        ).distinct()


# ============================================================================
# MESSAGE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Messages",
        description=(
            "Retrieve a list of messages sent to or from attendees. "
            "Messages can be inquiries, requests, or communications between attendees and staff. "
            "Supports filtering by priority (low, medium, high) and response status."
        ),
        tags=['Attendee Messages']
    ),
    retrieve=extend_schema(
        summary="Get Message Details",
        description=(
            "Retrieve full details of a specific attendee message including subject, message content, "
            "priority level, submission timestamp, response details, and staff notes. "
            "Shows complete message thread with any staff responses."
        ),
        tags=['Attendee Messages']
    ),
    create=extend_schema(
        summary="Create Message",
        description=(
            "Create a new message from or about an attendee. "
            "Messages can be submitted by attendees with questions or requests, or by staff for record-keeping. "
            "Priority levels (low, medium, high) help staff prioritize responses."
        ),
        tags=['Attendee Messages']
    ),
    update=extend_schema(
        summary="Update Message",
        description=(
            "Update a message, primarily used by staff to add responses or administrative notes. "
            "Can update priority level, response content, and internal staff notes. "
            "Response timestamp is automatically recorded when staff responds."
        ),
        tags=['Attendee Messages']
    ),
    partial_update=extend_schema(
        summary="Partially Update Message",
        description=(
            "Partially update message fields such as priority, response, or admin notes "
            "without providing the complete message payload."
        ),
        tags=['Attendee Messages']
    )
)
class AttendeeMessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeMessage records.
    
    Handles communication between attendees and event staff including:
    - Inquiries and requests from attendees
    - Staff responses and internal notes
    - Priority management for message triage
    - Message threading and history
    """
    
    queryset = AttendeeMessage.objects.select_related('attendee', 'responsed_by').all()
    permission_classes = [CanAccessMessages]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeMessageFilterSet
    ordering_fields = ['submitted_at', 'priority']
    ordering = ['-submitted_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return AttendeeMessageListSerializer
        elif self.action == 'create':
            return AttendeeMessageCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AttendeeMessageUpdateSerializer
        return AttendeeMessageDetailSerializer


# ============================================================================
# ACCESSIBILITY REQUIREMENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Accessibility Requirements",
        description=(
            "Retrieve a list of available accessibility requirement types that can be assigned to attendees. "
            "These represent various accessibility needs such as wheelchair access, sign language interpretation, "
            "visual aids, hearing assistance, and other accommodations. "
            "Each requirement includes verification status for compliance tracking."
        ),
        tags=['Accessibility Requirements']
    ),
    retrieve=extend_schema(
        summary="Get Accessibility Requirement Details",
        description=(
            "Retrieve detailed information about a specific accessibility requirement type including "
            "code, label, description, verification status, and active status."
        ),
        tags=['Accessibility Requirements']
    ),
    create=extend_schema(
        summary="Create Accessibility Requirement",
        description=(
            "Create a new accessibility requirement type for event accessibility planning. "
            "Staff can define custom accessibility accommodations with codes, labels, and descriptions. "
            "Supports verification workflows for compliance."
        ),
        tags=['Accessibility Requirements']
    ),
    update=extend_schema(
        summary="Update Accessibility Requirement",
        description=(
            "Update an accessibility requirement type's details including label, description, "
            "verification status, or active status. Used to maintain the accessibility catalog."
        ),
        tags=['Accessibility Requirements']
    ),
    partial_update=extend_schema(
        summary="Partially Update Accessibility Requirement",
        description="Partially update an accessibility requirement without providing complete payload.",
        tags=['Accessibility Requirements']
    ),
    destroy=extend_schema(
        summary="Delete Accessibility Requirement",
        description="Delete an accessibility requirement type (use with caution if assignments exist).",
        tags=['Accessibility Requirements']
    )
)
class AccessibilityRequirementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AccessibilityRequirement types.
    
    Provides a catalog of accessibility accommodations that can be assigned to attendees.
    Supports compliance tracking through verification status management.
    Read-only for non-staff users.
    """
    
    queryset = AccessibilityRequirement.objects.all()
    serializer_class = AccessibilityRequirementSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AccessibilityRequirementFilterSet
    search_fields = ['code', 'label', 'description']
    ordering_fields = ['label', 'added_at']
    ordering = ['label']


@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Accessibility Requirements",
        description=(
            "Retrieve accessibility requirements assigned to attendees. "
            "Shows which attendees have specific accessibility needs with detailed notes and verification status. "
            "Supports filtering by attendee, requirement type, and verification status for compliance reporting."
        ),
        tags=['Attendee Accessibility']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Accessibility Requirement Details",
        description=(
            "Retrieve detailed information about a specific attendee's accessibility requirement including "
            "the requirement type, specific details, accommodation notes, verification status, and verification history."
        ),
        tags=['Attendee Accessibility']
    ),
    create=extend_schema(
        summary="Assign Accessibility Requirement",
        description=(
            "Assign an accessibility requirement to an attendee with specific details and accommodation notes. "
            "Captures attendee-specific needs beyond the standard requirement definition. "
            "Automatically tracks creation timestamp for audit purposes."
        ),
        tags=['Attendee Accessibility']
    ),
    update=extend_schema(
        summary="Update Accessibility Requirement Assignment",
        description=(
            "Update an attendee's accessibility requirement details, notes, or verification status. "
            "Used to refine accommodation plans or update verification as accommodations are confirmed."
        ),
        tags=['Attendee Accessibility']
    ),
    partial_update=extend_schema(
        summary="Partially Update Accessibility Requirement Assignment",
        description="Partially update accessibility requirement details without providing complete payload.",
        tags=['Attendee Accessibility']
    ),
    destroy=extend_schema(
        summary="Remove Accessibility Requirement",
        description=(
            "Remove an accessibility requirement assignment from an attendee when it is no longer needed. "
            "Does not delete the requirement type, only the assignment to this specific attendee."
        ),
        tags=['Attendee Accessibility']
    )
)
class AttendeeAccessibilityRequirementViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeAccessibilityRequirement assignments.
    
    Handles the association of accessibility requirements with specific attendees,
    including detailed notes, verification status, and accommodation planning.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeAccessibilityRequirement.objects.select_related(
        'attendee', 'accessibility_requirement'
    ).all()
    serializer_class = AttendeeAccessibilityRequirementSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeAccessibilityRequirementFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']


# ============================================================================
# DIETARY REQUIREMENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Dietary Requirements",
        description=(
            "Retrieve a list of available dietary requirement types for event meal planning. "
            "Includes common dietary needs such as vegetarian, vegan, halal, kosher, gluten-free, "
            "lactose-free, nut allergies, and other dietary restrictions. "
            "Each requirement can be assigned to attendees for catering purposes."
        ),
        tags=['Dietary Requirements']
    ),
    retrieve=extend_schema(
        summary="Get Dietary Requirement Details",
        description=(
            "Retrieve detailed information about a specific dietary requirement type including "
            "code, label, description, verification status, and active status."
        ),
        tags=['Dietary Requirements']
    ),
    create=extend_schema(
        summary="Create Dietary Requirement",
        description=(
            "Create a new dietary requirement type for meal planning and catering. "
            "Staff can define custom dietary needs with codes, labels, and descriptions. "
            "Supports verification workflows for dietary compliance."
        ),
        tags=['Dietary Requirements']
    ),
    update=extend_schema(
        summary="Update Dietary Requirement",
        description=(
            "Update a dietary requirement type's details including label, description, "
            "verification status, or active status. Used to maintain the dietary catalog."
        ),
        tags=['Dietary Requirements']
    ),
    partial_update=extend_schema(
        summary="Partially Update Dietary Requirement",
        description="Partially update a dietary requirement without providing complete payload.",
        tags=['Dietary Requirements']
    ),
    destroy=extend_schema(
        summary="Delete Dietary Requirement",
        description="Delete a dietary requirement type (use with caution if assignments exist).",
        tags=['Dietary Requirements']
    )
)
class DietaryRequirementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing DietaryRequirement types.
    
    Provides a catalog of dietary restrictions and preferences for event catering.
    Supports meal planning, allergen management, and dietary compliance.
    Read-only for non-staff users.
    """
    
    queryset = DietaryRequirement.objects.all()
    serializer_class = DietaryRequirementSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DietaryRequirementFilterSet
    search_fields = ['code', 'label', 'description']
    ordering_fields = ['label', 'added_at']
    ordering = ['label']


@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Dietary Requirements",
        description=(
            "Retrieve dietary requirements assigned to attendees for meal planning and catering. "
            "Shows which attendees have specific dietary needs with detailed notes and verification status. "
            "Essential for event catering, allergen management, and dietary compliance."
        ),
        tags=['Attendee Dietary']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Dietary Requirement Details",
        description=(
            "Retrieve detailed information about a specific attendee's dietary requirement including "
            "the requirement type, specific details, preparation notes, verification status, and verification history."
        ),
        tags=['Attendee Dietary']
    ),
    create=extend_schema(
        summary="Assign Dietary Requirement",
        description=(
            "Assign a dietary requirement to an attendee with specific details and preparation notes. "
            "Captures attendee-specific dietary needs, allergies, and restrictions for safe meal preparation. "
            "Automatically tracks creation timestamp for audit purposes."
        ),
        tags=['Attendee Dietary']
    ),
    update=extend_schema(
        summary="Update Dietary Requirement Assignment",
        description=(
            "Update an attendee's dietary requirement details, notes, or verification status. "
            "Used to refine meal plans or update verification as dietary needs are confirmed."
        ),
        tags=['Attendee Dietary']
    ),
    partial_update=extend_schema(
        summary="Partially Update Dietary Requirement Assignment",
        description="Partially update dietary requirement details without providing complete payload.",
        tags=['Attendee Dietary']
    ),
    destroy=extend_schema(
        summary="Remove Dietary Requirement",
        description=(
            "Remove a dietary requirement assignment from an attendee when it is no longer applicable. "
            "Does not delete the requirement type, only the assignment to this specific attendee."
        ),
        tags=['Attendee Dietary']
    )
)
class AttendeeDietaryRequirementViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeDietaryRequirement assignments.
    
    Handles the association of dietary requirements with specific attendees,
    including detailed notes, verification status, and meal planning information.
    Critical for safe event catering and allergen management.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeDietaryRequirement.objects.select_related(
        'attendee', 'dietary_requirement'
    ).all()
    serializer_class = AttendeeDietaryRequirementSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeDietaryRequirementFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']


# ============================================================================
# MEDICAL CONDITION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Medical Conditions",
        description=(
            "Retrieve a list of available medical condition types for attendee health management. "
            "Includes common conditions such as asthma, diabetes, epilepsy, heart conditions, "
            "allergies, and other medical concerns requiring monitoring or emergency response. "
            "Each condition can be assigned to attendees with severity levels (mild, moderate, severe)."
        ),
        tags=['Medical Conditions']
    ),
    retrieve=extend_schema(
        summary="Get Medical Condition Details",
        description=(
            "Retrieve detailed information about a specific medical condition type including "
            "code, label, description, verification status, and active status."
        ),
        tags=['Medical Conditions']
    ),
    create=extend_schema(
        summary="Create Medical Condition",
        description=(
            "Create a new medical condition type for health management and emergency response planning. "
            "Staff can define custom medical conditions with codes, labels, and descriptions. "
            "Supports verification workflows for medical compliance."
        ),
        tags=['Medical Conditions']
    ),
    update=extend_schema(
        summary="Update Medical Condition",
        description=(
            "Update a medical condition type's details including label, description, "
            "verification status, or active status. Used to maintain the medical conditions catalog."
        ),
        tags=['Medical Conditions']
    ),
    partial_update=extend_schema(
        summary="Partially Update Medical Condition",
        description="Partially update a medical condition without providing complete payload.",
        tags=['Medical Conditions']
    ),
    destroy=extend_schema(
        summary="Delete Medical Condition",
        description="Delete a medical condition type (use with caution if assignments exist).",
        tags=['Medical Conditions']
    )
)
class MedicalConditionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing MedicalCondition types.
    
    Provides a catalog of medical conditions for attendee health monitoring.
    Supports emergency response planning and medical compliance tracking.
    Read-only for non-staff users.
    """
    
    queryset = MedicalCondition.objects.all()
    serializer_class = MedicalConditionSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = MedicalConditionFilterSet
    search_fields = ['code', 'label', 'description']
    ordering_fields = ['label', 'added_at']
    ordering = ['label']


@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Medical Conditions",
        description=(
            "Retrieve medical conditions assigned to attendees for health monitoring and emergency response. "
            "Shows which attendees have specific medical conditions with severity levels (mild, moderate, severe), "
            "detailed notes, and verification status. Critical for event safety and medical preparedness."
        ),
        tags=['Attendee Medical']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Medical Condition Details",
        description=(
            "Retrieve detailed information about a specific attendee's medical condition including "
            "the condition type, severity level, specific details, medical notes, verification status, and verification history."
        ),
        tags=['Attendee Medical']
    ),
    create=extend_schema(
        summary="Assign Medical Condition",
        description=(
            "Assign a medical condition to an attendee with severity level and specific medical details. "
            "Captures attendee-specific medical needs for emergency response planning and health monitoring. "
            "Severity levels: mild, moderate, severe. Automatically tracks creation timestamp for audit purposes."
        ),
        tags=['Attendee Medical']
    ),
    update=extend_schema(
        summary="Update Medical Condition Assignment",
        description=(
            "Update an attendee's medical condition details, severity level, notes, or verification status. "
            "Used to refine emergency response plans or update verification as medical information is confirmed."
        ),
        tags=['Attendee Medical']
    ),
    partial_update=extend_schema(
        summary="Partially Update Medical Condition Assignment",
        description="Partially update medical condition details without providing complete payload.",
        tags=['Attendee Medical']
    ),
    destroy=extend_schema(
        summary="Remove Medical Condition",
        description=(
            "Remove a medical condition assignment from an attendee when it is no longer applicable. "
            "Does not delete the condition type, only the assignment to this specific attendee."
        ),
        tags=['Attendee Medical']
    )
)
class AttendeeMedicalConditionViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeMedicalCondition assignments.
    
    Handles the association of medical conditions with specific attendees,
    including severity levels, detailed medical notes, and verification status.
    Critical for event safety, emergency response, and health management.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeMedicalCondition.objects.select_related(
        'attendee', 'medical_condition'
    ).all()
    serializer_class = AttendeeMedicalConditionSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeMedicalConditionFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']


# ============================================================================
# EMERGENCY CONTACT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Emergency Contacts",
        description=(
            "Retrieve a list of emergency contacts for attendees. "
            "Emergency contacts are individuals to be notified in case of medical emergencies, accidents, or urgent situations. "
            "Each attendee can have multiple contacts with one designated as primary. "
            "Essential for event safety and emergency response protocols."
        ),
        tags=['Emergency Contacts']
    ),
    retrieve=extend_schema(
        summary="Get Emergency Contact Details",
        description=(
            "Retrieve detailed information about a specific emergency contact including "
            "name, relationship to attendee, phone numbers, email, and primary contact designation."
        ),
        tags=['Emergency Contacts']
    ),
    create=extend_schema(
        summary="Create Emergency Contact",
        description=(
            "Create a new emergency contact for an attendee. "
            "Requires contact name, relationship, and at least one contact method (phone or email). "
            "Designate as primary contact if this is the first or most important contact for emergencies."
        ),
        tags=['Emergency Contacts']
    ),
    update=extend_schema(
        summary="Update Emergency Contact",
        description=(
            "Update emergency contact information including contact details, relationship, or primary designation. "
            "Ensures attendee emergency information remains current for safety purposes."
        ),
        tags=['Emergency Contacts']
    ),
    partial_update=extend_schema(
        summary="Partially Update Emergency Contact",
        description="Partially update emergency contact details without providing complete payload.",
        tags=['Emergency Contacts']
    ),
    destroy=extend_schema(
        summary="Delete Emergency Contact",
        description=(
            "Remove an emergency contact from an attendee's record. "
            "Use caution when removing primary contacts to ensure attendee always has emergency contact information."
        ),
        tags=['Emergency Contacts']
    )
)
class EmergencyContactViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing EmergencyContact records.
    
    Handles emergency contact information for attendees including multiple contacts per attendee,
    primary contact designation, and comprehensive contact information.
    Critical for event safety and emergency response.
    Supports nested access under attendee resources.
    """
    
    queryset = EmergencyContact.objects.select_related('attendee').all()
    serializer_class = EmergencyContactSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EmergencyContactFilterSet
    search_fields = ['first_name', 'last_name', 'phone_number', 'email']
    ordering_fields = ['added_at', 'primary_contact']
    ordering = ['-primary_contact', '-added_at']


# ============================================================================
# CONSENT VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Consents",
        description=(
            "Retrieve a list of available consent types for events. "
            "Consents are legal agreements or permissions required from attendees such as photo/video release, "
            "medical treatment authorization, liability waivers, code of conduct acknowledgment, "
            "and data processing permissions. Each consent type is associated with a specific event."
        ),
        tags=['Consents']
    ),
    retrieve=extend_schema(
        summary="Get Consent Details",
        description=(
            "Retrieve detailed information about a specific consent type including "
            "code, title, description, associated event, and creation timestamp."
        ),
        tags=['Consents']
    ),
    create=extend_schema(
        summary="Create Consent",
        description=(
            "Create a new consent type for an event. "
            "Define legal agreements or permissions required from attendees with unique codes, titles, and descriptions. "
            "Each consent can then be individually granted or declined by attendees."
        ),
        tags=['Consents']
    ),
    update=extend_schema(
        summary="Update Consent",
        description=(
            "Update a consent type's details including title or description. "
            "Used to maintain consent definitions and legal language for compliance."
        ),
        tags=['Consents']
    ),
    partial_update=extend_schema(
        summary="Partially Update Consent",
        description="Partially update a consent type without providing complete payload.",
        tags=['Consents']
    ),
    destroy=extend_schema(
        summary="Delete Consent",
        description="Delete a consent type (use with caution if attendee consent records exist).",
        tags=['Consents']
    )
)
class ConsentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Consent types.
    
    Provides a catalog of consent types required for event participation.
    Supports legal compliance, liability management, and data protection.
    Read-only for non-staff users.
    """
    
    queryset = Consent.objects.select_related('event').all()
    serializer_class = ConsentSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ConsentFilterSet
    search_fields = ['code', 'title', 'description']
    ordering_fields = ['title', 'created_at']
    ordering = ['title']


@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Consents",
        description=(
            "Retrieve consent records for attendees showing which consents have been granted or declined. "
            "Tracks attendee agreement to event terms, photo releases, liability waivers, and other legal permissions. "
            "Includes consent status (granted/declined), timestamp, and optional consent giver information for minors. "
            "Essential for legal compliance and event liability management."
        ),
        tags=['Attendee Consents']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Consent Details",
        description=(
            "Retrieve detailed information about a specific attendee's consent record including "
            "the consent type, granted status, recording timestamp, when consent was given, and who gave consent (for minors)."
        ),
        tags=['Attendee Consents']
    ),
    create=extend_schema(
        summary="Record Attendee Consent",
        description=(
            "Record a consent grant or decline for an attendee. "
            "Captures whether consent is given, when it was given, and optionally who gave consent (parent/guardian for minors). "
            "Creates an immutable audit trail for legal compliance."
        ),
        tags=['Attendee Consents']
    ),
    update=extend_schema(
        summary="Update Attendee Consent",
        description=(
            "Update an attendee's consent record such as changing consent status or recording withdrawal of consent. "
            "Maintains compliance with data protection regulations and consent management requirements."
        ),
        tags=['Attendee Consents']
    ),
    partial_update=extend_schema(
        summary="Partially Update Attendee Consent",
        description="Partially update consent record details without providing complete payload.",
        tags=['Attendee Consents']
    ),
    destroy=extend_schema(
        summary="Remove Consent Record",
        description=(
            "Remove a consent record from an attendee. "
            "Use with caution as consent records are typically maintained for legal compliance. "
            "Consider marking as declined rather than deleting for audit trail purposes."
        ),
        tags=['Attendee Consents']
    )
)
class AttendeeConsentViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeConsent records.
    
    Handles the recording and management of consent grants/declines for attendees.
    Supports legal compliance, GDPR/data protection, and liability management.
    Maintains audit trail of consent decisions.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeConsent.objects.select_related('attendee', 'consent').all()
    serializer_class = AttendeeConsentSerializer
    permission_classes = [CanManageAttendeePersonalInfo]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeConsentFilterSet
    ordering_fields = ['recorded_at', 'given_at']
    ordering = ['-recorded_at']


# ============================================================================
# EVENT ATTENDANCE VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Event Attendances",
        description=(
            "Retrieve a list of event attendance records tracking attendee check-ins and check-outs. "
            "Shows who attended events, arrival and departure times, and staff who processed check-in/check-out. "
            "Useful for attendance reporting, capacity monitoring, and event analytics. "
            "Supports filtering by event, attendee, and date ranges."
        ),
        tags=['Event Attendance']
    ),
    retrieve=extend_schema(
        summary="Get Attendance Details",
        description=(
            "Retrieve detailed information about a specific attendance record including "
            "event details, attendee information, check-in and check-out timestamps, and processing staff members."
        ),
        tags=['Event Attendance']
    ),
    create=extend_schema(
        summary="Create Attendance Record",
        description=(
            "Create a new attendance record when an attendee arrives at an event. "
            "Records check-in time and staff member who processed the check-in. "
            "Enables real-time event capacity monitoring and attendance tracking."
        ),
        tags=['Event Attendance']
    ),
    update=extend_schema(
        summary="Update Attendance Record",
        description=(
            "Update an attendance record, typically to record check-out when an attendee leaves. "
            "Can also be used to correct check-in times or update processing staff information. "
            "Records check-out timestamp and staff member who processed departure."
        ),
        tags=['Event Attendance']
    ),
    partial_update=extend_schema(
        summary="Partially Update Attendance Record",
        description="Partially update attendance details such as check-out time without providing complete payload.",
        tags=['Event Attendance']
    ),
    destroy=extend_schema(
        summary="Delete Attendance Record",
        description="Delete an attendance record (use with caution as this affects attendance history).",
        tags=['Event Attendance']
    )
)
class EventAttendanceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing EventAttendance records.
    
    Tracks attendee presence at events with check-in and check-out functionality.
    Supports real-time attendance monitoring, capacity management, and event analytics.
    Records staff responsible for processing attendance for audit purposes.
    """
    
    queryset = EventAttendance.objects.select_related('event', 'attendee', 'check_in_by', 'check_out_by').all()
    serializer_class = EventAttendanceSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventAttendanceFilterSet
    ordering_fields = ['check_in_time', 'check_out_time']
    ordering = ['-check_in_time']


# ============================================================================
# ATTENDEE ORGANISATION VIEWSETS
# ============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="List Attendee Organisations",
        description=(
            "Retrieve organisation associations for attendees showing which organisations attendees belong to or represent. "
            "Useful for tracking institutional affiliations, group registrations, and organisational analytics. "
            "Supports filtering by organisation, attendee, or association date."
        ),
        tags=['Attendee Organisations']
    ),
    retrieve=extend_schema(
        summary="Get Attendee Organisation Details",
        description=(
            "Retrieve detailed information about a specific organisation association including "
            "the attendee, organisation details, association timestamp, and any additional context."
        ),
        tags=['Attendee Organisations']
    ),
    create=extend_schema(
        summary="Link Attendee to Organisation",
        description=(
            "Create a new association between an attendee and an organisation. "
            "Links attendees to institutions, companies, parishes, or other organisational entities they represent. "
            "Enables organisational reporting and group management."
        ),
        tags=['Attendee Organisations']
    ),
    destroy=extend_schema(
        summary="Unlink Attendee from Organisation",
        description=(
            "Remove an organisation association from an attendee when the affiliation is no longer valid. "
            "Does not delete the attendee or organisation records, only the association between them."
        ),
        tags=['Attendee Organisations']
    )
)
class AttendeeOrganisationViewSet(NestedAttendeeViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing AttendeeOrganisation associations.
    
    Handles the many-to-many relationship between attendees and organisations.
    Supports institutional affiliations, group registrations, and organisational analytics.
    No update operation - associations are either created or deleted.
    Supports nested access under attendee resources.
    """
    
    queryset = AttendeeOrganisation.objects.select_related('attendee', 'organisation').all()
    serializer_class = AttendeeOrganisationSerializer
    permission_classes = [IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AttendeeOrganisationFilterSet
    ordering_fields = ['added_at']
    ordering = ['-added_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']  # No update
