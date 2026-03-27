"""
Model tests for checkout integrity guarantees.

Covers two-phase checkout assumptions at the model/service level:
- Booking and attendee are created during pending-payment finalization
- Attendee remains in pending payment state until verification
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from djmoney.money import Money

from apps.attendee.models import Attendee, AttendeeStatus
from apps.bookings.models import (
    Booking,
    BookingIntent,
    BookingPackage,
    PackageProduct,
    TicketType,
    TicketScopeChoices,
)
from apps.bookings.services.checkout_finalizer import BookingCheckoutFinalizer
from apps.common.models.availability import AvailabilityTypeChoices, AvailabilityWindow
from apps.events.models import (
    Event,
    EventAuthorization,
    EventAuthorizationStatusChoices,
    EventStatusChoices,
    EventType,
)
from apps.locations.models import (
    AreaLocation,
    ChapterLocation,
    ClusterLocation,
    CountryLocation,
    GeneralSectorType,
    SpecificSectorType,
)
from apps.organisations.models import Organisation
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentMethodTypeChoices,
    PaymentStatusChoices,
)

User = get_user_model()


class CheckoutIntegrityModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="checkout-model-user",
            email="checkout-model@example.com",
            password="pass12345",
        )
        self.admin = User.objects.create_user(
            username="checkout-model-admin",
            email="checkout-model-admin@example.com",
            password="pass12345",
            is_staff=True,
        )

        self.event_type = EventType.objects.create(
            title="Conference",
            code="CONF",
            created_by=self.user,
        )
        self.organisation = Organisation.objects.create(
            title="Model Test Org",
            created_by=self.user,
        )
        self.event = Event.objects.create(
            title="Model Integrity Event",
            display_code="MINT",
            display_identifier="MINTCONF001",
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )

        AvailabilityWindow.objects.create(
            name="Registration Window",
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=ContentType.objects.get_for_model(Event),
            target_id=self.event.id,
            available_from=timezone.now() - timedelta(days=1),
            available_to=timezone.now() + timedelta(days=60),
        )

        country = CountryLocation.objects.create(
            country="GB",
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE,
            active=True,
        )
        cluster = ClusterLocation.objects.create(
            cluster_name="Model Cluster",
            country=country,
            active=True,
        )
        chapter = ChapterLocation.objects.create(
            chapter_name="Model Chapter",
            cluster=cluster,
            active=True,
        )
        self.area = AreaLocation.objects.create(
            area_name="Model Area",
            chapter=chapter,
            active=True,
        )

        EventAuthorization.objects.create(
            event=self.event,
            status=EventAuthorizationStatusChoices.APPROVED,
            reviewed_by=self.admin,
        )

        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code="STANDARD",
            title="Standard Ticket",
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.user,
        )
        self.package = BookingPackage.objects.create(
            name="Standard Package",
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(50, "GBP"),
            created_by=self.user,
        )

        self.intent = BookingIntent.objects.create(
            event=self.event,
            intended_ticket_count=1,
            made_by=self.user,
        )

        self.bank_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            title="Bank Transfer",
            is_active=True,
            created_by=self.user,
        )

    def test_finalize_for_bank_transfer_creates_booking_and_attendee(self):
        payment = Payment.objects.create(
            user=self.user,
            event=self.event,
            method=self.bank_method,
            base_amount=Money(50, "GBP"),
            percentage_modifier=Decimal("0.00"),
            description="Model integrity payment",
            status=PaymentStatusChoices.PENDING,
            metadata={
                "checkout_intent_id": str(self.intent.booking_intent_id),
                "checkout_attendees": [
                    {
                        "attendee_id": None,
                        "attendee_draft": {
                            "first_name": "Draft",
                            "last_name": "Model",
                            "date_of_birth": "1990-01-01",
                            "relationship_to_user": "self",
                            "area_from": self.area.id,
                        },
                        "package_id": self.package.id,
                        "product_selections": [],
                    }
                ],
                "booking_finalized": False,
            },
        )

        result = BookingCheckoutFinalizer.finalize_for_bank_transfer(payment, actor=self.user)

        self.assertIn("booking", result)
        booking = result["booking"]
        self.assertIsInstance(booking, Booking)

        payment.refresh_from_db()
        self.assertEqual(payment.target, booking)

        attendees = Attendee.objects.filter(booking=booking)
        self.assertEqual(attendees.count(), 1)
        self.assertEqual(attendees.first().status, AttendeeStatus.PENDING_PAYMENT)
