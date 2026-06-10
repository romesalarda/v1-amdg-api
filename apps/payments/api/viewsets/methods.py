from rest_framework import viewsets, status, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from apps.payments.models import PaymentMethod
from apps.payments.api.serializers import (
    PaymentMethodSerializer, PaymentMethodDetailSerializer, PaymentMethodCreateUpdateSerializer,
)
from apps.payments.api.filtersets import PaymentMethodFilterSet
from apps.payments.api.permissions import IsAdministrativeStaffOnly
from apps.common.pagination import StandardPagination
from apps.events.services.notifications import create_notification, NotificationPriorityChoices, NotificationTypeChoices

@extend_schema_view(
    list=extend_schema(
        summary="List payment methods",
        description="Retrieve all payment methods. Only accessible by administrative staff.",
        tags=["Payment Methods"],
    ),
    retrieve=extend_schema(
        summary="Retrieve payment method",
        description="Get detailed information about a specific payment method.",
        tags=["Payment Methods"],
    ),
    create=extend_schema(
        summary="Create payment method",
        description="Create a new payment method for an event. Only admins.",
        tags=["Payment Methods"],
    ),
    update=extend_schema(
        summary="Update payment method",
        description=(
            "Update a payment method with complete payload. "
            "Use PATCH for partial updates. Only administrative staff can update payment methods."
        ),
        tags=["Payment Methods"],
    ),
    partial_update=extend_schema(
        summary="Partially update payment method",
        description=(
            "Partially update a payment method such as changing status or configuration. "
            "Only administrative staff can update payment methods."
        ),
        tags=["Payment Methods"],
    ),
    destroy=extend_schema(
        summary="Delete payment method",
        description=(
            "Delete a payment method. Use with caution as this affects payment processing. "
            "Only administrative staff can delete payment methods."
        ),
        tags=["Payment Methods"],
    )
)
class PaymentMethodViewSet(viewsets.ModelViewSet):
    """
    ViewSet for PaymentMethod model operations.
    
    Permissions: Administrative staff only
    All operations restricted to admins for security and control.
    """
    
    queryset = PaymentMethod.objects.select_related('event', 'created_by')
    permission_classes = [permissions.IsAuthenticated, IsAdministrativeStaffOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PaymentMethodFilterSet
    search_fields = ['title', 'code', 'description']
    ordering_fields = ['created_at', 'title', 'method_type']
    ordering = ['-created_at']
    lookup_field = 'method_id'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return PaymentMethodSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return PaymentMethodCreateUpdateSerializer
        return PaymentMethodDetailSerializer
    
    def perform_create(self, serializer):
        """Set created_by to current user."""
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        """Set created_by to current user on update."""

        old_instance = self.get_object()

        payment_method =serializer.save(created_by=self.request.user)

        new_instance = self.get_object()

        changes = []
        stripe_account_id_changed = False
        new_stripe_account_id = None
        # detect changes to title, description, provided details and check account name, sort code, account number for bank transfer details

        if old_instance.title != new_instance.title:
            changes.append(f"title changed from '{old_instance.title}' to '{new_instance.title}'")

        if old_instance.description != new_instance.description:
            changes.append(f"description changed from '{old_instance.description}' to '{new_instance.description}'")

        if old_instance.provided_details != new_instance.provided_details:

            if old_instance.provided_details.get('account_name') != new_instance.provided_details.get('account_name'):
                changes.append(f"account name changed from '{old_instance.provided_details.get('account_name')}' to '{new_instance.provided_details.get('account_name')}'")

            if old_instance.provided_details.get('sort_code') != new_instance.provided_details.get('sort_code'):
                changes.append(f"sort code changed from '{old_instance.provided_details.get('sort_code')}' to '{new_instance.provided_details.get('sort_code')}'")

            if old_instance.provided_details.get('account_number') != new_instance.provided_details.get('account_number'):
                changes.append(f"account number changed from '{old_instance.provided_details.get('account_number')}' to '{new_instance.provided_details.get('account_number')}'")

            if old_instance.provided_details.get('stripe_account_id') != new_instance.provided_details.get('stripe_account_id'):
                changes.append(f"Stripe account ID changed from '{old_instance.provided_details.get('stripe_account_id')}' to '{new_instance.provided_details.get('stripe_account_id')}'")
                stripe_account_id_changed = True
                new_stripe_account_id = new_instance.provided_details.get('stripe_account_id')

        if stripe_account_id_changed:
            create_notification(
                event=payment_method.event,
                message=f"Stripe account ID for payment method '{payment_method.title}' updated. New Stripe Account ID: {new_stripe_account_id}",
                metadata={
                    'action': 'UPDATED_STRIPE_ACCOUNT',
                    'performed_by_id': self.request.user.id,
                    'performed_by_username': self.request.user.username,
                },
                notification_type=NotificationTypeChoices.GENERAL,
                priority=NotificationPriorityChoices.HIGH,
                force_create=True,
            )

        else:
            create_notification(
                event=payment_method.event,
                message=f"Payment method '{payment_method.title}' updated. Changes: {', '.join(changes)}",
                metadata={
                    'action': 'UPDATED',
                    'performed_by_id': self.request.user.id,
                    'performed_by_username': self.request.user.username,
                },
                notification_type=NotificationTypeChoices.GENERAL,
                force_create=True,
            )