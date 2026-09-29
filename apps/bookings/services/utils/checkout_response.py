"""Builds the JSON response payload returned by the booking checkout endpoint."""
import typing
from decimal import Decimal

from rest_framework.request import Request

from apps.bookings.models import Booking
from apps.payments.models import Payment, PaymentMethodTypeChoices, BankTransferEvidence
from apps.products.models import Order
from apps.bookings.models.ticket import Ticket


class CheckoutResponseBuilder:
    """Formats the checkout endpoint's response body."""

    @staticmethod
    def build(
        request: Request,
        payment_obj: Payment,
        status_label: str,
        message: str,
        booking: typing.Optional[Booking] = None,
        stripe_client_secret: typing.Optional[str] = None,
        bank_transfer_evidence: typing.Optional[BankTransferEvidence] = None,
    ) -> typing.Dict[str, typing.Any]:
        """
        Build a structured response for the checkout endpoint.

        Args:
            request: The originating request, used to build absolute URIs.
            payment_obj: The Payment object associated with the checkout.
            status_label: A string indicating the status of the checkout (e.g., 'confirmed', 'pending_payment').
            message: A human-readable message describing the checkout result.
            booking: Optional Booking object if a booking was created.
            stripe_client_secret: Optional client secret for Stripe payments.
            bank_transfer_evidence: Optional BankTransferEvidence object if applicable.

        Returns:
            A dictionary containing the checkout response data.
        """
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
