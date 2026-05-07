"""
ViewSet endpoints for user-managed Stripe connected accounts.
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.payments.api.permissions import (
    IsStripeAccountOwner,
    user_can_access_stripe_account_for_event,
)
from apps.payments.api.stripe_serializers import (
    StripeConnectedAccountCreateSerializer,
    StripeConnectedAccountListSerializer,
    StripeConnectedAccountUpdateSerializer,
)
from apps.payments.models import StripeConnectedAccount
from apps.payments.services.stripe.connect import StripeConnectService


@extend_schema_view(
    retrieve=extend_schema(
        parameters=[
            OpenApiParameter(
                name='event',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    'Optional event url_safe_title. If supplied, event staff can retrieve '
                    'a non-owned account only when that account is linked to a Stripe '
                    'payment method on the event.'
                ),
            )
        ]
    )
)
class StripeConnectedAccountViewSet(viewsets.ModelViewSet):
    """Manage Stripe connected accounts for the authenticated user."""

    permission_classes = [IsAuthenticated, IsStripeAccountOwner]
    lookup_field = 'stripe_account_id'
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        queryset = StripeConnectedAccount.objects.all().order_by('-is_primary', '-created_at')

        # List is always self-scoped.
        if self.action == 'list':
            return queryset.filter(user=user)

        # Retrieve can expand beyond ownership only with event-based staff access.
        if self.action == 'retrieve':
            event_identifier = self.request.query_params.get('event')
            if not event_identifier:
                return queryset.filter(user=user)

            if user_can_access_stripe_account_for_event(
                user=user,
                event_identifier=event_identifier,
                stripe_account_id=self.kwargs.get(self.lookup_field),
            ):
                return queryset

            return queryset.none()

        # Mutating actions remain owner-scoped.
        return queryset.filter(user=user)

    def get_serializer_class(self):
        if self.action == 'create':
            return StripeConnectedAccountCreateSerializer
        if self.action == 'partial_update':
            return StripeConnectedAccountUpdateSerializer
        return StripeConnectedAccountListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = serializer.save()
        response_serializer = StripeConnectedAccountListSerializer(account)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        account = self.get_object()
        serializer = self.get_serializer(account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        account = serializer.save()

        # Keep primary-account behavior centralized in service/model layers.
        if serializer.validated_data.get('is_primary') is True:
            account = StripeConnectService.set_primary(account)

        response_serializer = StripeConnectedAccountListSerializer(account)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='set-primary')
    def set_primary(self, request, stripe_account_id=None):
        account = self.get_object()
        account = StripeConnectService.set_primary(account)
        serializer = StripeConnectedAccountListSerializer(account)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        account = self.get_object()

        # If this is the primary account, check whether other accounts exist.
        # Prevent deletion without first re-assigning primary to avoid an
        # ownerless account pool.
        if account.is_primary:
            other_active = (
                StripeConnectedAccount.objects.filter(user=request.user, is_active=True)
                .exclude(pk=account.pk)
                .exists()
            )
            if other_active:
                return Response(
                    {
                        'detail': (
                            'Cannot delete the primary account while other active accounts exist. '
                            'Set a different account as primary first.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
