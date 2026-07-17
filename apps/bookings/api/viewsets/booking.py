import json
import uuid
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
import typing
from djmoney.money import Money
from decimal import Decimal

from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.request import Request

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User

from apps.products.models import Order
from apps.payments.models import BankTransferEvidence, Payment, PaymentStatusChoices, PaymentMethodTypeChoices, PaymentMethod

from apps.attendee.models import Attendee, AttendeeRelationship
from apps.common.models import Resource, ResourceTypeChoices
from apps.bookings.models.ticket import Ticket

from apps.bookings.models import (
    Booking, BookingIntent, BookingIntentStatusChoices,Ticket,EventAlternativeSigninIdentifier,
)
from apps.events.models import Event

from apps.bookings.api.serializers import (
    BookingListSerializer, BookingDetailSerializer, BookingCreateSerializer, BookingUpdateSerializer,
    TicketListSerializer, 
    EventAlternativeSigninListSerializer,
    CheckoutSerializer, CheckoutPreviewSerializer, BookingAttendeePrecheckSerializer,
)
from apps.bookings.api.filtersets import BookingFilterSet
from apps.bookings.api.permissions import IsBookingOwnerOrAdministrative
from apps.attendee.api.serializers import AttendeeListSerializer

from apps.bookings.services import BookingCheckoutFinaliser
from apps.payments.services.stripe.payment_intents import PaymentIntentService
from apps.bookings.api.pagination import StandardPagination

from apps.payments.models import DiscountType, BankTransferEvidence
from apps.payments.mixins import PaymentMixin

from apps.payments.services.evaluator import discount_applies

from apps.events.services.notifications import create_notification, NotificationTypeChoices, NotificationPriorityChoices
from apps.bookings.services import AttendeePrecheckValidationService

