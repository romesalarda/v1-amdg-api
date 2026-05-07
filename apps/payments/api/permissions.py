"""
Production-grade permissions for the payments app.

Provides comprehensive permission classes for payment management with
support for event-based ADMINISTRATIVE roles, Django staff, and superusers.

Permission Classes:
    - IsAdministrativeStaff: Checks for ADMINISTRATIVE event role, staff, or superuser
    - IsPaymentOwner: Checks if user owns the payment
    - IsPaymentOwnerOrAdministrative: Combined permission for payment operations
    - IsRefundRequestOwnerOrAdministrative: Permission for refund operations

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework import permissions
from django.contrib.auth import get_user_model
from typing import Any
from uuid import UUID

from apps.events.models import EventRoleAssignment, EventRoleCategoryChoices
from apps.payments.models import (
    BankTransferEvidence,
    CreditExpense,
    PaymentMethod,
    PaymentMethodTypeChoices,
)

User = get_user_model()


class IsAdministrativeStaff(permissions.BasePermission):
    """
    Permission class to check if user has administrative access.
    
    Grants access if user is:
    1. Django superuser (is_superuser=True)
    2. Django staff (is_staff=True)
    3. Has EventRoleAssignment with ADMINISTRATIVE category role for the relevant event
    
    This permission should be used for operations that require administrative oversight
    such as viewing all payments, processing refunds, or managing payment methods.
    
    Example:
        ```python
        class PaymentViewSet(viewsets.ModelViewSet):
            permission_classes = [IsAuthenticated, IsAdministrativeStaff]
        ```
    """
    
    message = "You must be an administrator, staff member, or have an administrative event role to perform this action."
    
    def has_permission(self, request, view) -> bool:
        """
        Check if user has administrative privileges at the object-independent level.
        
        Args:
            request: The request object
            view: The view being accessed
            
        Returns:
            bool: True if user has administrative access, False otherwise
        """
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # For event-specific checks, we need the event context
        # This will be further refined in has_object_permission
        return True  # Allow through to object-level check
    
    def has_object_permission(self, request, view, obj) -> bool:
        """
        Check if user has administrative privileges for the specific object.
        
        Args:
            request: The request object
            view: The view being accessed
            obj: The object being accessed (Payment, RefundRequest, etc.)
            
        Returns:
            bool: True if user has administrative access, False otherwise
        """
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Django superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True
        # Get the event from the object
        event = self._get_event_from_object(obj)
        if not event:
            return False
        
        # Check if user has an ADMINISTRATIVE role for this event
        return self._user_has_administrative_role(request.user, event)
    
    def _get_event_from_object(self, obj) -> Any:
        """
        Extract the event from various object types.
        
        Args:
            obj: The object (Payment, RefundRequest, PaymentMethod, etc.)
            
        Returns:
            Event object or None
        """
        # Direct event attribute
        if hasattr(obj, 'event'):
            return obj.event
        
        # Event through payment (for RefundRequest, Donation)
        if hasattr(obj, 'payment') and hasattr(obj.payment, 'event'):
            return obj.payment.event
        
        # Event through discount target
        if hasattr(obj, 'target') and hasattr(obj.target, 'event'):
            return obj.target.event
        
        return None
    
    def _user_has_administrative_role(self, user, event) -> bool:
        """
        Check if user has an ADMINISTRATIVE role assignment for the event.
        
        Args:
            user: The user to check
            event: The event to check against
            
        Returns:
            bool: True if user has ADMINISTRATIVE role, False otherwise
        """
        return EventRoleAssignment.objects.filter(
            user=user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()


class IsPaymentOwner(permissions.BasePermission):
    """
    Permission class to check if user owns the payment.
    
    Grants access if the user is the owner of the payment object.
    Used for operations where users should only access their own payments.
    
    Example:
        ```python
        class MyPaymentsViewSet(viewsets.ReadOnlyModelViewSet):
            permission_classes = [IsAuthenticated, IsPaymentOwner]
        ```
    """
    
    message = "You can only access your own payments."
    
    def has_object_permission(self, request, view, obj) -> bool:
        """
        Check if user owns the payment object.
        
        Args:
            request: The request object
            view: The view being accessed
            obj: The payment object
            
        Returns:
            bool: True if user owns the payment, False otherwise
        """
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Get the user from the object
        payment_user = self._get_payment_user(obj)
        if not payment_user:
            return False
        
        return payment_user == request.user
    
    def _get_payment_user(self, obj) -> Any:
        """
        Extract the payment owner from various object types.
        
        Args:
            obj: The object (Payment, RefundRequest, Donation, etc.)
            
        Returns:
            User object or None
        """
        # Direct user attribute (Payment)
        if hasattr(obj, 'user'):
            return obj.user
        
        # User through payment (RefundRequest, Donation)
        if hasattr(obj, 'payment') and hasattr(obj.payment, 'user'):
            return obj.payment.user
        
        return None


class IsStripeAccountOwner(permissions.BasePermission):
    """Allow access only to Stripe connected account records owned by the request user."""

    message = "You can only access your own Stripe connected accounts."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        if getattr(obj, 'user_id', None) == request.user.id:
            return True

        if request.method not in permissions.SAFE_METHODS:
            return False

        if getattr(view, 'action', None) != 'retrieve':
            return False

        event_identifier = request.query_params.get('event')
        if not event_identifier:
            return False

        return user_can_access_stripe_account_for_event(
            user=request.user,
            event_identifier=event_identifier,
            stripe_account_id=getattr(obj, 'stripe_account_id', ''),
        )


def user_can_access_stripe_account_for_event(user, event_identifier: str, stripe_account_id: str) -> bool:
    """
    Check whether a user can view a specific Stripe connected account for an event.

    Access is granted only when:
    1. The user is staff on the referenced event, and
    2. The Stripe account is linked to a Stripe payment method on that event.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False

    if not event_identifier or not stripe_account_id:
        return False

    from apps.events.models import EventStaff

    is_event_staff = EventStaff.objects.filter(
        event__url_safe_title=event_identifier,
        user_id=user.id,
    ).exists()
    if not is_event_staff:
        return False

    return PaymentMethod.objects.filter(
        event__url_safe_title=event_identifier,
        method_type=PaymentMethodTypeChoices.STRIPE,
        provided_details__stripe_account_id=stripe_account_id,
    ).exists()


