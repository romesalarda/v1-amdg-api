"""
Model tests for the workshops app.

Covers:
- Workshop status transitions and property behaviour
- AllocationMode choices
- WorkshopRegistration status, booking_reference auto-generation, and attendee FK
- WorkshopInterestSubmission uniqueness and finalise logic
- WorkshopInterestRank ordering and clean() validation
- WorkshopStaff event-consistency validation
"""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.events.models import Event, EventType, EventStatusChoices, EventStaff, EventVenue
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.workshops.models.workshop import Workshop, WorkshopStatus, AllocationMode
from apps.workshops.models.registration import WorkshopRegistration, WorkshopRegistrationStatus
from apps.workshops.models.interest import WorkshopInterestSubmission, WorkshopInterestRank
from apps.workshops.models.staff import WorkshopStaff, WorkshopStaffRoleChoice

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_user(username, **kwargs):
    return User.objects.create_user(
        username=username,
        email=f'{username}@test.com',
        password='testpass123',
        **kwargs,
    )


def make_event(created_by, suffix='001'):
    event_type, _ = EventType.objects.get_or_create(
        code=f'T{suffix}',
        defaults={'title': f'Type {suffix}', 'created_by': created_by},
    )
    org, _ = Organisation.objects.get_or_create(
        title=f'Org {suffix}',
        defaults={'created_by': created_by},
    )
    return Event.objects.create(
        title=f'Test Event {suffix}',
        display_code=f'TE{suffix}',
        created_by=created_by,
        event_type=event_type,
        start_datetime=timezone.now() + timedelta(days=30),
        end_datetime=timezone.now() + timedelta(days=32),
        status=EventStatusChoices.OPEN,
        organisation=org,
    )


def make_attendee(user, event):
    return Attendee.objects.create(
        user=user,
        first_name='Jane',
        last_name='Doe',
        email=user.email,
        date_of_birth=date(1995, 6, 1),
        relationship_to_user=AttendeeRelationship.SELF,
        event=event,
        defined_by=user,
    )


def make_workshop(event, title='Test Workshop', status=WorkshopStatus.OPEN, capacity=10):
    return Workshop.objects.create(
        title=title,
        description='A test workshop',
        event=event,
        date=timezone.now() + timedelta(days=31),
        status=status,
        capacity=capacity,
        allocation_mode=AllocationMode.FCFS,
    )


# ---------------------------------------------------------------------------
# Workshop model tests
# ---------------------------------------------------------------------------

