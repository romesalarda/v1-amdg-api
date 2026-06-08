from django.contrib.auth import get_user_model

User = get_user_model()

class PurchaseContextMixin:
    """Resolve optional attendee/customer context for serializer output enrichment."""

    def _user_has_attendee_access(self, attendee, user):
        if user.is_superuser or user.is_staff:
            return True

        attendee_owner_match = attendee.user_id == user.id
        attendee_booking_match = bool(
            attendee.booking_id and attendee.booking and attendee.booking.made_by_id == user.id
        )
        return attendee_owner_match or attendee_booking_match

    def _resolve_effective_customer(self):
        request_user = self.request.user
        customer_id = self.request.query_params.get('customer_id')

        if not customer_id or not (request_user.is_superuser or request_user.is_staff):
            return request_user

        try:
            return User.objects.get(pk=customer_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return request_user

    def _resolve_attendee_context(self, effective_customer):
        '''
        Resolve an optional attendee context based on the 'attendee_id' query parameter and the effective customer. 

        :param effective_customer: The effective customer resolved from the request.

        Returns:
        - attendee: The resolved Attendee instance or None if not found/accessible.
        - context_enabled: Boolean indicating whether a valid attendee context was resolved.
        - context_attendee: The resolved Attendee instance or None if not found/accessible.
        '''

        from apps.attendee.models import Attendee

        attendee_id = self.request.query_params.get('attendee_id')
        if not attendee_id:
            return None, False


        attendee = (
            Attendee.objects
            .select_related('booking', 'event', 'user')
            .filter(attendee_id=attendee_id)
            .first()
        )
        if attendee is None:
            return None, False

        if not self._user_has_attendee_access(attendee, effective_customer):
            return None, False

        requested_customer = self.request.query_params.get('customer_id')
        if requested_customer and (self.request.user.is_superuser or self.request.user.is_staff):
            attendee_owner_match = attendee.user_id == effective_customer.id
            attendee_booking_match = bool(
                attendee.booking_id and attendee.booking and attendee.booking.made_by_id == effective_customer.id
            )
            if not attendee_owner_match and not attendee_booking_match:
                return None, False

        return attendee, True

    def _build_purchase_context(self):
        effective_customer = self._resolve_effective_customer()
        attendee, context_enabled = self._resolve_attendee_context(effective_customer)
        return {
            'context_enabled': context_enabled,
            'context_customer': effective_customer,
            'context_attendee': attendee,
        }
