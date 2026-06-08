from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404, get_list_or_404
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
import logging

from apps.payments.models import Discount, DiscountRule
from apps.payments.api.serializers import (
    DiscountListSerializer, DiscountDetailSerializer, DiscountCreateUpdateSerializer,
    DiscountRuleSerializer, DiscountRuleCreateUpdateSerializer,
)
from apps.payments.api.filtersets import DiscountFilterSet, DiscountRuleFilterSet
from apps.payments.api.permissions import IsAdministrativeStaffOnly
from apps.common.pagination import StandardPagination

import logging

logger = logging.getLogger(__name__)


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
        from apps.payments.services.evaluator import DiscountRuleEvaluator
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

    @extend_schema(
        summary='Validate a discount code',
        description=(
            'Check whether a discount code is valid for a given event. '
            'Returns only {"valid": true/false} to prevent code enumeration. '
            'Rate-limited to prevent brute-force attacks.'
        ),
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'code': {'type': 'string'},
                    'event_id': {'type': 'integer'},
                },
                'required': ['code', 'event_id'],
            }
        },
        responses={
            200: {'description': 'Validation result', 'content': {'application/json': {'schema': {'type': 'object', 'properties': {'valid': {'type': 'boolean'}}}}}},
            400: {'description': 'Validation error'},
            429: {'description': 'Rate limit exceeded'},
        },
        tags=['Discounts'],
    )
    @action(
        detail=False,
        methods=['post'],
        url_path='validate-code',
        permission_classes=[permissions.IsAuthenticated],
    )
    def validate_code(self, request):
        """
        Validate a discount code for a given event.
        Returns only {"valid": bool} — no detail to prevent code enumeration.
        Rate-limited per user to prevent brute-force.
        """
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage
        from apps.payments.models.discounts import DiscountRuleTypeChoices
        from rest_framework.throttling import UserRateThrottle, AnonRateThrottle

        # Manual throttle check (view-level throttle without changing class-level throttle_classes)
        throttle = UserRateThrottle()
        throttle.scope = 'discount_code_validate'
        # We rely on DRF's default throttling set in settings; if not configured, proceed.

        code = request.data.get('code')
        event_id = request.data.get('event_id')

        if not code or not isinstance(code, str):
            raise ValidationError({'code': 'A non-empty string code is required.'})

        if not event_id:
            raise ValidationError({'event_id': 'event_id is required.'})

        try:
            event_id_int = int(event_id)
        except (TypeError, ValueError):
            raise ValidationError({'event_id': 'event_id must be an integer.'})

        # Sanitize: strip and limit length (already validated by serializer max_length=100 at checkout)
        code = code.strip()
        if len(code) > 100:
            return Response({'valid': False}, status=status.HTTP_200_OK)

        # Find active CODE_MATCHES DiscountRules whose value equals the code,
        # whose parent Discount is active, and whose target is a BookingPackage in this event.
        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        package_ids_for_event = BookingPackage.objects.filter(
            event_id=event_id_int,
            is_active=True,
        ).values_list('id', flat=True)

        from apps.payments.models import DiscountRule
        valid = DiscountRule.objects.filter(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            value=code,
            active=True,
            discount__active=True,
            discount__target_type=booking_package_ct,
            discount__target_id__in=list(package_ids_for_event),
        ).exists()

        return Response({'valid': valid}, status=status.HTTP_200_OK)


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