import logging
logger = logging.getLogger(__name__)

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
        parameters=[
            OpenApiParameter(
                name='Idempotency-Key',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                description='Optional idempotency key to make checkout retries safe'
            )
        ],
        tags=["Bookings"],
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
    
    def perform_create(self, serializer: BookingCreateSerializer):
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
    def attendees(self, request: Request, pk: typing.Optional[int] = None):
        """Return all attendees for this booking."""
        booking = self.get_object()
        
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
    def tickets(self, request: Request, pk: typing.Optional[int] = None):
        """Return all tickets for all attendees in this booking."""
        booking = self.get_object()
        
        # Get all tickets through attendees
        tickets = Ticket.objects.filter(
            attendee__booking=booking
        ).select_related('attendee', 'ticket_type', 'package', 'payment')
        
        serializer = TicketListSerializer(tickets, many=True, context={'request': request, 'event': booking.event})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Precheck attendees before checkout",
        description=(
            "Validate attendee payload for duplicate detection, self re-registration guard, "
            "and event registration limits before calling checkout."
        ),
        tags=["Bookings"],
        request={'application/json': BookingAttendeePrecheckSerializer},
        responses={
            200: OpenApiResponse(description="Precheck passed"),
            400: OpenApiResponse(description="Precheck validation failed"),
        },
        operation_id="bookings_attendee_precheck",
    )
    @action(detail=False, methods=['post'], url_path='attendee-precheck')
    def attendee_precheck(self, request: Request):
        """Validate attendee constraints before checkout submission."""

        serializer = BookingAttendeePrecheckSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        intent = serializer.validated_data['_intent']
        attendee_selections = serializer.validated_data['attendees']
        precheck_result = AttendeePrecheckValidationService.validate(
            event=intent.event,
            user=request.user,
            attendee_selections=attendee_selections,
        )

        response_status = status.HTTP_200_OK if precheck_result['valid'] else status.HTTP_400_BAD_REQUEST
        return Response(precheck_result, status=response_status)

    @extend_schema(
        summary="List checkout alternative sign-in definitions",
        description=(
            "Return active event alternative sign-in definitions for a booking intent. "
            "Authenticated users can access definitions for their own intent. "
            "Administrative users can access any intent."
        ),
        tags=["Bookings"],
        parameters=[
            OpenApiParameter(
                name='booking_intent_id',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=True,
                description='Booking intent UUID used to scope event alternative sign-in definitions',
            )
        ],
        responses={
            200: EventAlternativeSigninListSerializer(many=True),
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Permission denied'),
        },
        operation_id="bookings_checkout_alternative_signins",
    )
    @action(detail=False, methods=['get'], url_path='checkout-alternative-signins')
    def checkout_alternative_signins(self, request: Request):
        """List active event alternative sign-in definitions for checkout."""
        booking_intent_id = request.query_params.get('booking_intent_id')
        if not booking_intent_id:
            raise ValidationError({
                'booking_intent_id': 'booking_intent_id is required.'
            })

        try:
            intent = BookingIntent.objects.select_related('event').get(
                booking_intent_id=booking_intent_id
            )
        except BookingIntent.DoesNotExist:
            raise ValidationError({
                'booking_intent_id': f'BookingIntent with id {booking_intent_id} does not exist.'
            })

        user = request.user
        if not (user.is_staff or user.is_superuser):
            if not intent.made_by_id or intent.made_by_id != user.id:
                raise PermissionDenied('You do not have permission to access this booking intent.')

        queryset = EventAlternativeSigninIdentifier.objects.filter(
            event=intent.event,
            is_active=True,
        ).select_related('event').order_by('title')

        serializer = EventAlternativeSigninListSerializer(
            queryset,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

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
    @action(
        detail=False,
        methods=['post'],
        url_path='checkout',
        parser_classes=[JSONParser, FormParser, MultiPartParser]
    )
    def checkout(self, request: Request):
        """
        Complete booking checkout with payment.
        
        This is the unified checkout endpoint that handles the complete registration flow.
        All operations are atomic - if any step fails, everything rolls back.
        """
        
        # Validate input data
        serializer = CheckoutSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        # Extract validated data
        intent = serializer.validated_data['_intent']
        payment_method = serializer.validated_data['_payment_method']
        attendee_selections = serializer.validated_data['attendees']
        stripe_payment_intent_id = serializer.validated_data.get('_stripe_payment_intent_id')
        bank_transfer_evidence_obj = serializer.validated_data.get('_bank_transfer_evidence_obj')
        discount_code = serializer.validated_data.get('discount_code') or None
        user = request.user
        idempotency_key = request.headers.get('Idempotency-Key') or request.META.get('HTTP_IDEMPOTENCY_KEY')
        
        def serialize_checkout_attendees(selections: typing.List[typing.Dict[str, typing.Any]]) -> typing.List[typing.Dict[str, typing.Any]]:
            """
            Serialize attendee selections for checkout.
            """
            serialized = []
            for selection in selections:
                attendee = selection.get('_attendee')
                draft = selection.get('_attendee_draft') or {}
                package = selection['_package']

                product_rows = []
                for prod_selection in selection.get('product_selections', []):
                    package_product = prod_selection['_package_product']
                    variant = prod_selection['_variant']
                    product_rows.append({
                        'package_product_id': package_product.id,
                        'variant_id': str(variant.variant_id),
                        'product_id': str(variant.product.product_id),
                        'quantity': int(prod_selection['quantity']),
                    })

                question_answers = []
                for answer in draft.get('question_answers', []) or []:
                    answer_row = {
                        'question_id': str(answer.get('question_id')) if answer.get('question_id') else None,
                        'answer_text': answer.get('answer_text'),
                        'selected_option_ids': answer.get('selected_option_ids') or [],
                        'upload_resource_id': answer.get('upload_resource_id'),
                        'upload_url': answer.get('upload_url'),
                    }
                    # Keep metadata payload JSON-safe and avoid persisting multipart mapping internals.
                    question_answers.append(answer_row)

                draft_payload = {
                    **draft,
                    'question_answers': question_answers,
                }

                serialized.append({
                    'attendee_id': str(attendee.attendee_id) if attendee else None,
                    'attendee_draft': (
                        json.loads(json.dumps(draft_payload, cls=DjangoJSONEncoder))
                        if not attendee else None
                    ),
                    'package_id': package.id,
                    'product_selections': product_rows,
                })
            return serialized

        def materialize_multipart_question_uploads(selections: list, event: Event, actor: User) -> None:
            '''
            Materialize any multipart question uploads into Resource objects and attach their IDs and URLs to the attendee draft answers.
            Args:
                selections (list): List of attendee selections with potential multipart uploads.
                event (Event): The event for which the booking is being made.
                actor (User): The user performing the checkout action.
            '''
            content_type = ContentType.objects.get_for_model(event.__class__)

            for selection in selections:
                draft = selection.get('_attendee_draft') or {}
                answers = draft.get('question_answers', []) or []
                for answer in answers:
                    upload_file = answer.pop('_upload_file', None)
                    answer.pop('upload_file_key', None)
                    if not upload_file:
                        continue

                    content_type_value = str(getattr(upload_file, 'content_type', '') or '').lower()
                    is_image = content_type_value.startswith('image/')

                    resource_kwargs = {
                        'name': getattr(upload_file, 'name', 'question-upload'),
                        'resource_type': ResourceTypeChoices.IMAGE if is_image else ResourceTypeChoices.DOCUMENT,
                        'target_type': content_type,
                        'target_id': event.id,
                        'added_by': actor,
                        'public': False,
                        'tag': 'QUESTION_UPLOAD',
                    }

                    if is_image:
                        resource_kwargs['image'] = upload_file
                    else:
                        resource_kwargs['file'] = upload_file

                    resource = Resource.objects.create(**resource_kwargs)
                    answer['upload_resource_id'] = resource.id
                    answer['upload_url'] = resource.resource_url
                    if not answer.get('answer_text'):
                        answer['answer_text'] = resource.resource_url or ''

        def calculate_total_and_validate(
            intent_obj: BookingIntent, 
            selections: typing.List[typing.Dict[str, typing.Any]], 
            code: typing.Optional[str] = None
            ) -> typing.Tuple[Money, typing.List[typing.Dict[str, typing.Any]]]:
            '''
            Calculate the total amount for the booking and validate attendee selections.
            Args:
                intent_obj: The BookingIntent object associated with the checkout.
                selections: List of attendee selections including packages and product selections.
                code: Optional discount code to apply.
            Returns:
                total_amount (Money): The total amount for the booking after discounts.
                applied_discounts_snapshot (list): A snapshot of applied discounts for each attendee.
            '''
            total_amount = Money(0, 'GBP')
            applied_discounts_snapshot = []
            preview_savepoint = transaction.savepoint()

            try:
                for attendee_index, selection in enumerate(selections):
                    package = selection['_package']
                    product_selections = selection.get('product_selections', [])

                    attendee = selection.get('_attendee')
                    if not attendee:
                        draft = selection.get('_attendee_draft') or {}
                        relationship = draft.get('relationship_to_user')
                        attendee_user = user if relationship == AttendeeRelationship.SELF else None
                        attendee = Attendee.objects.create(
                            event=intent_obj.event,
                            user=attendee_user,
                            defined_by=user,
                            first_name=draft.get('first_name'),
                            last_name=draft.get('last_name'),
                            email=draft.get('email') or None,
                            phone_number=draft.get('phone_number') or None,
                            date_of_birth=draft.get('date_of_birth'),
                            gender=draft.get('gender') or None,
                            relationship_to_user=relationship,
                            area_from_id=draft.get('area_from'),
                        )

                    if not package.can_use_package(user, attendee):
                        raise ValidationError({
                            'package_id': (
                                f'Attendee {attendee.attendee_id} is not eligible for package {package.name}.'
                            )
                        })

                    attendee_context = attendee.pricing_context(code=code)
                    package_base = package.modified_amount

                    # Collect discount breakdown for this attendee's package
                    attendee_discount_breakdown = []
                    percentage_total = Decimal('0.00')
                    fixed_total = Money(0, package_base.currency)
                    for d in package.discounts:
                        if not discount_applies(d, attendee_context):
                            continue
                        if d.discount_type == DiscountType.PERCENTAGE:
                            discount_amount = package_base * (d.percentage / Decimal('100'))
                            percentage_total += d.percentage
                            value = str(d.percentage)
                        else:
                            discount_amount = d.amount
                            fixed_total += d.amount
                            value = str(d.amount.amount)
                        attendee_discount_breakdown.append({
                            'discount_id': str(d.discount_id),
                            'name': d.name,
                            'discount_type': d.discount_type,
                            'value': value,
                            'amount': str(discount_amount.amount),
                            'currency': package_base.currency.code,
                        })

                    package_price = package.total_amount_for_context(attendee_context)
                    total_amount += package_price

                    applied_discounts_snapshot.append({
                        'attendee_index': attendee_index,
                        'attendee_id': str(attendee.attendee_id),
                        'attendee_name': attendee.full_name,
                        'package_id': package.id,
                        'package_name': package.name,
                        'discount_breakdown': attendee_discount_breakdown,
                        'total_discount': str(
                            min(
                                package_base * (percentage_total / Decimal('100')) + fixed_total,
                                package_base,
                            ).amount.quantize(Decimal('0.01'))
                        ),
                    })

                    if product_selections:
                        for prod_selection in product_selections:
                            package_product = prod_selection['_package_product']
                            variant = prod_selection['_variant']
                            quantity = int(prod_selection['quantity'])

                            if package_product.booking_package_id != package.id:
                                raise ValidationError({
                                    'product_selections': (
                                        f'Package product {package_product.id} does not belong to package {package.id}.'
                                    )
                                })

                            if not variant.can_attendee_purchase(attendee):
                                raise ValidationError({
                                    'product_selections': (
                                        f'Attendee {attendee.attendee_id} is not eligible for selected variant {variant.variant_id}.'
                                    )
                                })

                            try:
                                variant.can_attendee_purchase_quantity(attendee, quantity, raise_exception=True)
                            except Exception as exc:
                                raise ValidationError({'product_selections': str(exc)})

                            line_total = package_product.total_amount_with_variant(
                                variant=variant,
                                context=attendee_context,
                            ) * quantity
                            total_amount += line_total
            finally:
                transaction.savepoint_rollback(preview_savepoint)

            return total_amount, applied_discounts_snapshot

        def build_response(
                payment_obj: 'Payment', 
                status_label: str, 
                message: str , 
                booking: typing.Optional['Booking'] = None, 
                stripe_client_secret: typing.Optional[str] = None, 
                bank_transfer_evidence: typing.Optional['BankTransferEvidence'] =None
                ) -> typing.Dict[str, typing.Any]:
            '''
            Build a structured response for the checkout endpoint.
            Args:
                payment_obj: The Payment object associated with the checkout.
                status_label: A string indicating the status of the checkout (e.g., 'confirmed', 'pending_payment').
                message: A human-readable message describing the checkout result.
                booking: Optional Booking object if a booking was created.
                stripe_client_secret: Optional client secret for Stripe payments.
                bank_transfer_evidence: Optional BankTransferEvidence object if applicable.
            Returns:
                A dictionary containing the checkout response data.
            '''

            response_data = {
                'booking_id': str(booking.id) if booking else None,
                'booking_reference': booking.booking_reference if booking else None,
                'payment_id': payment_obj.payment_id,
                'payment_reference': payment_obj.payment_reference,
                'total_amount': str(payment_obj.base_amount.amount if payment_obj.base_amount else Decimal('0.00')),
                'currency': payment_obj.base_amount.currency.code if payment_obj.base_amount else 'GBP',
                'status': status_label,
                'message': message,
                'orders': [],
                'stripe_client_secret': stripe_client_secret,
                'bank_transfer_evidence_id': str(bank_transfer_evidence.bank_transfer_id) if bank_transfer_evidence else None,
                'bank_transfer_reference': payment_obj.bank_transfer_reference if payment_obj.method and payment_obj.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER else None,
                'bank_transfer_instructions': None,
                '_links': {},
            }

            if response_data['bank_transfer_reference']:
                response_data['bank_transfer_instructions'] = (
                    f"Please transfer {payment_obj.base_amount} to our bank account with "
                    f"reference: {payment_obj.bank_transfer_reference}. "
                    "Your booking will be finalized after payment verification."
                )

            if booking:
                orders = Order.objects.filter(attendee__booking=booking)
                response_data['orders'] = [
                    {
                        'order_id': str(order.order_id),
                        'order_reference': order.order_reference_id,
                        'attendee_id': str(order.attendee.attendee_id) if order.attendee else None,
                        'total_amount': str(order.total_amount.amount),
                        '_links': {
                            'self': request.build_absolute_uri(f'/api/products/orders/{order.order_id}/'),
                        }
                    }
                    for order in orders
                ]
                response_data['_links'] = {
                    'self': request.build_absolute_uri(f'/api/bookings/list/{booking.id}/'),
                    'attendees': request.build_absolute_uri(f'/api/bookings/list/{booking.id}/attendees/'),
                    'tickets': request.build_absolute_uri(f'/api/bookings/list/{booking.id}/tickets/'),
                }

                tickets = Ticket.objects.filter(attendee__booking=booking)
                if tickets.exists():
                    response_data['tickets'] = [
                        {
                            'ticket_id': str(ticket.ticket_id),
                            'ticket_code': ticket.ticket_code,
                            'attendee_name': ticket.attendee.full_name if ticket.attendee else None,
                            '_links': {
                                'self': request.build_absolute_uri(f'/api/bookings/tickets/{ticket.ticket_id}/'),
                            }
                        }
                        for ticket in tickets
                    ]

            return response_data
        
        try:
            with transaction.atomic():
                # Lock the intent to prevent race conditions
                intent = BookingIntent.objects.select_for_update().get(
                    booking_intent_id=intent.booking_intent_id
                )

                if idempotency_key and intent.last_checkout_idempotency_key == idempotency_key:
                    existing_payment = Payment.objects.filter(
                        user=user,
                        event=intent.event,
                        metadata__checkout_intent_id=str(intent.booking_intent_id),
                        metadata__checkout_idempotency_key=idempotency_key,
                    ).order_by('-id').first()
                    if existing_payment:
                        existing_booking = existing_payment.target if isinstance(existing_payment.target, Booking) else None
                        stripe_client_secret = None

                        # For Stripe pending payments, re-hydrate client secret so frontend
                        # can continue confirmation on idempotent retries.
                        if (
                            existing_payment.method
                            and existing_payment.method.method_type == PaymentMethodTypeChoices.STRIPE
                            and existing_payment.status != PaymentStatusChoices.COMPLETED
                            and existing_payment.stripe_payment_intent
                        ):
                            stripe_account_id = (
                                existing_payment.method.get_stripe_account_id()
                                if hasattr(existing_payment.method, 'get_stripe_account_id')
                                else None
                            )
                            try:
                                existing_payment_intent = PaymentIntentService.retrieve(
                                    existing_payment.stripe_payment_intent,
                                    stripe_account_id=stripe_account_id,
                                )
                                stripe_client_secret = getattr(existing_payment_intent, 'client_secret', None)
                            except Exception:
                                stripe_client_secret = None

                        response_data = build_response(
                            existing_payment,
                            'confirmed' if existing_booking else 'pending_payment',
                            'Returning previously initiated checkout session.',
                            booking=existing_booking,
                            stripe_client_secret=stripe_client_secret,
                        )
                        return Response(response_data, status=status.HTTP_200_OK)
                
                # Extend intent expiry during checkout
                intent.expires_at = timezone.now() + timezone.timedelta(minutes=30)
                intent.save(update_fields=['expires_at'])
                
                # Revalidate intent is still active
                if not intent.is_active or not intent.can_create_booking():
                    raise ValidationError({
                        'booking_intent_id': 'Booking intent is no longer valid for checkout.'
                    })

                materialize_multipart_question_uploads(attendee_selections, intent.event, user)

                total_amount, applied_discounts_snapshot = calculate_total_and_validate(
                    intent, attendee_selections, code=discount_code
                )

                payment_metadata = {
                    'checkout_intent_id': str(intent.booking_intent_id),
                    'checkout_idempotency_key': idempotency_key,
                    'checkout_attendees': serialize_checkout_attendees(attendee_selections),
                    'payment_type': 'booking_checkout_pending_finalization',
                    'total_attendees': len(attendee_selections),
                    'booking_finalized': False,
                    'discount_code': discount_code,
                    'applied_discounts_snapshot': applied_discounts_snapshot,
                }

                reserved_payment = serializer.validated_data.get('_payment_obj')
                if (
                    not reserved_payment
                    and payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER
                ):
                    # Fallback for clients that reserved a bank transfer reference but did not
                    # send payment_id during checkout; reuse the latest draft reservation.
                    reserved_payment = Payment.objects.select_for_update().filter(
                        user=user,
                        event=intent.event,
                        method=payment_method,
                        status=PaymentStatusChoices.DRAFTING,
                        metadata__contains={
                            'checkout_intent_id': str(intent.booking_intent_id),
                            'payment_type': 'booking_checkout_reservation',
                        },
                    ).order_by('-created_at').first()

                if total_amount.amount == 0:
                    payment = Payment.objects.create( # TODO: create better descriptions for checkout
                        user=user,
                        event=intent.event,
                        method=payment_method,
                        base_amount=total_amount,
                        original_amount=total_amount,
                        percentage_modifier=Decimal('0.00'),
                        description=f"Checkout intent {intent.booking_intent_id} - {intent.event.title} (free)",
                        status=PaymentStatusChoices.COMPLETED,
                        metadata=payment_metadata,
                    )

                    if idempotency_key:
                        intent.last_checkout_idempotency_key = idempotency_key
                        intent.save(update_fields=['last_checkout_idempotency_key'])

                    finalization = BookingCheckoutFinaliser.finalize_for_stripe(payment, actor=user)
                    booking = finalization['booking']
                    response_data = build_response(
                        payment,
                        'confirmed',
                        'Registration completed. No payment required.',
                        booking=booking,
                    )
                    return Response(response_data, status=status.HTTP_201_CREATED)

                if not payment_method:
                    raise ValidationError({
                        'payment_method_id': 'Payment method is required when total amount is greater than 0.'
                    })
                
                description = "Booking payment from user '%s' for event '%s' for attendees [%s] (intent reference: %s...)" % (
                        user.username,
                        intent.event.title,
                        ",".join([
                            (attendee.get("attendee_draft") or {}).get("first_name")
                            or attendee.get("attendee_id")
                            or "unknown"
                            for attendee in payment_metadata['checkout_attendees']
                        ]),
                        str(intent.booking_intent_id)[:8],
                    )

                if reserved_payment:
                    payment = reserved_payment
                    payment.method = payment_method
                    payment.base_amount = total_amount
                    payment.original_amount = total_amount
                    payment.percentage_modifier = Decimal('0.00')
                    # payment.description = f"Checkout intent {intent.booking_intent_id} - {intent.event.title}"
                    payment.description = description

                    payment.status = PaymentStatusChoices.DRAFTING
                    payment.metadata = {**(payment.metadata or {}), **payment_metadata}
                    payment.save()
                    payment.transition_to(PaymentStatusChoices.PENDING)
                else:
                    
                    payment = Payment.objects.create(
                        user=user,
                        event=intent.event,
                        method=payment_method,
                        base_amount=total_amount,
                        original_amount=total_amount,
                        percentage_modifier=Decimal('0.00'),
                        description=description,
                        status=PaymentStatusChoices.PENDING,
                        metadata=payment_metadata,
                    )

                bank_transfer_evidence = None
                if payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER and bank_transfer_evidence_obj:
                    metadata = dict(bank_transfer_evidence_obj.metadata or {})
                    if bank_transfer_evidence_obj.payment_id and bank_transfer_evidence_obj.payment_id != payment.id:
                        raise ValidationError({'bank_transfer_evidence_id': 'Evidence has already been consumed by another payment.'})

                    bank_transfer_evidence_obj.payment = payment
                    bank_transfer_evidence_obj.transfer_id = payment.bank_transfer_reference
                    metadata['consumed'] = True
                    metadata['consumed_at'] = timezone.now().isoformat()
                    metadata['consumed_by_payment_id'] = str(payment.payment_id)
                    bank_transfer_evidence_obj.metadata = metadata
                    bank_transfer_evidence_obj.save(update_fields=['payment', 'transfer_id', 'metadata', 'updated_at'])
                    bank_transfer_evidence = bank_transfer_evidence_obj

                if idempotency_key:
                    intent.last_checkout_idempotency_key = idempotency_key
                    intent.save(update_fields=['last_checkout_idempotency_key'])

                logger.info(
                    f"Initiated checkout payment {payment.payment_reference} for intent {intent.booking_intent_id}, "
                    f"amount: {payment.base_amount}"
                )

                # Pre-create booking/attendees only for bank transfer flows, where the
                # payment is never confirmed server-side in real time and the user needs
                # a booking reference immediately to complete the manual transfer.
                #
                # For Stripe, we intentionally do NOT pre-create objects here. All booking
                # artifacts (Booking, Attendees, Tickets) are created atomically by
                # BookingCheckoutFinaliser inside _process_completed_payment() after Stripe
                # confirms the payment via webhook. This guarantees that if the card is
                # declined or the user abandons the Stripe confirmation step, no orphaned
                # records are left behind.
                prefinalized_booking = None
                if (
                    payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER
                    and not stripe_payment_intent_id
                ):
                    prefinalization = BookingCheckoutFinaliser.finalize_for_bank_transfer(payment, actor=user)
                    prefinalized_booking = prefinalization.get('booking')

                if payment_method.method_type == PaymentMethodTypeChoices.STRIPE:
                    stripe_account_id = None
                    if payment.method and hasattr(payment.method, 'get_stripe_account_id'):
                        stripe_account_id = payment.method.get_stripe_account_id()

                    if stripe_payment_intent_id:
                        try:
                            payment_intent = PaymentIntentService.retrieve(
                                stripe_payment_intent_id,
                                stripe_account_id=stripe_account_id,
                            )
                        except Exception as e:
                            raise ValidationError({
                                'stripe_payment_intent_id': f'Unable to retrieve Stripe payment intent: {str(e)}'
                            })

                        amount_in_cents = int(total_amount.amount * 100)
                        if payment_intent.amount != amount_in_cents:
                            raise ValidationError({
                                'stripe_payment_intent_id': 'Stripe payment amount does not match checkout total.'
                            })

                        if payment_intent.currency.lower() != total_amount.currency.code.lower():
                            raise ValidationError({
                                'stripe_payment_intent_id': 'Stripe payment currency does not match checkout currency.'
                            })

                        if payment_intent.status != 'succeeded':
                            raise ValidationError({
                                'stripe_payment_intent_id': 'Stripe payment intent is not succeeded.'
                            })

                        payment.stripe_payment_intent = payment_intent.id
                        payment.transition_to(PaymentStatusChoices.COMPLETED)
                        payment.save(update_fields=['stripe_payment_intent', 'updated_at'])

                        finalization = BookingCheckoutFinaliser.finalize_from_payment(payment, actor=user)
                        booking = finalization['booking']

                        response_data = build_response(
                            payment,
                            'confirmed',
                            'Payment confirmed and booking finalized.',
                            booking=booking,
                        )
                        return Response(response_data, status=status.HTTP_201_CREATED)
                    else:
                        logger.warning(
                            f"Checkout initiated with Stripe payment method but no Stripe PaymentIntent ID provided for payment {payment.payment_reference} and intent {intent.booking_intent_id}."
                        )

                    try:
                        stripe_metadata = payment.prepare_stripe_metadata()
                        stripe_metadata['checkout_intent_id'] = str(intent.booking_intent_id)
                        payment_intent = PaymentIntentService.create(
                            amount=payment.base_amount,
                            currency=payment.base_amount.currency.code,
                            payment_reference=payment.payment_reference,
                            metadata=stripe_metadata,
                            customer_email=user.email,
                            description=payment.description,
                            stripe_account_id=stripe_account_id,
                        )

                        payment.stripe_payment_intent = payment_intent.id
                        payment.save(update_fields=['stripe_payment_intent', 'updated_at'])

                        response_data = build_response(
                            payment,
                            'pending_payment',
                            'Checkout initiated. Complete payment with Stripe to finalize booking.',
                            booking=prefinalized_booking,
                            stripe_client_secret=payment_intent.client_secret,
                        )
                        return Response(response_data, status=status.HTTP_201_CREATED)
                    except Exception as e:
                        logger.error(
                            f"Failed to create Stripe PaymentIntent for payment {payment.payment_reference}: {str(e)}",
                            exc_info=True,
                        )
                        raise ValidationError({'payment': f'Failed to initialize Stripe payment: {str(e)}'})

                if payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
                    response_data = build_response(
                        payment,
                        'pending_verification',
                        'Checkout initiated. Complete bank transfer to finalize booking.',
                        booking=prefinalized_booking,
                        bank_transfer_evidence=bank_transfer_evidence,
                    )

                    create_notification(
                        event=intent.event,
                        notification_type=NotificationTypeChoices.BOOKING_CONFIRMATION,
                        priority=NotificationPriorityChoices.HIGH,
                        payment=payment,
                        booking=prefinalized_booking,
                        metadata={
                            'message': f'New bank transfer payment pending verification for booking intent {intent.booking_intent_id}.',
                            'payment_id': str(payment.payment_id),
                            'booking_intent_id': str(intent.booking_intent_id),
                        },
                    )


                    return Response(response_data, status=status.HTTP_201_CREATED)

                if payment_method.method_type == PaymentMethodTypeChoices.CASH:
                    payment.transition_to(PaymentStatusChoices.COMPLETED)
                    finalization = BookingCheckoutFinaliser.finalize_from_payment(payment, actor=user)
                    booking = finalization['booking']
                    response_data = build_response(
                        payment,
                        'confirmed',
                        'Booking finalized. Pay cash on arrival.',
                        booking=booking,
                    )
                    return Response(response_data, status=status.HTTP_201_CREATED)

                raise ValidationError({'payment_method_id': 'Unsupported payment method for checkout.'})
        
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

    @extend_schema(
        summary="Reserve bank transfer reference",
        description=(
            "Create or reuse a draft bank transfer payment for an active booking intent so the customer can see the reference before checkout."
        ),
        tags=["Bookings"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'booking_intent_id': {'type': 'string', 'format': 'uuid'},
                    'payment_method_id': {'type': 'integer'},
                },
                'required': ['booking_intent_id', 'payment_method_id'],
            }
        },
        responses={
            201: OpenApiResponse(description='Draft bank transfer payment reserved.'),
            400: OpenApiResponse(description='Validation error.'),
        },
        operation_id="bookings_reserve_bank_transfer_payment",
    )
    @action(detail=False, methods=['post'], url_path='reserve-bank-transfer-payment')
    def reserve_bank_transfer_payment(self, request: Request) -> Response:
        user = request.user
        intent_id = request.data.get('booking_intent_id')
        payment_method_id = request.data.get('payment_method_id')

        if not intent_id:
            raise ValidationError({'booking_intent_id': 'booking_intent_id is required.'})
        if not payment_method_id:
            raise ValidationError({'payment_method_id': 'payment_method_id is required.'})

        try:
            intent = BookingIntent.objects.select_related('event').get(booking_intent_id=intent_id, made_by=user)
        except BookingIntent.DoesNotExist:
            raise ValidationError({'booking_intent_id': 'Booking intent not found for this user.'})

        try:
            payment_method = PaymentMethod.objects.get(id=payment_method_id, event=intent.event)
        except PaymentMethod.DoesNotExist:
            raise ValidationError({'payment_method_id': 'Payment method not found for this event.'})

        if payment_method.method_type != PaymentMethodTypeChoices.BANK_TRANSFER:
            raise ValidationError({'payment_method_id': 'Only bank transfer payments can be reserved.'})

        existing_checkout_payment = Payment.objects.filter(
            user=user,
            event=intent.event,
            method=payment_method,
            metadata__checkout_intent_id=str(intent.booking_intent_id),
            metadata__payment_type='booking_checkout_pending_finalization',
        ).exclude(
            status__in=[PaymentStatusChoices.CANCELLED, PaymentStatusChoices.FAILED]
        ).order_by('-created_at').first()

        if existing_checkout_payment:
            return Response({
                'payment_id': str(existing_checkout_payment.payment_id),
                'payment_reference': existing_checkout_payment.payment_reference,
                'bank_transfer_reference': existing_checkout_payment.bank_transfer_reference,
                'status': existing_checkout_payment.status,
                'message': 'Checkout payment already exists for this booking intent.',
            }, status=status.HTTP_200_OK)

        if not intent.is_active:
            raise ValidationError({'booking_intent_id': 'Booking intent is no longer active.'})

        existing_payment = Payment.objects.filter(
            user=user,
            event=intent.event,
            method=payment_method,
            status=PaymentStatusChoices.DRAFTING,
            metadata__contains={
                'checkout_intent_id': str(intent.booking_intent_id),
                'payment_type': 'booking_checkout_reservation',
            },
        ).order_by('-created_at').first()

        if existing_payment:
            payment = existing_payment
        else:
            payment = Payment.objects.create(
                user=user,
                event=intent.event,
                method=payment_method,
                base_amount=Money(0, 'GBP'),
                original_amount=Money(0, 'GBP'),
                percentage_modifier=Decimal('0.00'),
                description=f"Bank transfer reservation for intent {intent.booking_intent_id} - {intent.event.title}",
                status=PaymentStatusChoices.DRAFTING,
                metadata={
                    'checkout_intent_id': str(intent.booking_intent_id),
                    'payment_type': 'booking_checkout_reservation',
                    'booking_finalized': False,
                },
            )

        return Response({
            'payment_id': str(payment.payment_id),
            'payment_reference': payment.payment_reference,
            'bank_transfer_reference': payment.bank_transfer_reference,
            'status': payment.status,
            'message': 'Bank transfer reference reserved.',
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Upload bank transfer evidence for checkout",
        description=(
            "Upload bank transfer evidence before checkout and bind it to an active booking intent. "
            "The returned bank_transfer_evidence_id can then be submitted in JSON checkout payload."
        ),
        tags=["Bookings"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'booking_intent_id': {'type': 'string', 'format': 'uuid'},
                    'evidence_file': {'type': 'string', 'format': 'binary'},
                    'payer_name': {'type': 'string'},
                    'payer_account_last4': {'type': 'string'},
                    'amount_on_evidence': {'type': 'string'},
                },
                'required': ['booking_intent_id', 'evidence_file', 'payer_name', 'payer_account_last4', 'amount_on_evidence'],
            }
        },
        responses={
            201: OpenApiResponse(description='Evidence uploaded and bound to intent.'),
            400: OpenApiResponse(description='Validation error.'),
        },
        operation_id="bookings_upload_bank_transfer_evidence",
    )
    @action(detail=False, methods=['post'], url_path='upload-bank-transfer-evidence')
    def upload_bank_transfer_evidence(self, request: Request) -> Response:
        user = request.user
        intent_id = request.data.get('booking_intent_id')
        if not intent_id:
            raise ValidationError({'booking_intent_id': 'booking_intent_id is required.'})

        try:
            intent = BookingIntent.objects.get(booking_intent_id=intent_id, made_by=user)
        except BookingIntent.DoesNotExist:
            raise ValidationError({'booking_intent_id': 'Booking intent not found for this user.'})

        if not intent.is_active:
            raise ValidationError({'booking_intent_id': 'Booking intent is no longer active.'})

        evidence_file = request.FILES.get('evidence_file')
        if not evidence_file:
            raise ValidationError({'evidence_file': 'evidence_file is required.'})

        payer_name = str(request.data.get('payer_name') or '').strip()
        if not payer_name:
            raise ValidationError({'payer_name': 'payer_name is required.'})

        payer_account_last4 = str(request.data.get('payer_account_last4') or '').strip()
        if not payer_account_last4 or not payer_account_last4.isdigit() or len(payer_account_last4) != 4:
            raise ValidationError({'payer_account_last4': 'payer_account_last4 must be exactly 4 digits.'})

        raw_amount = request.data.get('amount_on_evidence')
        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            raise ValidationError({'amount_on_evidence': 'amount_on_evidence must be a valid number.'})
        if amount <= 0:
            raise ValidationError({'amount_on_evidence': 'amount_on_evidence must be greater than zero.'})

        transfer_id = f"TMP-{uuid.uuid4().hex[:16].upper()}"
        evidence = BankTransferEvidence.objects.create(
            transfer_id=transfer_id,
            evidence_file=evidence_file,
            payer_name=payer_name,
            payer_account_last4=payer_account_last4,
            amount_on_evidence=Money(amount, 'GBP'),
            metadata={
                'booking_intent_id': str(intent.booking_intent_id),
                'uploaded_by_user_id': user.id,
                'precheckout_upload': True,
                'consumed': False,
                'intent_expires_at': intent.expires_at.isoformat() if intent.expires_at else None,
            },
        )

        return Response({
            'bank_transfer_evidence_id': str(evidence.bank_transfer_id),
            'uploaded_at': evidence.uploaded_at,
            'message': 'Evidence uploaded. Use bank_transfer_evidence_id in checkout payload.',
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Preview checkout pricing",
        description=(
            "Calculate a pre-checkout pricing preview for booking packages and package products. "
            "This endpoint validates an active booking intent, evaluates eligibility and discounts, "
            "and returns a detailed line-item breakdown. "
            "Stock checks are performed using temporary order-item reservations that are always rolled back."
        ),
        tags=["Bookings"],
        request={'application/json': CheckoutPreviewSerializer},
        responses={
            200: OpenApiResponse(
                description="Checkout preview generated",
                response={
                    'type': 'object',
                    'properties': {
                        'booking_intent_id': {'type': 'string', 'format': 'uuid'},
                        'event_id': {'type': 'string', 'format': 'uuid'},
                        'currency': {'type': 'string'},
                        'total_amount': {'type': 'string'},
                        'soft_stock_reservation': {'type': 'boolean'},
                        'attendees': {'type': 'array'},
                    }
                }
            ),
            400: OpenApiResponse(description="Validation error"),
        },
        operation_id="bookings_checkout_preview",
    )
    @action(detail=False, methods=['post'], url_path='checkout-preview')
    def checkout_preview(self, request: Request) -> Response:
        """
        Preview booking checkout totals and discounts without persisting booking/payment data.
        """

        serializer = CheckoutPreviewSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        intent = serializer.validated_data['_intent']
        attendee_selections = serializer.validated_data['attendees']
        discount_code = serializer.validated_data.get('discount_code') or None

        def applied_discount_breakdown(payable: 'PaymentMixin', discount_base: Money, context: dict) -> typing.Tuple[typing.List[typing.Dict[str, typing.Any]], Money]:
            """
            Applies eligible discounts to a given payable item (package or product) and calculates the total discount amount.

            Args:
                payable (PaymentMixin): The item to which discounts are applied.
                discount_base (Money): The base amount before discounts.
                context (dict): Context for evaluating discount eligibility.
            
            Returns:
                tuple: A tuple containing a list of applied discounts and the total discount amount.

            """
            percentage_total = Decimal('0.00')
            fixed_total = Money(0, discount_base.currency)
            applied_discounts = []

            for discount in payable.discounts:
                if not discount_applies(discount, context):
                    continue

                if discount.discount_type == DiscountType.PERCENTAGE:
                    percentage_total += discount.percentage
                    discount_amount = discount_base * (discount.percentage / Decimal('100'))
                    value = str(discount.percentage)
                else:
                    fixed_total += discount.amount
                    discount_amount = discount.amount
                    value = str(discount.amount.amount)

                applied_discounts.append({
                    'discount_id': str(discount.discount_id),
                    'name': discount.name,
                    'discount_type': discount.discount_type,
                    'value': value,
                    'amount': str(discount_amount.amount),
                    'currency': discount_base.currency.code,
                })

            percentage_discount = discount_base * (percentage_total / Decimal('100'))
            total_discount = percentage_discount + fixed_total
            if total_discount > discount_base:
                total_discount = discount_base

            return applied_discounts, total_discount

        try:
            with transaction.atomic():
                intent = BookingIntent.objects.select_for_update().get(
                    booking_intent_id=intent.booking_intent_id
                )

                intent.expires_at = timezone.now() + timezone.timedelta(minutes=30)
                intent.save(update_fields=['expires_at'])

                if not intent.is_active or not intent.can_create_booking():
                    raise ValidationError({
                        'booking_intent_id': 'Booking intent is no longer valid for checkout preview.'
                    })

                preview_savepoint = transaction.savepoint()
                attendees_breakdown = []
                total_amount = Money(0, 'GBP')

                try:
                    for selection in attendee_selections:
                        package = selection['_package']
                        product_selections = selection.get('product_selections', [])

                        attendee = selection.get('_attendee')
                        attendee_source = 'existing'
                        if not attendee:
                            attendee_source = 'draft'
                            draft = selection.get('_attendee_draft') or {}
                            relationship = draft.get('relationship_to_user')
                            attendee_user = user if relationship == AttendeeRelationship.SELF else None
                            attendee = Attendee.objects.create(
                                event=intent.event,
                                user=attendee_user,
                                defined_by=user,
                                first_name=draft.get('first_name'),
                                last_name=draft.get('last_name'),
                                email=draft.get('email') or None,
                                phone_number=draft.get('phone_number') or None,
                                date_of_birth=draft.get('date_of_birth'),
                                gender=draft.get('gender') or None,
                                relationship_to_user=relationship,
                                area_from_id=draft.get('area_from'),
                            )

                        attendee_context = attendee.pricing_context(code=discount_code)
                        attendee_name = attendee.full_name
                        if not package.can_use_package(user, attendee):
                            raise ValidationError({
                                'package_id': (
                                    f'Attendee {attendee.attendee_id} is not eligible for package {package.name}.'
                                )
                            })

                        package_base = package.modified_amount
                        package_discounts, package_discount_total = applied_discount_breakdown(
                            payable=package,
                            discount_base=package_base,
                            context=attendee_context,
                        )
                        package_final = max(
                            package_base - package_discount_total,
                            Money(0, package_base.currency)
                        )

                        attendee_total = package_final
                        products_breakdown = []

                        if product_selections:
                            for product_selection in product_selections:
                                package_product = product_selection['_package_product']
                                variant = product_selection['_variant']
                                quantity = product_selection['quantity']

                                if package_product.booking_package_id != package.id:
                                    raise ValidationError({
                                        'product_selections': (
                                            f'Package product {package_product.id} does not belong to package {package.id}.'
                                        )
                                    })

                                if not variant.can_attendee_purchase(attendee):
                                    raise ValidationError({
                                        'product_selections': (
                                            f'Attendee {attendee.attendee_id} is not eligible for selected variant {variant.variant_id}.'
                                        )
                                    })

                                try:
                                    variant.can_attendee_purchase_quantity(attendee, quantity, raise_exception=True)
                                except Exception as exc:
                                    raise ValidationError({
                                        'product_selections': (
                                            f'Unable to reserve product stock for preview: {str(exc)}'
                                        )
                                    })

                                variant_base = variant.modified_amount
                                bundled_unit_price = variant_base * (
                                    Decimal('1.00') + package_product.percentage_modifier / Decimal('100')
                                )
                                product_discounts, product_discount_total = applied_discount_breakdown(
                                    payable=package_product,
                                    discount_base=bundled_unit_price,
                                    context=attendee_context,
                                )
                                product_final_unit = max(
                                    bundled_unit_price - product_discount_total,
                                    Money(0, bundled_unit_price.currency)
                                )
                                product_line_total = product_final_unit * quantity
                                attendee_total += product_line_total

                                products_breakdown.append({
                                    'package_product_id': package_product.id,
                                    'variant_id': str(variant.variant_id),
                                    'product_title': package_product.product.title,
                                    'quantity': quantity,
                                    'unit_base_amount': str(variant_base.amount.quantize(Decimal('0.01'))),
                                    'unit_bundled_amount': str(bundled_unit_price.amount.quantize(Decimal('0.01'))),
                                    'unit_discount_total': str(product_discount_total.amount.quantize(Decimal('0.01'))),
                                    'unit_final_amount': str(product_final_unit.amount.quantize(Decimal('0.01'))),
                                    'line_total': str(product_line_total.amount.quantize(Decimal('0.01'))),
                                    'currency': product_final_unit.currency.code,
                                    'applied_discounts': product_discounts,
                                })

                        total_amount += attendee_total
                        attendees_breakdown.append({
                            'attendee_id': str(attendee.attendee_id) if attendee else None,
                            'attendee_name': attendee_name,
                            'source': attendee_source,
                            'package': {
                                'package_id': package.id,
                                'package_name': package.name,
                                'base_amount': str(package_base.amount.quantize(Decimal('0.01'))),
                                'discount_total': str(package_discount_total.amount.quantize(Decimal('0.01'))),
                                'final_amount': str(package_final.amount.quantize(Decimal('0.01'))),
                                'currency': package_final.currency.code,
                                'applied_discounts': package_discounts,
                            },
                            'products': products_breakdown,
                            'attendee_total': str(attendee_total.amount.quantize(Decimal('0.01'))),
                            'currency': attendee_total.currency.code,
                        })

                finally:
                    transaction.savepoint_rollback(preview_savepoint)

                return Response(
                    {
                        'booking_intent_id': str(intent.booking_intent_id),
                        'event_id': str(intent.event.event_id),
                        'currency': total_amount.currency.code,
                        'total_amount': str(total_amount.amount.quantize(Decimal('0.01'))),
                        'soft_stock_reservation': True,
                        'discount_code_applied': discount_code or None,
                        'attendees': attendees_breakdown,
                    },
                    status=status.HTTP_200_OK,
                )

        except ValidationError:
            raise
        except Exception as exc:
            logger.error(
                f"Checkout preview failed for user {user.id}, intent {intent.booking_intent_id}: {str(exc)}",
                exc_info=True,
            )
            raise ValidationError({
                'checkout_preview': (
                    'Could not generate checkout preview due to an unexpected error. '
                    'Please retry or contact support.'
                )
            })
        
    @extend_schema(
        summary="Ping booking intent to extend expiry",
        description=(
            "Internal endpoint to ping a booking intent and extend its expiry. "
            "Used by frontend to keep intent alive during checkout."
        ),
        tags=["Booking Intents"],
        responses={
            200: OpenApiResponse(
                description="Booking intent status",
                response={
                    'type': 'object',
                    'properties': {
                        'intent': {'type': 'string', 'format': 'uuid'},
                        'exists': {'type': 'boolean'},
                        'is_active': {'type': 'boolean'},
                        'is_expired': {'type': 'boolean'},
                        'status': {'type': 'string'},
                        'expires_at': {'type': 'string', 'format': 'date-time', 'nullable': True},
                        'seconds_remaining': {'type': 'integer'},
                        'redirect_required': {'type': 'boolean'},
                    }
                }
            ),
            400: OpenApiResponse(description='Missing intent query parameter'),
            404: OpenApiResponse(description='Booking intent not found'),
        },
        parameters=[
            OpenApiParameter(
                name='intent',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description='Booking intent ID to ping',
            ),
        ],
    )
    @action(detail=False, methods=['get'], url_path='ping-intent')
    def ping_booking_intent(self, request: Request) -> Response:
        """
        Internal endpoint to ping a booking intent and extend its expiry.
        Used by frontend to keep intent alive during checkout.
        """
        try:
            booking_intent_id = request.query_params.get('intent')
            if not booking_intent_id:
                return Response({'detail': 'Query parameter "intent" is required.'}, status=status.HTTP_400_BAD_REQUEST)

            intent = BookingIntent.objects.get(booking_intent_id=booking_intent_id)

            user = request.user
            if not (user.is_staff or user.is_superuser):
                if not intent.made_by_id or intent.made_by_id != user.id:
                    return Response({'detail': 'Booking intent not found.'}, status=status.HTTP_404_NOT_FOUND)

            # Keep intent alive while user is actively progressing through checkout.
            # if intent.is_active:
            #     intent.expires_at = timezone.now() + timezone.timedelta(minutes=20)
            #     intent.save(update_fields=['expires_at'])

            now = timezone.now()
            seconds_remaining = 0
            if intent.expires_at and intent.expires_at > now:
                seconds_remaining = int((intent.expires_at - now).total_seconds())

            return Response(
                {
                    'intent': str(intent.booking_intent_id),
                    'exists': True,
                    'is_active': intent.is_active,
                    'is_expired': intent.is_expired,
                    'status': intent.status,
                    'expires_at': intent.expires_at,
                    'seconds_remaining': max(seconds_remaining, 0),
                    'redirect_required': not intent.is_active,
                },
                status=status.HTTP_200_OK,
            )
        except BookingIntent.DoesNotExist:
            return Response({'detail': 'Booking intent not found.'}, status=status.HTTP_404_NOT_FOUND)