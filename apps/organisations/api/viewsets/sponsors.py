import uuid

from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Q, Count, Sum
from django.http import Http404
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes
from typing import Any
from uuid import UUID

from apps.organisations.models import (
    Organisation, OrganisationControl,EventSponsor, EventSponsorPackage, EventSponsorInvite,
)
from apps.events.models import Event
from apps.payments.models import Payment, PaymentMethod, PaymentMethodTypeChoices, PaymentStatusChoices
from apps.utils.querying import get_organisation_or_url_safe_title
from apps.organisations.api.serializers import (
    EventSponsorListSerializer, EventSponsorDetailSerializer, EventSponsorCreateUpdateSerializer,
    EventSponsorLedgerSerializer,
    EventSponsorPackageListSerializer, EventSponsorPackageDetailSerializer, EventSponsorPackageCreateUpdateSerializer,
    EventSponsorInviteListSerializer, EventSponsorInviteDetailSerializer, EventSponsorInviteCreateUpdateSerializer,
    EventSponsorCheckoutSerializer, SponsorshipPaymentHistorySerializer,
)
from apps.organisations.api.filtersets import (
    EventSponsorFilterSet, EventSponsorPackageFilterSet,
    EventSponsorInviteFilterSet,
)
from apps.organisations.api.permissions import IsOrganisationControllerOrEventAdmin, HasMonetaryAccessPermission

from apps.common.pagination import StandardPagination

