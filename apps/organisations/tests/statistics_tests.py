"""
Organisation statistics API tests.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from djmoney.money import Money
from rest_framework import status
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventStatusChoices, EventType
from apps.locations.models import AreaLocation, ChapterLocation
from apps.organisations.models import (
    EventSponsorPackage,
    Leader,
    Organisation,
    OrganisationControl,
    UserOrganisationMembership,
)
from apps.payments.models import Payment, PaymentStatusChoices
from apps.payments.models.donations import Donation

User = get_user_model()


class OrganisationStatisticsAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.superuser = User.objects.create_superuser(
            email="super@example.com",
            password="pass123",
        )
        self.controller = User.objects.create_user(
            email="controller@example.com",
            password="pass123",
        )
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="pass123",
        )

        self.org1 = Organisation.objects.create(title="Org 1", created_by=self.superuser)
        self.org2 = Organisation.objects.create(title="Org 2", created_by=self.superuser)

        OrganisationControl.objects.create(
            organisation=self.org1,
            user=self.controller,
            added_by=self.superuser,
        )

        UserOrganisationMembership.objects.create(
            organisation=self.org1,
            user=self.controller,
            added_by=self.superuser,
            verified_at=timezone.now(),
        )
        UserOrganisationMembership.objects.create(
            organisation=self.org1,
            user=self.outsider,
            added_by=self.superuser,
        )

        event_type = EventType.objects.create(
            title="Conference",
            code="CONF",
            created_by=self.superuser,
        )

        now = timezone.now()
        self.org1_event_open = Event.objects.create(
            title="Org1 Open",
            display_code="ORG1OPN",
            display_identifier="ORG1OPN-1",
            status=EventStatusChoices.OPEN,
            created_by=self.superuser,
            event_type=event_type,
            start_datetime=now + timedelta(days=2),
            end_datetime=now + timedelta(days=3),
            organisation=self.org1,
        )
        self.org1_event_completed = Event.objects.create(
            title="Org1 Completed",
            display_code="ORG1CMP",
            display_identifier="ORG1CMP-1",
            status=EventStatusChoices.COMPLETED,
            created_by=self.superuser,
            event_type=event_type,
            start_datetime=now - timedelta(days=10),
            end_datetime=now - timedelta(days=9),
            organisation=self.org1,
        )
        self.org2_event = Event.objects.create(
            title="Org2 Event",
            display_code="ORG2EVT",
            display_identifier="ORG2EVT-1",
            status=EventStatusChoices.OPEN,
            created_by=self.superuser,
            event_type=event_type,
            start_datetime=now + timedelta(days=5),
            end_datetime=now + timedelta(days=6),
            organisation=self.org2,
        )

        # Attendees on org1 events
        from apps.attendee.models import Attendee

        Attendee.objects.create(
            first_name="A",
            last_name="One",
            email="a1@example.com",
            event=self.org1_event_open,
            date_of_birth=timezone.now().date() - timedelta(days=30 * 365),
            user=self.controller,
            defined_by=self.controller,
        )
        Attendee.objects.create(
            first_name="A",
            last_name="Two",
            email="a2@example.com",
            event=self.org1_event_completed,
            date_of_birth=timezone.now().date() - timedelta(days=28 * 365),
            user=self.controller,
            defined_by=self.controller,
        )

        booking_ct = ContentType.objects.get_for_model(Booking)
        sponsor_pkg = EventSponsorPackage.objects.create(
            event=self.org1_event_open,
            package_name="Gold",
            base_amount=Money(250, "GBP"),
            tier=1,
        )
        sponsor_ct = ContentType.objects.get_for_model(EventSponsorPackage)
        donation_ct = ContentType.objects.get_for_model(Donation)

        booking_payment = Payment.objects.create(
            user=self.controller,
            event=self.org1_event_open,
            base_amount=Money(100, "GBP"),
            status=PaymentStatusChoices.COMPLETED,
            target_type=booking_ct,
            target_id="1",
        )
        donation_payment = Payment.objects.create(
            user=self.controller,
            event=self.org1_event_open,
            base_amount=Money(50, "GBP"),
            status=PaymentStatusChoices.COMPLETED,
            target_type=donation_ct,
            target_id="1",
        )
        Payment.objects.create(
            user=self.controller,
            event=self.org1_event_completed,
            base_amount=Money(200, "GBP"),
            status=PaymentStatusChoices.COMPLETED,
            target_type=sponsor_ct,
            target_id=str(sponsor_pkg.pk),
        )

        Donation.objects.create(
            amount=Money(50, "GBP"),
            donated_by=self.controller,
            payment=donation_payment,
            verification_status=VerificationStatus.VERIFIED,
        )

        # Leaders for org1 only
        area_ct = ContentType.objects.get_for_model(AreaLocation)
        chapter_ct = ContentType.objects.get_for_model(ChapterLocation)
        Leader.objects.create(
            user=self.controller,
            organisation=self.org1,
            target_type=area_ct,
            target_id=101,
            added_by=self.superuser,
        )
        Leader.objects.create(
            user=self.superuser,
            organisation=self.org1,
            target_type=chapter_ct,
            target_id=202,
            added_by=self.superuser,
        )

        # Non-scoped payment for org2 to ensure filtering works
        Payment.objects.create(
            user=self.superuser,
            event=self.org2_event,
            base_amount=Money(999, "GBP"),
            status=PaymentStatusChoices.COMPLETED,
            target_type=booking_ct,
            target_id="2",
        )

    def test_overview_scoped_to_controller_organisations(self):
        self.client.force_authenticate(user=self.controller)
        url = reverse("organisations:organisationstatistics-overview")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_events"], 2)
        self.assertEqual(response.data["total_attendees"], 2)
        self.assertEqual(response.data["total_members"], 2)
        self.assertEqual(response.data["total_revenue"], 350.0)

    def test_leader_distribution_returns_all_location_type_buckets_present(self):
        self.client.force_authenticate(user=self.controller)
        url = reverse("organisations:organisationstatistics-leaders-distribution")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_leaders"], 2)
        labels = {item["label"] for item in response.data["distribution"]}
        self.assertIn("Area", labels)
        self.assertIn("Chapter", labels)

    def test_non_controller_cannot_request_uncontrolled_organisation(self):
        self.client.force_authenticate(user=self.outsider)
        url = reverse("organisations:organisationstatistics-overview")

        response = self.client.get(url, {"organisation_id": self.org1.id})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_can_request_specific_organisation(self):
        self.client.force_authenticate(user=self.superuser)
        url = reverse("organisations:organisationstatistics-overview")

        response = self.client.get(url, {"organisation_id": self.org2.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_events"], 1)
        self.assertEqual(response.data["total_revenue"], 999.0)