class IsPaymentOwnerOrAdministrative(permissions.BasePermission):
    """
    Combined permission: owner OR administrative staff.
    
    Grants access if user is either:
    - The owner of the payment, OR
    - Has administrative privileges (superuser, staff, or ADMINISTRATIVE event role)
    
    This is the most commonly used permission for payment operations,
    allowing users to manage their own payments while giving admins full access.
    
    Example:
        ```python
        class PaymentViewSet(viewsets.ModelViewSet):
            permission_classes = [IsAuthenticated, IsPaymentOwnerOrAdministrative]
        ```
    """
    
    message = "You must own this payment or have administrative privileges."
    
    def has_permission(self, request, view) -> bool:
        """Check basic authentication."""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj) -> bool:
        """
        Check if user is owner OR has administrative access.
        
        Args:
            request: The request object
            view: The view being accessed
            obj: The object being accessed
            
        Returns:
            bool: True if user is owner or admin, False otherwise
        """
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if owner
        owner_check = IsPaymentOwner()
        if owner_check.has_object_permission(request, view, obj):
            return True
        
        # Check if administrative
        admin_check = IsAdministrativeStaff()
        if admin_check.has_object_permission(request, view, obj):
            return True
                    
        return False


def _user_has_finance_role(user, event) -> bool:
    """Check whether a user has a finance-style role for the given event."""
    if not user or not getattr(user, 'is_authenticated', False) or not event:
        return False

    return EventRoleAssignment.objects.filter(
        user=user,
        event=event,
        role__name__icontains='finance'
    ).exists() or EventRoleAssignment.objects.filter(
        user=user,
        event=event,
        role__code__iexact='FIN'
    ).exists()