class WorkshopModelTest(TestCase):

    def setUp(self):
        self.user = make_user('wsuser')
        self.event = make_event(self.user)

    def test_str_representation(self):
        workshop = make_workshop(self.event, title='Art Workshop')
        self.assertIn('Art Workshop', str(workshop))

    def test_default_status_is_draft(self):
        workshop = Workshop.objects.create(
            title='Draft WS',
            description='desc',
            event=self.event,
            date=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(workshop.status, WorkshopStatus.DRAFT)

    def test_default_allocation_mode_is_fcfs(self):
        workshop = Workshop.objects.create(
            title='FCFS WS',
            description='desc',
            event=self.event,
            date=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(workshop.allocation_mode, AllocationMode.FCFS)

    def test_is_full_with_unlimited_capacity(self):
        workshop = Workshop.objects.create(
            title='Unlimited',
            description='desc',
            event=self.event,
            date=timezone.now() + timedelta(days=1),
            capacity=None,
        )
        self.assertFalse(workshop.is_full)

    def test_is_full_when_at_capacity(self):
        workshop = make_workshop(self.event, capacity=1)
        attendee = make_attendee(self.user, self.event)
        WorkshopRegistration.objects.create(
            workshop=workshop,
            attendee=attendee,
            status=WorkshopRegistrationStatus.CONFIRMED,
        )
        self.assertTrue(workshop.is_full)

    def test_current_registration_count_only_counts_confirmed(self):
        workshop = make_workshop(self.event, capacity=5)
        attendee1 = make_attendee(self.user, self.event)

        user2 = make_user('wsuser2')
        attendee2 = make_attendee(user2, self.event)

        WorkshopRegistration.objects.create(
            workshop=workshop, attendee=attendee1,
            status=WorkshopRegistrationStatus.CONFIRMED,
        )
        WorkshopRegistration.objects.create(
            workshop=workshop, attendee=attendee2,
            status=WorkshopRegistrationStatus.WAITLISTED,
        )
        self.assertEqual(workshop.current_registration_count, 1)

    def test_clean_raises_when_registration_window_inverted(self):
        workshop = Workshop(
            title='Bad Window',
            description='desc',
            event=self.event,
            date=timezone.now() + timedelta(days=1),
            registration_opens_at=timezone.now() + timedelta(days=2),
            registration_closes_at=timezone.now() + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            workshop.clean()

    def test_ordering_by_date(self):
        ws1 = Workshop.objects.create(
            title='Second',
            description='d',
            event=self.event,
            date=timezone.now() + timedelta(days=5),
        )
        ws2 = Workshop.objects.create(
            title='First',
            description='d',
            event=self.event,
            date=timezone.now() + timedelta(days=2),
        )
        workshops = list(Workshop.objects.filter(event=self.event))
        self.assertEqual(workshops[0].pk, ws2.pk)
        self.assertEqual(workshops[1].pk, ws1.pk)


# ---------------------------------------------------------------------------
# WorkshopRegistration model tests
# ---------------------------------------------------------------------------

class WorkshopRegistrationModelTest(TestCase):

    def setUp(self):
        self.user = make_user('reguser')
        self.event = make_event(self.user, suffix='002')
        self.attendee = make_attendee(self.user, self.event)
        self.workshop = make_workshop(self.event, capacity=10)

    def test_booking_reference_auto_generated(self):
        reg = WorkshopRegistration.objects.create(
            workshop=self.workshop,
            attendee=self.attendee,
        )
        self.assertIsNotNone(reg.booking_reference)
        self.assertTrue(reg.booking_reference.startswith('wrk-'))

    def test_booking_reference_preserved_when_provided(self):
        reg = WorkshopRegistration.objects.create(
            workshop=self.workshop,
            attendee=self.attendee,
            booking_reference='WRK-CUSTOM-001',
        )
        self.assertEqual(reg.booking_reference, 'WRK-CUSTOM-001')

    def test_default_status_is_confirmed(self):
        reg = WorkshopRegistration.objects.create(
            workshop=self.workshop,
            attendee=self.attendee,
        )
        self.assertEqual(reg.status, WorkshopRegistrationStatus.CONFIRMED)

    def test_duplicate_registration_raises_integrity_error(self):
        WorkshopRegistration.objects.create(
            workshop=self.workshop,
            attendee=self.attendee,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            WorkshopRegistration.objects.create(
                workshop=self.workshop,
                attendee=self.attendee,
            )

    def test_str_representation_includes_status(self):
        reg = WorkshopRegistration.objects.create(
            workshop=self.workshop,
            attendee=self.attendee,
            status=WorkshopRegistrationStatus.WAITLISTED,
        )
        self.assertIn('Waitlisted', str(reg))

    def test_attendee_fk_is_attendee_model(self):
        """Confirm attendee FK points to the Attendee model, not User."""
        reg = WorkshopRegistration.objects.create(
            workshop=self.workshop,
            attendee=self.attendee,
        )
        self.assertIsInstance(reg.attendee, Attendee)


# ---------------------------------------------------------------------------
# WorkshopInterestSubmission & Rank model tests
# ---------------------------------------------------------------------------

class WorkshopInterestSubmissionModelTest(TestCase):

    def setUp(self):
        self.user = make_user('intuser')
        self.event = make_event(self.user, suffix='003')
        self.attendee = make_attendee(self.user, self.event)
        self.ws1 = make_workshop(self.event, title='WS 1')
        self.ws2 = make_workshop(self.event, title='WS 2')

    def test_create_submission_with_ranks(self):
        submission = WorkshopInterestSubmission.objects.create(
            event=self.event,
            attendee=self.attendee,
        )
        WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws1, rank=1)
        WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws2, rank=2)
        self.assertEqual(submission.ranks.count(), 2)

    def test_submission_unique_per_attendee_event(self):
        WorkshopInterestSubmission.objects.create(
            event=self.event,
            attendee=self.attendee,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            WorkshopInterestSubmission.objects.create(
                event=self.event,
                attendee=self.attendee,
            )

    def test_rank_ordering_ascending(self):
        submission = WorkshopInterestSubmission.objects.create(
            event=self.event,
            attendee=self.attendee,
        )
        WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws2, rank=2)
        WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws1, rank=1)
        ranks = list(submission.ranks.all())
        self.assertEqual(ranks[0].rank, 1)
        self.assertEqual(ranks[1].rank, 2)

    def test_duplicate_rank_value_raises_integrity_error(self):
        submission = WorkshopInterestSubmission.objects.create(
            event=self.event,
            attendee=self.attendee,
        )
        WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws1, rank=1)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws2, rank=1)

    def test_duplicate_workshop_in_submission_raises_integrity_error(self):
        user2 = make_user('intuser2')
        attendee2 = make_attendee(user2, self.event)
        submission = WorkshopInterestSubmission.objects.create(
            event=self.event,
            attendee=attendee2,
        )
        WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws1, rank=1)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            WorkshopInterestRank.objects.create(submission=submission, workshop=self.ws1, rank=2)

    def test_rank_clean_validates_workshop_belongs_to_event(self):
        other_user = make_user('other_intuser')
        other_event = make_event(other_user, suffix='999')
        other_ws = make_workshop(other_event, title='Other WS')
        submission = WorkshopInterestSubmission.objects.create(
            event=self.event,
            attendee=self.attendee,
        )
        rank = WorkshopInterestRank(submission=submission, workshop=other_ws, rank=1)
        with self.assertRaises(ValidationError):
            rank.clean()

    def test_is_finalised_defaults_false(self):
        submission = WorkshopInterestSubmission.objects.create(
            event=self.event,
            attendee=self.attendee,
        )
        self.assertFalse(submission.is_finalised)