@extend_schema_view(
    list=extend_schema(
        summary="List event sponsors",
        description="Retrieve a list of event sponsors.",
        tags=["Event Sponsors"],
    ),
    retrieve=extend_schema(
        summary="Retrieve sponsor details",
        description="Get detailed information about an event sponsor including packages.",
        tags=["Event Sponsors"],
    ),
    create=extend_schema(
        summary="Create sponsor",
        description="Create a new event sponsor.",
        tags=["Event Sponsors"],
    ),
    update=extend_schema(
        summary="Update sponsor",
        description="Update sponsor details.",
        tags=["Event Sponsors"],
    ),
    partial_update=extend_schema(
        summary="Partially update sponsor",
        description="Partially update sponsor details.",
        tags=["Event Sponsors"],
    ),
    destroy=extend_schema(
        summary="Delete sponsor",
        description="Delete an event sponsor.",
        tags=["Event Sponsors"],
    ),
)
class EventSponsorViewSet(viewsets.ModelViewSet):
    """ViewSet for EventSponsor CRUD operations."""
    
    queryset = EventSponsor.objects.select_related(
        'organisation', 'event', 'added_by', 'verified_by', 'processed_by', 'package'
    ).order_by('-added_at')
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorFilterSet
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'added_at']
    ordering = ['-added_at']
    lookup_field = 'sponsor_id'

    def get_permissions(self):
        """Safe methods allow leaders with ALLOW_MONETARY_ACCESS; writes need controller/event-admin."""
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated(), HasMonetaryAccessPermission()]
        return [permissions.IsAuthenticated(), IsOrganisationControllerOrEventAdmin()]

    def _get_organisation_for_sponsor_lists(self, request):
        organisation_id = request.query_params.get('organisation_id') or request.query_params.get('organisation')
        if not organisation_id:
            return None, Response({'organisation_id': ['organisation_id is required.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            organisation = get_organisation_or_url_safe_title(organisation_id)
        except Http404:
            return None, Response({'organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        is_org_controller = request.user.is_superuser or request.user.is_staff or OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user,
        ).exists()
        if not is_org_controller:
            return None, Response(
                {'error': 'You must control this organisation to view sponsors.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return organisation, None

    def _apply_sponsor_list_filters(self, queryset, request):
        event_id = request.query_params.get('event_id')
        if event_id:
            try:
                UUID(event_id)
            except ValueError:
                return None, Response({'event_id': ['event_id must be a valid UUID.']}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(event__event_id=event_id)

        sponsor_org_id = request.query_params.get('sponsor_organisation_id')
        if sponsor_org_id:
            try:
                queryset = queryset.filter(organisation=get_organisation_or_url_safe_title(sponsor_org_id))
            except Http404:
                return None, Response({'sponsor_organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        event_org_id = request.query_params.get('event_organisation_id')
        if event_org_id:
            try:
                queryset = queryset.filter(event__organisation=get_organisation_or_url_safe_title(event_org_id))
            except Http404:
                return None, Response({'event_organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        return queryset, None

    def _build_payment_map(self, sponsors):
        sponsor_ids = [str(sponsor.id) for sponsor in sponsors]
        if not sponsor_ids:
            return {}

        sponsor_type = ContentType.objects.get_for_model(EventSponsor)
        payments = Payment.objects.filter(
            target_type=sponsor_type,
            target_id__in=sponsor_ids,
        ).order_by('-created_at')

        payment_map = {}
        for payment in payments:
            try:
                sponsor_id = int(payment.target_id)
            except (TypeError, ValueError):
                continue
            if sponsor_id not in payment_map:
                payment_map[sponsor_id] = payment
        return payment_map
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventSponsorListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventSponsorCreateUpdateSerializer
        return EventSponsorDetailSerializer
    
    @extend_schema(
        summary="List sponsor packages",
        description="Get all sponsorship packages for a specific sponsor.",
        responses={200: EventSponsorPackageListSerializer(many=True)},
        tags=["Event Sponsors"],
    )
    @action(detail=True, methods=['get'])
    def packages(self, request, sponsor_id=None):
        """Get package selected by the sponsor, if any."""
        sponsor = self.get_object()
        packages = [sponsor.package] if sponsor.package else []
        serializer = EventSponsorPackageListSerializer(
            packages, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @extend_schema(
        summary="Inbound sponsors list",
        description=(
            "List organisations sponsoring events owned by the specified organisation."
        ),
        tags=["Event Sponsors"],
        parameters=[
            OpenApiParameter(name='organisation_id', type=OpenApiTypes.STR, required=True, description='Organisation id or url_safe_title.'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.UUID, required=False, description='Event public UUID.'),
            OpenApiParameter(name='sponsor_organisation_id', type=OpenApiTypes.STR, required=False, description='Sponsor organisation id or url_safe_title.'),
        ],
        responses={200: EventSponsorLedgerSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='inbound')
    def inbound(self, request):
        organisation, error_response = self._get_organisation_for_sponsor_lists(request)
        if error_response:
            return error_response

        queryset = self.get_queryset().filter(event__organisation_id=organisation.id).order_by('-added_at')
        queryset, filter_error = self._apply_sponsor_list_filters(queryset, request)
        if filter_error:
            return filter_error

        page = self.paginate_queryset(queryset)
        if page is not None:
            payment_map = self._build_payment_map(page)
            serializer = EventSponsorLedgerSerializer(
                page,
                many=True,
                context={'request': request, 'payment_map': payment_map},
            )
            return self.get_paginated_response(serializer.data)

        payment_map = self._build_payment_map(queryset)
        serializer = EventSponsorLedgerSerializer(
            queryset,
            many=True,
            context={'request': request, 'payment_map': payment_map},
        )
        return Response(serializer.data)

    @extend_schema(
        summary="Outbound sponsors list",
        description=(
            "List events that the specified organisation is sponsoring."
        ),
        tags=["Event Sponsors"],
        parameters=[
            OpenApiParameter(name='organisation_id', type=OpenApiTypes.STR, required=True, description='Organisation id or url_safe_title.'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.UUID, required=False, description='Event public UUID.'),
            OpenApiParameter(name='event_organisation_id', type=OpenApiTypes.STR, required=False, description='Event organisation id or url_safe_title.'),
        ],
        responses={200: EventSponsorLedgerSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='outbound')
    def outbound(self, request):
        organisation, error_response = self._get_organisation_for_sponsor_lists(request)
        if error_response:
            return error_response

        queryset = self.get_queryset().filter(organisation_id=organisation.id).order_by('-added_at')
        queryset, filter_error = self._apply_sponsor_list_filters(queryset, request)
        if filter_error:
            return filter_error

        page = self.paginate_queryset(queryset)
        if page is not None:
            payment_map = self._build_payment_map(page)
            serializer = EventSponsorLedgerSerializer(
                page,
                many=True,
                context={'request': request, 'payment_map': payment_map},
            )
            return self.get_paginated_response(serializer.data)

        payment_map = self._build_payment_map(queryset)
        serializer = EventSponsorLedgerSerializer(
            queryset,
            many=True,
            context={'request': request, 'payment_map': payment_map},
        )
        return Response(serializer.data)

    @extend_schema(
        summary="Sponsor checkout",
        description=(
            "Create a provisional sponsor commitment and initialize payment. "
            "Supports direct authenticated controller flow and invite-token assisted flow."
        ),
        request=EventSponsorCheckoutSerializer,
        tags=["Event Sponsors"],
    )
    @action(detail=False, methods=['post'], url_path='checkout', permission_classes=[permissions.IsAuthenticated])
    def checkout(self, request):
        serializer = EventSponsorCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        invite = None
        if data.get('invite_token'):
            try:
                invite = EventSponsorInvite.objects.select_related(
                    'event', 'organisation', 'chapter_location'
                ).get(token=data['invite_token'])
            except EventSponsorInvite.DoesNotExist:
                return Response({'error': 'Invalid invite token.'}, status=status.HTTP_404_NOT_FOUND)

            if not invite.is_valid:
                return Response({'error': 'Invite is no longer valid.'}, status=status.HTTP_400_BAD_REQUEST)

        event = None
        if invite:
            event = invite.event
            payload_event_id = data.get('event_id')
            if payload_event_id and str(payload_event_id) != str(event.event_id):
                return Response({'event_id': ['event_id does not match invite token event.']}, status=status.HTTP_400_BAD_REQUEST)
        else:
            event_id = data.get('event_id')
            if not event_id:
                return Response({'event_id': ['event_id is required when invite_token is not provided.']}, status=status.HTTP_400_BAD_REQUEST)
            try:
                event = Event.objects.get(event_id=event_id)
            except Event.DoesNotExist:
                return Response({'event_id': ['Event not found.']}, status=status.HTTP_404_NOT_FOUND)

        settings_obj = getattr(event, 'settings', None)
        if settings_obj and not settings_obj.accepting_sponsorships_enabled:
            return Response({'error': 'Sponsorships are not enabled for this event.'}, status=status.HTTP_400_BAD_REQUEST)
        if settings_obj and settings_obj.requires_invite_acceptance_for_checkout and not invite:
            return Response(
                {'error': 'This event requires sponsorship invite acceptance before checkout.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            package = EventSponsorPackage.objects.get(package_id=data['package_id'])
        except EventSponsorPackage.DoesNotExist:
            return Response({'package_id': ['Package not found.']}, status=status.HTTP_404_NOT_FOUND)

        if package.event_id != event.id:
            return Response({'package_id': ['Selected package does not belong to the selected event.']}, status=status.HTTP_400_BAD_REQUEST)

        if not package.active:
            return Response({'package_id': ['Selected package is not active.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment_method = PaymentMethod.objects.get(pk=data['payment_method_id'])
        except PaymentMethod.DoesNotExist:
            return Response({'payment_method_id': ['Payment method not found.']}, status=status.HTTP_404_NOT_FOUND)

        if payment_method.event_id != event.id:
            return Response({'payment_method_id': ['Payment method does not belong to the selected event.']}, status=status.HTTP_400_BAD_REQUEST)

        if not payment_method.is_active:
            return Response({'payment_method_id': ['Payment method is not active.']}, status=status.HTTP_400_BAD_REQUEST)

        organisation = None
        if invite and invite.organisation_id:
            organisation = invite.organisation
        elif data.get('organisation_id'):
            try:
                organisation = Organisation.objects.get(pk=data['organisation_id'])
            except Organisation.DoesNotExist:
                return Response({'organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)

        # When invite has no pre-linked organisation, create one on-the-fly using the
        # name provided by the external sponsor. The new org + controller are saved
        # inside the atomic transaction below.
        org_created_inline = False
        if organisation is None:
            if invite:
                org_name = (data.get('organisation_name') or '').strip()
                if not org_name:
                    return Response(
                        {'organisation_name': ['organisation_name is required when the invite has no pre-linked organisation.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                organisation = Organisation(title=org_name, created_by=request.user)
                org_created_inline = True
            else:
                return Response({'organisation_id': ['Unable to resolve organisation for this checkout.']}, status=status.HTTP_400_BAD_REQUEST)

        if not org_created_inline:
            is_org_controller = request.user.is_superuser or request.user.is_staff or OrganisationControl.objects.filter(
                organisation=organisation,
                user=request.user,
            ).exists()
            if not is_org_controller:
                return Response({'error': 'You must control this organisation to checkout sponsorship.'}, status=status.HTTP_403_FORBIDDEN)

        chapter_location = invite.chapter_location if invite and invite.chapter_location_id else None
        if data.get('chapter_location'):
            from apps.locations.models import ChapterLocation
            try:
                chapter_location = ChapterLocation.objects.get(pk=data['chapter_location'])
            except ChapterLocation.DoesNotExist:
                return Response({'chapter_location': ['Chapter location not found.']}, status=status.HTTP_404_NOT_FOUND)

        # A freshly-created (unsaved) organisation cannot already be a sponsor.
        if not org_created_inline and EventSponsor.objects.filter(
            event=event,
            organisation=organisation,
            chapter_location=chapter_location,
        ).exists():
            return Response({'error': 'This organisation is already sponsoring the event for this location.'}, status=status.HTTP_409_CONFLICT)

        sponsor_name = (data.get('name') or organisation.title).strip()
        if not sponsor_name:
            return Response({'name': ['Sponsor name cannot be empty.']}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            if org_created_inline:
                organisation.save()
                OrganisationControl.objects.create(
                    organisation=organisation,
                    user=request.user,
                    added_by=request.user,
                )

            sponsor = EventSponsor.objects.create(
                name=sponsor_name,
                description=data.get('description', ''),
                organisation=organisation,
                event=event,
                package=package,
                chapter_location=chapter_location,
                added_by=request.user,
            )

            payment = Payment.objects.create(
                user=request.user,
                event=event,
                method=payment_method,
                base_amount=package.modified_amount,
                description=f"Sponsorship payment for {event.title} ({package.package_name})",
                target_type=ContentType.objects.get_for_model(EventSponsor),
                target_id=str(sponsor.pk),
                status=PaymentStatusChoices.DRAFTING,
            )
            payment.transition_to(PaymentStatusChoices.PENDING)

            response_data = {
                'sponsor_id': str(sponsor.sponsor_id),
                'payment_id': str(payment.payment_id),
                'payment_reference': payment.payment_reference,
                'payment_status': payment.status,
                'payment_method_type': payment_method.method_type,
            }

            if payment_method.method_type == PaymentMethodTypeChoices.STRIPE:
                from apps.payments.services.stripe.payment_intents import PaymentIntentService
                from apps.payments.services.stripe.client import StripeClient
                from apps.payments.services.stripe.exceptions import StripeServiceError

                try:
                    stripe_account_id = payment_method.get_stripe_account_id()
                    if not stripe_account_id:
                        use_platform = bool((payment_method.provided_details or {}).get('use_platform_account'))
                        if not use_platform:
                            raise DjangoValidationError(
                                "This Stripe payment method has no connected account configured. "
                                "Please contact the event organiser."
                            )
                    payment_intent = PaymentIntentService.create(
                        amount=payment.base_amount,
                        currency=payment.base_amount.currency.code,
                        payment_reference=payment.payment_reference,
                        metadata=payment.prepare_stripe_metadata(),
                        customer_email=payment.user.email,
                        customer_id=payment.stripe_customer_id,
                        description=f"Sponsorship payment for {event.title}",
                        stripe_account_id=stripe_account_id,
                    )
                    payment.stripe_payment_intent = payment_intent.id
                    payment.save(update_fields=['stripe_payment_intent', 'updated_at'])
                    response_data.update({
                        'client_secret': payment_intent.client_secret,
                        'payment_intent_id': payment_intent.id,
                        'publishable_key': StripeClient.get_publishable_key(),
                    })
                except StripeServiceError as exc:
                    raise DjangoValidationError(f"Unable to initialize Stripe payment: {exc.user_message}")
            elif payment_method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
                response_data.update({
                    'bank_transfer_reference': payment.bank_transfer_reference,
                    'payment_instructions': payment_method.provided_details or {},
                })

            if invite:
                invite.accepted = True
                invite.declined = False
                invite.responded_at = timezone.now()
                invite.save(update_fields=['accepted', 'declined', 'responded_at'])

        return Response(response_data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Sponsorship payment history",
        description=(
            "Get sponsorship payment summary and timeline for an organisation and event pair. "
            "Only organisation controllers or staff can access this endpoint."
        ),
        tags=["Event Sponsors"],
        parameters=[
            OpenApiParameter(name='organisation_id', type=OpenApiTypes.INT, required=True, description='Organisation ID.'),
            OpenApiParameter(name='event_id', type=OpenApiTypes.UUID, required=True, description='Event public UUID.'),
        ],
        responses={200: SponsorshipPaymentHistorySerializer},
    )
    @action(detail=False, methods=['get'], url_path='payment-history', permission_classes=[permissions.IsAuthenticated])
    def payment_history(self, request):
        organisation_id = request.query_params.get('organisation_id')
        event_id = request.query_params.get('event_id')

        if not organisation_id:
            return Response({'organisation_id': ['organisation_id is required.']}, status=status.HTTP_400_BAD_REQUEST)
        if not event_id:
            return Response({'event_id': ['event_id is required.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            organisation = get_organisation_or_url_safe_title(organisation_id)
        except Http404:
            return Response({'organisation_id': ['Organisation not found.']}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            event = Event.objects.get(event_id=event_id)
        except Event.DoesNotExist:
            return Response({'event_id': ['Event not found.']}, status=status.HTTP_404_NOT_FOUND)

        is_org_controller = request.user.is_superuser or request.user.is_staff or OrganisationControl.objects.filter(
            organisation=organisation,
            user=request.user,
        ).exists()
        if not is_org_controller:
            return Response(
                {'error': 'You must control this organisation to view sponsorship payments.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        sponsor_ids = list(
            EventSponsor.objects.filter(
                organisation=organisation,
                event=event,
            ).values_list('id', flat=True)
        )

        if not sponsor_ids:
            data = {
                'event_id': event.event_id,
                'event_title': event.title,
                'organisation_id': organisation.id,
                'organisation_title': organisation.title,
                'summary': {
                    'total_payments': 0,
                    'completed_payments': 0,
                    'pending_payments': 0,
                    'failed_payments': 0,
                    'cancelled_payments': 0,
                    'total_completed_amount': '0.00',
                    'currency': 'GBP',
                },
                'timeline': [],
            }
            serializer = SponsorshipPaymentHistorySerializer(data)
            return Response(serializer.data)

        sponsor_content_type = ContentType.objects.get_for_model(EventSponsor)
        payment_queryset = Payment.objects.select_related('method').filter(
            target_type=sponsor_content_type,
            target_id__in=[str(sponsor_id) for sponsor_id in sponsor_ids],
            event=event,
        ).order_by('-created_at')

        aggregates = payment_queryset.aggregate(
            total_payments=Count('id'),
            completed_payments=Count('id', filter=Q(status=PaymentStatusChoices.COMPLETED)),
            pending_payments=Count('id', filter=Q(status=PaymentStatusChoices.PENDING)),
            failed_payments=Count('id', filter=Q(status=PaymentStatusChoices.FAILED)),
            cancelled_payments=Count('id', filter=Q(status=PaymentStatusChoices.CANCELLED)),
            total_completed_amount=Sum('base_amount', filter=Q(status=PaymentStatusChoices.COMPLETED)),
        )

        total_completed_amount = aggregates.get('total_completed_amount')
        if total_completed_amount is None:
            total_completed_amount_value = '0.00'
            currency = 'GBP'
        else:
            total_completed_amount_value = str(getattr(total_completed_amount, 'amount', total_completed_amount))
            currency = str(getattr(total_completed_amount, 'currency', 'GBP'))


        timeline = [
            {
                'payment_id': payment.payment_id,
                'payment_reference': payment.payment_reference,
                'status': payment.status,
                'amount': str(payment.base_amount.amount) if payment.base_amount else '0.00',
                'currency': str(payment.base_amount.currency) if payment.base_amount else currency,
                'method_type': payment.method.method_type if payment.method else None,
                'method_title': payment.method.title if payment.method else None,
                'method_provided_details': payment.method.provided_details if payment.method else None,
                'created_at': payment.created_at,
                'updated_at': payment.updated_at,
                'bank_transfer_reference': payment.bank_transfer_reference if payment.method and payment.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER else None,

            }
            for payment in payment_queryset
        ]

        response_payload = {
            'event_id': event.event_id,
            'event_title': event.title,
            'organisation_id': organisation.id,
            'organisation_title': organisation.title,
            'summary': {
                'total_payments': aggregates.get('total_payments', 0),
                'completed_payments': aggregates.get('completed_payments', 0),
                'pending_payments': aggregates.get('pending_payments', 0),
                'failed_payments': aggregates.get('failed_payments', 0),
                'cancelled_payments': aggregates.get('cancelled_payments', 0),
                'total_completed_amount': total_completed_amount_value,
                'currency': currency,
            },
            'timeline': timeline,
        }
        serializer = SponsorshipPaymentHistorySerializer(response_payload)
        return Response(serializer.data)

@extend_schema_view(
    list=extend_schema(
        summary="List sponsor packages",
        description="Retrieve a list of sponsorship packages with payment info.",
        tags=["Sponsorship Packages"],
    ),
    retrieve=extend_schema(
        summary="Retrieve package details",
        description="Get detailed information about a sponsorship package including payment.",
        tags=["Sponsorship Packages"],
    ),
    create=extend_schema(
        summary="Create package",
        description="Create a new sponsorship package.",
        tags=["Sponsorship Packages"],
    ),
    update=extend_schema(
        summary="Update package",
        description="Update package details.",
        tags=["Sponsorship Packages"],
    ),
    partial_update=extend_schema(
        summary="Partially update package",
        description="Partially update package details.",
        tags=["Sponsorship Packages"],
    ),
    destroy=extend_schema(
        summary="Delete package",
        description="Delete a sponsorship package.",
        tags=["Sponsorship Packages"],
    ),
)
class EventSponsorPackageViewSet(viewsets.ModelViewSet):
    """ViewSet for EventSponsorPackage with PayableModel support."""
    
    queryset = EventSponsorPackage.objects.select_related(
        'event'
    )
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorPackageFilterSet
    search_fields = ['package_name', 'package_description']
    ordering_fields = ['package_name', 'added_at', 'base_amount']
    ordering = ['-added_at']
    lookup_field = 'package_id'

    def get_permissions(self):
        """Safe methods allow leaders with ALLOW_MONETARY_ACCESS; writes need controller/event-admin."""
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated(), HasMonetaryAccessPermission()]
        return [permissions.IsAuthenticated(), IsOrganisationControllerOrEventAdmin()]
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventSponsorPackageListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return EventSponsorPackageCreateUpdateSerializer
        return EventSponsorPackageDetailSerializer
    
@extend_schema_view(
    list=extend_schema(summary="List sponsor invites", tags=["Event Sponsor Invites"]),
    retrieve=extend_schema(summary="Retrieve sponsor invite", tags=["Event Sponsor Invites"]),
    create=extend_schema(summary="Create sponsor invite", tags=["Event Sponsor Invites"]),
    update=extend_schema(summary="Update sponsor invite", tags=["Event Sponsor Invites"]),
    partial_update=extend_schema(summary="Partially update sponsor invite", tags=["Event Sponsor Invites"]),
    destroy=extend_schema(summary="Delete sponsor invite", tags=["Event Sponsor Invites"]),
)
class EventSponsorInviteViewSet(viewsets.ModelViewSet):
    """ViewSet for sponsor invitation lifecycle."""

    queryset = EventSponsorInvite.objects.select_related('event', 'organisation', 'chapter_location')
    permission_classes = [permissions.IsAuthenticated, IsOrganisationControllerOrEventAdmin]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EventSponsorInviteFilterSet
    search_fields = ['email', 'event__title', 'organisation__title']
    ordering_fields = ['sent_at', 'responded_at']
    ordering = ['-sent_at']
    lookup_field = 'invite_id'

    def get_permissions(self):
        """Safe methods allow leaders with ALLOW_MONETARY_ACCESS; writes need controller/event-admin."""
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated(), HasMonetaryAccessPermission()]
        return [permissions.IsAuthenticated(), IsOrganisationControllerOrEventAdmin()]

    def get_serializer_class(self):
        if self.action == 'list':
            return EventSponsorInviteListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return EventSponsorInviteCreateUpdateSerializer
        return EventSponsorInviteDetailSerializer

    @extend_schema(
        summary="Accept sponsor invite by token",
        request={'application/json': {'type': 'object', 'properties': {'token': {'type': 'string', 'format': 'uuid'}}, 'required': ['token']}},
        tags=["Event Sponsor Invites"],
    )
    @action(detail=False, methods=['post'], url_path='accept-by-token', permission_classes=[permissions.AllowAny])
    def accept_by_token(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invite = EventSponsorInvite.objects.get(token=token)
        except EventSponsorInvite.DoesNotExist:
            return Response({'error': 'Invite not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not invite.is_valid:
            return Response({'error': 'Invite is no longer valid.'}, status=status.HTTP_400_BAD_REQUEST)

        invite.accepted = True
        invite.declined = False
        invite.responded_at = timezone.now()
        invite.save(update_fields=['accepted', 'declined', 'responded_at'])

        serializer = EventSponsorInviteDetailSerializer(invite, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Decline sponsor invite by token",
        request={'application/json': {'type': 'object', 'properties': {'token': {'type': 'string', 'format': 'uuid'}}, 'required': ['token']}},
        tags=["Event Sponsor Invites"],
    )
    @action(detail=False, methods=['post'], url_path='decline-by-token', permission_classes=[permissions.AllowAny])
    def decline_by_token(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invite = EventSponsorInvite.objects.get(token=token)
        except EventSponsorInvite.DoesNotExist:
            return Response({'error': 'Invite not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not invite.is_valid:
            return Response({'error': 'Invite is no longer valid.'}, status=status.HTTP_400_BAD_REQUEST)

        invite.declined = True
        invite.accepted = False
        invite.responded_at = timezone.now()
        invite.save(update_fields=['accepted', 'declined', 'responded_at'])

        serializer = EventSponsorInviteDetailSerializer(invite, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Retrieve sponsor invite by token",
        description=(
            "Retrieve sponsor invite details and event info by token. "
            "Does not require authentication. Used by the external sponsor checkout page. "
            "Returns 400 if the invite has already been accepted or declined."
        ),
        parameters=[
            OpenApiParameter(
                name='token',
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=True,
                description='Invite token UUID.',
            ),
        ],
        responses={200: EventSponsorInviteDetailSerializer},
        tags=["Event Sponsor Invites"],
    )
    @action(detail=False, methods=['get'], url_path='retrieve-by-token', permission_classes=[permissions.AllowAny])
    def retrieve_by_token(self, request):
        token = request.query_params.get('token')
        if not token:
            return Response({'error': 'token query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            uuid.UUID(token)
        except ValueError:
            return Response({'error': 'token must be a valid UUID.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            invite = EventSponsorInvite.objects.select_related(
                'event', 'organisation', 'chapter_location'
            ).get(token=token)
        except EventSponsorInvite.DoesNotExist:
            return Response({'error': 'Invite not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = EventSponsorInviteDetailSerializer(invite, context={'request': request})
        data = dict(serializer.data)

        # Embed event details needed for the external checkout page.
        event = invite.event
        data['event_title'] = event.title
        data['event_url_safe_title'] = event.url_safe_title
        data['event_start_datetime'] = event.start_datetime.isoformat() if event.start_datetime else None
        data['event_end_datetime'] = event.end_datetime.isoformat() if event.end_datetime else None
        data['event_id'] = str(event.event_id)

        return Response(data, status=status.HTTP_200_OK)