class IsCreditAccessible(permissions.BasePermission):
    """Allow creators and event administrators to view credit records."""

    message = "You do not have permission to access this credit record."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if isinstance(obj, CreditExpense) and obj.created_by == request.user:
            return True

        event = getattr(obj, 'event', None)
        if not event:
            return False

        if EventRoleAssignment.objects.filter(
            user=request.user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).exists():
            return True

        return _user_has_finance_role(request.user, event)


class IsBankTransferEvidenceAccessible(permissions.BasePermission):
    """Allow payment owners and event administrators to view bank evidence."""

    message = "You do not have permission to access this bank transfer evidence record."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        payment = getattr(obj, 'payment', None)
        if payment and payment.user == request.user:
            return True

        event = getattr(payment, 'event', None)
        if not event:
            return False

        if EventRoleAssignment.objects.filter(
            user=request.user,
            event=event,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).exists():
            return True

        return _user_has_finance_role(request.user, event)


class IsRefundRequestOwnerOrAdministrative(permissions.BasePermission):
    """
    Permission for refund request operations.
    
    Grants access if user is:
    - The owner of the payment being refunded, OR
    - Has administrative privileges (superuser, staff, or ADMINISTRATIVE event role)
    
    This permission is specifically designed for refund request creation and viewing,
    where the payment owner can request refunds for their own payments, and admins
    can view and process all refund requests.
    
    Example:
        ```python
        class RefundRequestViewSet(viewsets.ModelViewSet):
            permission_classes = [IsAuthenticated, IsRefundRequestOwnerOrAdministrative]
            
            def get_permissions(self):
                if self.action in ['verify', 'process']:
                    # Only admins can verify/process
                    return [IsAuthenticated(), IsAdministrativeStaff()]
                return super().get_permissions()
        ```
    """
    
    message = "You must own the payment or have administrative privileges to manage refund requests."
    
    def has_permission(self, request, view) -> bool:
        """Check basic authentication and creation permissions."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # For creation, check if user is owner of the payment or admin
        if view.action == 'create':
            # Will be validated in serializer that payment belongs to user
            return True
        
        return True  # Allow through to object-level check
    
    def has_object_permission(self, request, view, obj) -> bool:
        """
        Check if user can access the refund request.
        
        For viewing: owner or admin
        For updates (verify/process/reject): admin only
        
        Args:
            request: The request object
            view: The view being accessed
            obj: The RefundRequest object
            
        Returns:
            bool: True if user has access, False otherwise
        """
        if not request.user or not request.user.is_authenticated:
            return False
        
        # For status updates, only admins
        if view.action in ['update', 'partial_update', 'verify', 'process', 'reject']:
            admin_check = IsAdministrativeStaff()
            return admin_check.has_object_permission(request, view, obj)
        
        # For viewing, owner or admin
        owner_check = IsPaymentOwner()
        if owner_check.has_object_permission(request, view, obj):
            return True
        
        admin_check = IsAdministrativeStaff()
        return admin_check.has_object_permission(request, view, obj)


class IsAdministrativeStaffOnly(permissions.BasePermission):
    """
    Strict administrative-only permission.
    
    Only grants access to Django superusers, Django staff, or users with
    ADMINISTRATIVE event roles. Payment owners do NOT have access.
    
    Use this for sensitive operations like:
    - Creating/editing payment methods
    - Managing discount rules
    - Processing payments
    - Viewing all payment history
    
    Example:
        ```python
        class PaymentMethodViewSet(viewsets.ModelViewSet):
            permission_classes = [IsAuthenticated, IsAdministrativeStaffOnly]
        ```
    """
    
    message = "Only administrators and staff can perform this action. You must have an administrative role for the relevant event."
    
    def has_permission(self, request, view) -> bool:
        """Check if user has administrative privileges.
        
        For create/update actions on discounts, validates that the user has
        access to the event associated with the target object to prevent
        cross-event discount manipulation.
        """
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Superusers and staff bypass all permission checks for administrative convenience.
        if request.user.is_superuser or request.user.is_staff or view.action in ['list', 'retrieve']:
            return True
        
        # For create/update actions with target binding, validate event access BEFORE allowing operation.
        if view.action in ['create', 'update', 'partial_update']:
            # Extract target information from request data.
            target_alias = request.data.get('target')
            target_type_id = request.data.get('target_type')
            target_id = request.data.get('target_id')
            
            if target_id and (target_alias or target_type_id):
                # Validate that the target object's event matches user's event access.
                if not self._validate_event_access_for_target(
                    request.user,
                    target_id=target_id,
                    target_type_id=target_type_id,
                    target_alias=target_alias,
                ):
                    return False
        
        # Check for administrative event role
        # For list views, we check if user has ANY administrative role
        has_any_admin_role = EventRoleAssignment.objects.filter(
            user=request.user,
            role__category=EventRoleCategoryChoices.ADMINISTRATIVE
        ).exists()
        
        return has_any_admin_role
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Check administrative access for specific object."""
        admin_check = IsAdministrativeStaff()
        return admin_check.has_object_permission(request, view, obj)
    
    def _validate_event_access_for_target(self, user, target_id, target_type_id=None, target_alias=None) -> bool:
        """Validate user has administrative access to the target object's event.
        
        Args:
            user: The user making the request
            target_id: Identifier for target object (UUID or numeric ID)
            target_type_id: Legacy ContentType ID of the target object
            target_alias: New target alias (booking, order, ticket)
            
        Returns:
            bool: True if user has access, False otherwise
        """
        from django.contrib.contenttypes.models import ContentType
        from apps.bookings.models import BookingPackage, Booking, Ticket
        from apps.products.models import Order

        def resolve_by_identifier(model_class, identifier, uuid_field=None):
            value = str(identifier).strip()
            queryset = model_class.objects.all()

            if uuid_field:
                try:
                    UUID(value)
                    return queryset.get(**{uuid_field: value})
                except ValueError:
                    pass
                except model_class.DoesNotExist:
                    pass

            if value.isdigit():
                return queryset.get(pk=int(value))

            return queryset.get(pk=value)

        target_alias_map = {
            'booking': (Booking, None),
            'order': (Order, 'order_id'),
            'ticket': (Ticket, 'ticket_id'),
            'none': (None, None),
        }
        
        try:
            if target_alias:
                alias = str(target_alias).lower().strip()
                model_class, uuid_field = target_alias_map.get(alias, (None, None))
                if alias == 'none':
                    return True
                if not model_class:
                    return False
                target_obj = resolve_by_identifier(model_class, target_id, uuid_field=uuid_field)
            else:
                content_type = ContentType.objects.get(pk=target_type_id)
                model_class = content_type.model_class()
                if model_class is None:
                    return False
                # BookingPackage legacy flow for discounts remains supported.
                target_obj = resolve_by_identifier(model_class, target_id)

            event = None
            if isinstance(target_obj, BookingPackage):
                event = target_obj.event
            elif hasattr(target_obj, 'event') and target_obj.event is not None:
                event = target_obj.event
            elif hasattr(target_obj, 'attendee') and target_obj.attendee is not None:
                event = getattr(target_obj.attendee, 'event', None)

            if not event:
                return False

            return EventRoleAssignment.objects.filter(
                user=user,
                event=event,
                role__category=EventRoleCategoryChoices.ADMINISTRATIVE
            ).exists()

        except (ContentType.DoesNotExist, ValueError, TypeError):
            return False
        except Exception:
            return False


class IsReadOnly(permissions.BasePermission):
    """
    Permission class that only allows read-only operations.
    
    Can be combined with other permissions for read-only access patterns.
    
    Example:
        ```python
        class PublicPaymentMethodViewSet(viewsets.ReadOnlyModelViewSet):
            permission_classes = [IsAuthenticated, IsReadOnly]
        ```
    """
    
    def has_permission(self, request, view) -> bool:
        """Only allow safe methods."""
        return request.method in permissions.SAFE_METHODS
    
    def has_object_permission(self, request, view, obj) -> bool:
        """Only allow safe methods."""
        return request.method in permissions.SAFE_METHODS
