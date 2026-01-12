"""
Ticket Creator Service

Handles ticket creation from payments after checkout or payment verification.
This service is designed to be called from signals or directly without side effects.
"""
import logging
from typing import List, Dict, Optional
from django.db import transaction
from django.core.exceptions import ValidationError
from djmoney.money import Money

logger = logging.getLogger(__name__)


class TicketCreationError(Exception):
    """Raised when ticket creation fails."""
    pass


class TicketCreatorService:
    """
    Service for creating tickets from completed payments.
    
    This service is stateless and can be safely called from signals or view methods.
    All operations are atomic - either all tickets are created or none are.
    """
    
    @staticmethod
    def create_tickets_for_payment(payment) -> List:
        """
        Create tickets for all attendees in a booking after payment is completed.
        
        This method:
        1. Validates payment status and method
        2. Extracts booking from payment target
        3. Creates tickets for each attendee based on their package selection
        4. Links tickets to payment for refund tracking
        5. Returns list of created tickets
        
        Args:
            payment: Payment instance that has been completed
            
        Returns:
            List of created Ticket instances
            
        Raises:
            TicketCreationError: If tickets cannot be created
            ValidationError: If payment or booking state is invalid
        """
        from apps.payments.models import PaymentStatusChoices, PaymentMethodTypeChoices
        from apps.bookings.models import Booking, Ticket, TicketStatusChoices
        
        # Validate payment status
        if payment.status != PaymentStatusChoices.COMPLETED:
            raise ValidationError(
                f"Cannot create tickets for payment with status {payment.status}. "
                "Payment must be completed."
            )
        
        # Validate payment target is a booking
        if not isinstance(payment.target, Booking):
            raise ValidationError(
                f"Payment target must be a Booking instance, got {type(payment.target).__name__}"
            )
        
        booking = payment.target
        
        # Check if tickets already exist (idempotency)
        existing_tickets = Ticket.objects.filter(payment=payment)
        if existing_tickets.exists():
            logger.info(
                f"Tickets already exist for payment {payment.payment_reference}. "
                f"Found {existing_tickets.count()} tickets. Skipping creation."
            )
            return list(existing_tickets)
        
        # Extract package selections from payment metadata
        package_selections = TicketCreatorService._extract_package_selections(payment)
        
        if not package_selections:
            raise TicketCreationError(
                f"No package selections found in payment {payment.payment_reference} metadata. "
                "Cannot create tickets without package information."
            )
        
        # Create tickets atomically
        created_tickets = []
        try:
            with transaction.atomic():
                for selection in package_selections:
                    # Skip selections with invalid package_id
                    package_id = selection.get('package_id')
                    attendee_id = selection.get('attendee_id')
                    
                    if not package_id:
                        logger.warning(
                            f"Skipping ticket creation for selection with missing package_id: {selection}"
                        )
                        continue
                    
                    if not attendee_id:
                        logger.warning(
                            f"Skipping ticket creation for selection with missing attendee_id: {selection}"
                        )
                        continue
                    
                    ticket = TicketCreatorService._create_ticket_for_attendee(
                        booking=booking,
                        payment=payment,
                        attendee_id=attendee_id,
                        package_id=package_id,
                        frozen_price=selection.get('frozen_price')
                    )
                    created_tickets.append(ticket)
                
                if not created_tickets:
                    raise TicketCreationError(
                        f"No valid tickets could be created from package selections in payment {payment.payment_reference}. "
                        "All selections had missing or invalid data."
                    )
                
                logger.info(
                    f"Successfully created {len(created_tickets)} tickets for "
                    f"payment {payment.payment_reference}, booking {booking.booking_reference}"
                )
        
        except Exception as e:
            logger.error(
                f"Failed to create tickets for payment {payment.payment_reference}: {str(e)}",
                exc_info=True
            )
            raise TicketCreationError(
                f"Failed to create tickets: {str(e)}"
            ) from e
        
        return created_tickets
    
    @staticmethod
    def _extract_package_selections(payment) -> List[Dict]:
        """
        Extract package selections from payment metadata.
        
        Expected metadata structure:
        {
            "attendee_selections": [
                {
                    "attendee_id": "uuid",
                    "package_id": 123,
                    "frozen_price": "10.00",
                    "currency": "GBP"
                }
            ]
        }
        
        Args:
            payment: Payment instance
            
        Returns:
            List of selection dicts with attendee_id, package_id, frozen_price
        """
        metadata = payment.metadata or {}
        selections = metadata.get('attendee_selections', [])
        
        if not selections:
            # Fallback: try to extract from old format (attendee_breakdown)
            breakdown = metadata.get('attendee_breakdown', {})
            selections = []
            for key, data in breakdown.items():
                if isinstance(data, dict):
                    selections.append({
                        'attendee_id': data.get('attendee_id'),
                        'package_id': data.get('package_id'),
                        'frozen_price': data.get('amount'),
                        'currency': data.get('currency', 'GBP')
                    })
        
        return selections
    
    @staticmethod
    def _create_ticket_for_attendee(
        booking,
        payment,
        attendee_id: str,
        package_id: int,
        frozen_price: Optional[str] = None
    ):
        """
        Create a single ticket for an attendee.
        
        Args:
            booking: Booking instance
            payment: Payment instance
            attendee_id: UUID of the attendee
            package_id: ID of the booking package
            frozen_price: Frozen price amount as string (optional)
            
        Returns:
            Created Ticket instance
            
        Raises:
            ValidationError: If attendee or package not found, or validation fails
        """
        from apps.bookings.models import Ticket, TicketStatusChoices, BookingPackage
        from apps.attendee.models import Attendee
        from core.utils.display import generate_human_readable_id
        
        # Fetch attendee
        try:
            attendee = Attendee.objects.get(attendee_id=attendee_id, booking=booking)
        except Attendee.DoesNotExist:
            raise ValidationError(
                f"Attendee {attendee_id} not found in booking {booking.booking_reference}"
            )
        
        # Fetch package
        try:
            package = BookingPackage.objects.get(id=package_id, event=booking.event)
        except BookingPackage.DoesNotExist:
            raise ValidationError(
                f"Booking package {package_id} not found for event {booking.event.id}"
            )
        
        # Generate unique ticket code
        ticket_code = generate_human_readable_id(
            50,
            'TKT',
            str(booking.event.display_code),
            str(attendee.first_name[:3].upper())
        )
        
        # Create ticket
        ticket = Ticket(
            ticket_type=package.ticket_type,
            attendee=attendee,
            package=package,
            payment=payment,
            status=TicketStatusChoices.ACTIVE,
            ticket_code=ticket_code,
            uses=1
        )
        
        ticket.full_clean()
        ticket.save()
        
        logger.debug(
            f"Created ticket {ticket.ticket_code} for attendee {attendee.full_name}, "
            f"package {package.name}"
        )
        
        return ticket
    
    @staticmethod
    def should_create_tickets_for_payment(payment) -> bool:
        """
        Determine if tickets should be created for a payment based on its method and status.
        
        Rules:
        - STRIPE: Create after payment completes (webhook confirms)
        - BANK_TRANSFER: Do NOT auto-create, requires manual admin verification
        - CASH: Create immediately on completion
        - FREE: Create immediately on completion
        
        Args:
            payment: Payment instance
            
        Returns:
            bool: True if tickets should be created automatically
        """
        from apps.payments.models import PaymentStatusChoices, PaymentMethodTypeChoices
        
        # Must be completed
        if payment.status != PaymentStatusChoices.COMPLETED:
            return False
        
        # Must have a method
        if not payment.method:
            return False
        
        # Do NOT auto-create for bank transfers (requires manual verification)
        if payment.method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER:
            return False
        
        # Auto-create for all other completed payments
        return True
