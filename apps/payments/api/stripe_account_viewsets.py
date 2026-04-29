"""
ViewSet endpoints for user-managed Stripe connected accounts.
"""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.payments.api.permissions import IsStripeAccountOwner
from apps.payments.api.stripe_serializers import (
    StripeConnectedAccountCreateSerializer,
    StripeConnectedAccountListSerializer,
    StripeConnectedAccountUpdateSerializer,
)
from apps.payments.models import StripeConnectedAccount
from apps.payments.services.stripe.connect import StripeConnectService


class StripeConnectedAccountViewSet(viewsets.ModelViewSet):
    """Manage Stripe connected accounts for the authenticated user."""

    permission_classes = [IsAuthenticated, IsStripeAccountOwner]
    lookup_field = 'stripe_account_id'
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        return StripeConnectedAccount.objects.filter(user=self.request.user).order_by('-is_primary', '-created_at')

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