# ---------------------------------------------------------------------------
# WorkshopStaff model tests
# ---------------------------------------------------------------------------

class WorkshopStaffModelTest(TestCase):

    def setUp(self):
        self.admin = make_user('staffadmin', is_staff=True)
        self.event = make_event(self.admin, suffix='004')
        self.workshop = make_workshop(self.event)
        self.event_staff_user = make_user('staffmember')
        self.event_staff = EventStaff.objects.create(
            event=self.event,
            user=self.event_staff_user,
        )

    def test_create_staff_assignment(self):
        ws_staff = WorkshopStaff.objects.create(
            workshop=self.workshop,
            event_staff=self.event_staff,
            role=WorkshopStaffRoleChoice.INSTRUCTOR,
            added_by=self.admin,
        )
        self.assertEqual(ws_staff.role, WorkshopStaffRoleChoice.INSTRUCTOR)

    def test_clean_rejects_staff_from_different_event(self):
        other_admin = make_user('other_staffadmin')
        other_event = make_event(other_admin, suffix='005')
        other_event_staff = EventStaff.objects.create(
            event=other_event,
            user=other_admin,
        )
        ws_staff = WorkshopStaff(
            workshop=self.workshop,
            event_staff=other_event_staff,
            role=WorkshopStaffRoleChoice.ASSISTANT,
        )
        with self.assertRaises(ValidationError):
            ws_staff.clean()

    def test_duplicate_staff_assignment_raises_integrity_error(self):
        WorkshopStaff.objects.create(
            workshop=self.workshop,
            event_staff=self.event_staff,
            role=WorkshopStaffRoleChoice.LEADER,
            added_by=self.admin,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            WorkshopStaff.objects.create(
                workshop=self.workshop,
                event_staff=self.event_staff,
                role=WorkshopStaffRoleChoice.ASSISTANT,
                added_by=self.admin,
            )
