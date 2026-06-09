"""
API tests for the workshops app.

Tests cover:
- Workshop CRUD endpoints
- Open/close registration and run_allocation custom actions
- WorkshopRegistration CRUD + confirm / cancel / promote_from_waitlist actions
- WorkshopInterestSubmission CRUD + finalise / unfinalize actions
- WorkshopStaff CRUD
- Permission enforcement (anon, regular user, event staff)
- Allocation service integration via API
"""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.events.models import Event, EventType, EventStatusChoices, EventStaff
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.workshops.models.workshop import Workshop, WorkshopStatus, AllocationMode
from apps.workshops.models.registration import WorkshopRegistration, WorkshopRegistrationStatus
from apps.workshops.models.interest import WorkshopInterestSubmission, WorkshopInterestRank
from apps.workshops.models.staff import WorkshopStaff, WorkshopStaffRoleChoice

User = get_user_model()

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
WORKSHOPS_URL = '/api/workshops/list/'
REGISTRATIONS_URL = '/api/workshops/registrations/'
INTEREST_URL = '/api/workshops/interest-submissions/'
STAFF_URL = '/api/workshops/staff/'


def ws_detail(pk):
    return f'{WORKSHOPS_URL}{pk}/'


def reg_detail(pk):
    return f'{REGISTRATIONS_URL}{pk}/'


def interest_detail(pk):
    return f'{INTEREST_URL}{pk}/'


def staff_detail(pk):
    return f'{STAFF_URL}{pk}/'


# ---------------------------------------------------------------------------
# Shared setup base class
# ---------------------------------------------------------------------------

class BaseWorkshopTestCase(APITestCase):
    """
    Base test case providing a fully wired event, attendee, and workshop,
    with an admin user (event owner), a regular event staff user, and an
    ordinary attendee user.
    """

    def setUp(self):
        self.client = APIClient()

        # Users
        self.admin = User.objects.create_user(
            username='ws_admin', email='wsadmin@test.com',
            password='testpass123', is_staff=True, is_superuser=True,
        )
        self.staff_user = User.objects.create_user(
            username='ws_staff', email='wsstaff@test.com', password='testpass123',
        )
        self.regular_user = User.objects.create_user(
            username='ws_regular', email='wsregular@test.com', password='testpass123',
        )
        self.attendee_user = User.objects.create_user(
            username='ws_attendee', email='wsattendee@test.com', password='testpass123',
        )

        # Organisation & Event
        self.org = Organisation.objects.create(title='WS Org', created_by=self.admin)
        self.event_type = EventType.objects.create(
            title='Workshop Event', code='WSEVT', created_by=self.admin,
        )
        self.event = Event.objects.create(
            title='Workshop Test Event',
            display_code='WTE001',
            created_by=self.admin,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.org,
        )

        # Make staff_user an event staff member
        self.event_staff = EventStaff.objects.create(event=self.event, user=self.staff_user)

        # Attendees
        self.attendee = Attendee.objects.create(
            user=self.attendee_user,
            first_name='Alice',
            last_name='Test',
            email=self.attendee_user.email,
            date_of_birth=date(1995, 1, 1),
            relationship_to_user=AttendeeRelationship.SELF,
            event=self.event,
            defined_by=self.admin,
        )

        # A second attendee for multi-person tests
        self.user2 = User.objects.create_user(
            username='ws_attendee2', email='wsattendee2@test.com', password='testpass123',
        )
        self.attendee2 = Attendee.objects.create(
            user=self.user2,
            first_name='Bob',
            last_name='Test',
            email=self.user2.email,
            date_of_birth=date(1996, 2, 2),
            relationship_to_user=AttendeeRelationship.SELF,
            event=self.event,
            defined_by=self.admin,
        )

        # Workshop
        self.workshop = Workshop.objects.create(
            title='Photography 101',
            description='Basic photography workshop.',
            event=self.event,
            date=timezone.now() + timedelta(days=31),
            status=WorkshopStatus.OPEN,
            capacity=5,
            allocation_mode=AllocationMode.FCFS,
        )

    # -- Auth shortcuts -------------------------------------------------------

    def auth_admin(self):
        self.client.force_authenticate(user=self.admin)

    def auth_staff(self):
        self.client.force_authenticate(user=self.staff_user)

    def auth_regular(self):
        self.client.force_authenticate(user=self.regular_user)

    def auth_attendee(self):
        self.client.force_authenticate(user=self.attendee_user)

    def unauth(self):
        self.client.force_authenticate(user=None)

    # -- Data helpers ---------------------------------------------------------

    def create_registration(self, attendee=None, status_val=WorkshopRegistrationStatus.CONFIRMED):
        attendee = attendee or self.attendee
        return WorkshopRegistration.objects.create(
            workshop=self.workshop,
            attendee=attendee,
            status=status_val,
        )


# ===========================================================================
# Workshop CRUD
# ===========================================================================

class WorkshopListCreateTest(BaseWorkshopTestCase):

    def test_list_unauthenticated_returns_401(self):
        self.unauth()
        response = self.client.get(WORKSHOPS_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_authenticated_returns_200(self):
        self.auth_regular()
        response = self.client.get(WORKSHOPS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)

    def test_create_as_admin_returns_201(self):
        self.auth_admin()
        payload = {
            'title': 'New Workshop',
            'description': 'A brand new workshop.',
            'event': self.event.pk,
            'date': (timezone.now() + timedelta(days=35)).isoformat(),
            'status': WorkshopStatus.DRAFT,
            'allocation_mode': AllocationMode.FCFS,
            'capacity': 20,
        }
        response = self.client.post(WORKSHOPS_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Workshop.objects.filter(title='New Workshop').count(), 1)

    def test_filter_by_event(self):
        self.auth_regular()
        response = self.client.get(WORKSHOPS_URL, {'event': self.event.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.data['results']:
            self.assertEqual(item['event'], self.event.pk)

    def test_filter_by_status(self):
        Workshop.objects.create(
            title='Draft WS', description='d', event=self.event,
            date=timezone.now() + timedelta(days=2), status=WorkshopStatus.DRAFT,
        )
        self.auth_regular()
        response = self.client.get(WORKSHOPS_URL, {'status': WorkshopStatus.DRAFT})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.data['results']:
            self.assertEqual(item['status'], WorkshopStatus.DRAFT)


class WorkshopDetailTest(BaseWorkshopTestCase):

    def test_retrieve_returns_200(self):
        self.auth_regular()
        response = self.client.get(ws_detail(self.workshop.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], self.workshop.title)
        self.assertIn('_links', response.data)

    def test_partial_update_as_admin(self):
        self.auth_admin()
        response = self.client.patch(ws_detail(self.workshop.pk), {'capacity': 99}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.capacity, 99)

    def test_delete_as_admin(self):
        self.auth_admin()
        ws = Workshop.objects.create(
            title='To Delete', description='d', event=self.event,
            date=timezone.now() + timedelta(days=2), status=WorkshopStatus.DRAFT,
        )
        response = self.client.delete(ws_detail(ws.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Workshop.objects.filter(pk=ws.pk).exists())


class WorkshopStatusTransitionTest(BaseWorkshopTestCase):

    def test_open_registrations(self):
        self.workshop.status = WorkshopStatus.DRAFT
        self.workshop.save()
        self.auth_admin()
        response = self.client.post(f'{ws_detail(self.workshop.pk)}open-registrations/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.status, WorkshopStatus.OPEN)

    def test_close_registrations(self):
        self.auth_admin()
        response = self.client.post(f'{ws_detail(self.workshop.pk)}close-registrations/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.status, WorkshopStatus.CLOSED)

    def test_open_cancelled_workshop_returns_400(self):
        self.workshop.status = WorkshopStatus.CANCELLED
        self.workshop.save()
        self.auth_admin()
        response = self.client.post(f'{ws_detail(self.workshop.pk)}open-registrations/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class WorkshopAllocationActionTest(BaseWorkshopTestCase):

    def test_run_allocation_fcfs_returns_no_op(self):
        self.auth_admin()
        response = self.client.post(f'{ws_detail(self.workshop.pk)}run-allocation/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('nothing to do', response.data.get('detail', '').lower())

    def test_run_random_allocation(self):
        self.workshop.allocation_mode = AllocationMode.RANDOM
        self.workshop.save()
        WorkshopRegistration.objects.create(
            workshop=self.workshop, attendee=self.attendee,
            status=WorkshopRegistrationStatus.PENDING_ALLOCATION,
        )
        self.auth_admin()
        response = self.client.post(f'{ws_detail(self.workshop.pk)}run-allocation/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('confirmed', response.data)
        self.assertIn('waitlisted', response.data)

    def test_run_allocation_requires_staff_permission(self):
        self.auth_regular()
        response = self.client.post(f'{ws_detail(self.workshop.pk)}run-allocation/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_nested_registrations_list(self):
        self.create_registration()
        self.auth_regular()
        response = self.client.get(f'{ws_detail(self.workshop.pk)}registrations/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_nested_registrations_filter_by_status(self):
        self.create_registration(status_val=WorkshopRegistrationStatus.CONFIRMED)
        self.create_registration(attendee=self.attendee2,
                                 status_val=WorkshopRegistrationStatus.WAITLISTED)
        self.auth_regular()
        response = self.client.get(
            f'{ws_detail(self.workshop.pk)}registrations/?registration_status=CONFIRMED'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for reg in response.data['results']:
            self.assertEqual(reg['status'], WorkshopRegistrationStatus.CONFIRMED)


# ===========================================================================
# WorkshopRegistration CRUD + actions
# ===========================================================================

class WorkshopRegistrationCRUDTest(BaseWorkshopTestCase):

    def test_list_registrations(self):
        self.create_registration()
        self.auth_regular()
        response = self.client.get(REGISTRATIONS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)

    def test_retrieve_registration(self):
        reg = self.create_registration()
        self.auth_regular()
        response = self.client.get(reg_detail(reg.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)

    def test_create_registration_fcfs_sets_confirmed(self):
        self.auth_admin()
        payload = {
            'workshop': str(self.workshop.pk),
            'attendee': str(self.attendee.pk),
        }
        response = self.client.post(REGISTRATIONS_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        reg = WorkshopRegistration.objects.get(
            workshop=self.workshop, attendee=self.attendee
        )
        self.assertEqual(reg.status, WorkshopRegistrationStatus.CONFIRMED)

    def test_create_registration_when_full_sets_waitlisted(self):
        self.workshop.capacity = 1
        self.workshop.save()
        # Fill the spot
        WorkshopRegistration.objects.create(
            workshop=self.workshop, attendee=self.attendee2,
            status=WorkshopRegistrationStatus.CONFIRMED,
        )
        self.auth_admin()
        payload = {
            'workshop': str(self.workshop.pk),
            'attendee': str(self.attendee.pk),
        }
        response = self.client.post(REGISTRATIONS_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        reg = WorkshopRegistration.objects.get(
            workshop=self.workshop, attendee=self.attendee
        )
        self.assertEqual(reg.status, WorkshopRegistrationStatus.WAITLISTED)

    def test_duplicate_registration_returns_400(self):
        self.auth_admin()
        payload = {'workshop': str(self.workshop.pk), 'attendee': str(self.attendee.pk)}
        self.client.post(REGISTRATIONS_URL, payload, format='json')
        # Second attempt
        response = self.client.post(REGISTRATIONS_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_registrations_by_status(self):
        self.create_registration(status_val=WorkshopRegistrationStatus.CONFIRMED)
        self.auth_regular()
        response = self.client.get(REGISTRATIONS_URL, {'status': 'CONFIRMED'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.data['results']:
            self.assertEqual(item['status'], 'CONFIRMED')


class WorkshopRegistrationActionsTest(BaseWorkshopTestCase):

    def test_confirm_waitlisted_registration(self):
        reg = self.create_registration(status_val=WorkshopRegistrationStatus.WAITLISTED)
        self.auth_admin()
        response = self.client.post(f'{reg_detail(reg.pk)}confirm/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg.refresh_from_db()
        self.assertEqual(reg.status, WorkshopRegistrationStatus.CONFIRMED)

    def test_confirm_already_confirmed_returns_400(self):
        reg = self.create_registration()
        self.auth_admin()
        response = self.client.post(f'{reg_detail(reg.pk)}confirm/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_confirmed_registration(self):
        reg = self.create_registration()
        self.auth_admin()
        response = self.client.post(f'{reg_detail(reg.pk)}cancel/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg.refresh_from_db()
        self.assertEqual(reg.status, WorkshopRegistrationStatus.CANCELLED)

    def test_cancel_promotes_waitlisted(self):
        # Fill workshop (cap=1)
        self.workshop.capacity = 1
        self.workshop.save()
        confirmed_reg = self.create_registration(status_val=WorkshopRegistrationStatus.CONFIRMED)
        waitlisted_reg = self.create_registration(
            attendee=self.attendee2,
            status_val=WorkshopRegistrationStatus.WAITLISTED,
        )
        self.auth_admin()
        self.client.post(f'{reg_detail(confirmed_reg.pk)}cancel/')
        waitlisted_reg.refresh_from_db()
        self.assertEqual(waitlisted_reg.status, WorkshopRegistrationStatus.CONFIRMED)

    def test_cancel_already_cancelled_returns_400(self):
        reg = self.create_registration(status_val=WorkshopRegistrationStatus.CANCELLED)
        self.auth_admin()
        response = self.client.post(f'{reg_detail(reg.pk)}cancel/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_promote_from_waitlist_action(self):
        confirmed = self.create_registration()
        waitlisted = self.create_registration(
            attendee=self.attendee2,
            status_val=WorkshopRegistrationStatus.WAITLISTED,
        )
        self.auth_admin()
        response = self.client.post(f'{reg_detail(confirmed.pk)}promote-waitlist/')
        # Workshop is not full so first waitlisted is promoted
        waitlisted.refresh_from_db()
        self.assertEqual(waitlisted.status, WorkshopRegistrationStatus.CONFIRMED)

    def test_promote_returns_204_when_no_waitlist(self):
        reg = self.create_registration()
        self.auth_admin()
        response = self.client.post(f'{reg_detail(reg.pk)}promote-waitlist/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_confirm_requires_staff(self):
        reg = self.create_registration(status_val=WorkshopRegistrationStatus.WAITLISTED)
        self.auth_regular()
        response = self.client.post(f'{reg_detail(reg.pk)}confirm/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# WorkshopInterestSubmission CRUD + actions
# ===========================================================================

class WorkshopInterestSubmissionCRUDTest(BaseWorkshopTestCase):

    def _submission_payload(self):
        return {
            'event': str(self.event.pk),
            'attendee': str(self.attendee.pk),
            'ranks': [
                {'workshop': str(self.workshop.pk), 'rank': 1},
            ],
        }

    def test_create_submission(self):
        self.auth_admin()
        response = self.client.post(INTEREST_URL, self._submission_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(WorkshopInterestSubmission.objects.filter(
            event=self.event, attendee=self.attendee,
        ).exists())

    def test_create_submission_creates_rank(self):
        self.auth_admin()
        self.client.post(INTEREST_URL, self._submission_payload(), format='json')
        sub = WorkshopInterestSubmission.objects.get(event=self.event, attendee=self.attendee)
        self.assertEqual(sub.ranks.count(), 1)

    def test_create_submission_rejects_duplicate_ranks(self):
        self.auth_admin()
        ws2 = Workshop.objects.create(
            title='WS2', description='d', event=self.event,
            date=timezone.now() + timedelta(days=31), status=WorkshopStatus.OPEN,
        )
        payload = {
            'event': str(self.event.pk),
            'attendee': str(self.attendee.pk),
            'ranks': [
                {'workshop': str(self.workshop.pk), 'rank': 1},
                {'workshop': str(ws2.pk), 'rank': 1},  # duplicate rank value
            ],
        }
        response = self.client.post(INTEREST_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_submission_rejects_workshop_from_different_event(self):
        other_user = make_user_helper('other_sub')
        other_event = make_event_helper(other_user, suffix='SUB')
        other_ws = Workshop.objects.create(
            title='Other WS', description='d', event=other_event,
            date=timezone.now() + timedelta(days=31), status=WorkshopStatus.OPEN,
        )
        self.auth_admin()
        payload = {
            'event': str(self.event.pk),
            'attendee': str(self.attendee.pk),
            'ranks': [{'workshop': str(other_ws.pk), 'rank': 1}],
        }
        response = self.client.post(INTEREST_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_submissions(self):
        WorkshopInterestSubmission.objects.create(event=self.event, attendee=self.attendee)
        self.auth_regular()
        response = self.client.get(INTEREST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_draft_submission(self):
        sub = WorkshopInterestSubmission.objects.create(
            event=self.event, attendee=self.attendee,
        )
        self.auth_admin()
        response = self.client.delete(interest_detail(sub.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_finalised_submission_returns_400(self):
        sub = WorkshopInterestSubmission.objects.create(
            event=self.event, attendee=self.attendee, is_finalised=True,
        )
        self.auth_admin()
        response = self.client.delete(interest_detail(sub.pk))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class WorkshopInterestSubmissionActionsTest(BaseWorkshopTestCase):

    def setUp(self):
        super().setUp()
        self.submission = WorkshopInterestSubmission.objects.create(
            event=self.event, attendee=self.attendee,
        )
        WorkshopInterestRank.objects.create(
            submission=self.submission, workshop=self.workshop, rank=1,
        )

    def test_finalise_submission(self):
        self.auth_admin()
        response = self.client.post(f'{interest_detail(self.submission.pk)}finalise/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.submission.refresh_from_db()
        self.assertTrue(self.submission.is_finalised)

    def test_finalise_empty_submission_returns_400(self):
        sub = WorkshopInterestSubmission.objects.create(
            event=self.event, attendee=self.attendee2,
        )
        self.auth_admin()
        response = self.client.post(f'{interest_detail(sub.pk)}finalise/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_finalise_already_finalised_returns_400(self):
        self.submission.is_finalised = True
        self.submission.save()
        self.auth_admin()
        response = self.client.post(f'{interest_detail(self.submission.pk)}finalise/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unfinalize_as_admin(self):
        self.submission.is_finalised = True
        self.submission.save()
        self.auth_admin()
        response = self.client.post(f'{interest_detail(self.submission.pk)}unfinalize/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.submission.refresh_from_db()
        self.assertFalse(self.submission.is_finalised)

    def test_unfinalize_not_finalised_returns_400(self):
        self.auth_admin()
        response = self.client.post(f'{interest_detail(self.submission.pk)}unfinalize/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ===========================================================================
# WorkshopStaff CRUD
# ===========================================================================

class WorkshopStaffCRUDTest(BaseWorkshopTestCase):

    def test_list_staff(self):
        self.auth_regular()
        response = self.client.get(STAFF_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_staff_assignment(self):
        self.auth_admin()
        payload = {
            'workshop': str(self.workshop.pk),
            'event_staff': str(self.event_staff.pk),
            'role': WorkshopStaffRoleChoice.INSTRUCTOR,
        }
        response = self.client.post(STAFF_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(WorkshopStaff.objects.filter(
            workshop=self.workshop, event_staff=self.event_staff,
        ).exists())

    def test_create_staff_from_different_event_returns_400(self):
        other_admin = make_user_helper('other_staff_admin')
        other_event = make_event_helper(other_admin, suffix='STF')
        other_es = EventStaff.objects.create(event=other_event, user=other_admin)
        self.auth_admin()
        payload = {
            'workshop': str(self.workshop.pk),
            'event_staff': str(other_es.pk),
            'role': WorkshopStaffRoleChoice.ASSISTANT,
        }
        response = self.client.post(STAFF_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_staff_assignment(self):
        ws_staff = WorkshopStaff.objects.create(
            workshop=self.workshop,
            event_staff=self.event_staff,
            role=WorkshopStaffRoleChoice.LEADER,
            added_by=self.admin,
        )
        self.auth_admin()
        response = self.client.delete(staff_detail(ws_staff.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Interest Ranking Allocation integration test
# ===========================================================================

class InterestRankingAllocationIntegrationTest(BaseWorkshopTestCase):
    """
    End-to-end test for the interest ranking allocation flow via the API.

    Flow:
    1. Create workshops (cap=1 each)
    2. Both attendees submit finalised interest rankings
    3. Trigger run_allocation on workshop (INTEREST_RANKING mode)
    4. Verify one attendee is CONFIRMED and one is WAITLISTED
    """

    def setUp(self):
        super().setUp()
        # Reconfigure workshop for interest ranking
        self.workshop.allocation_mode = AllocationMode.INTEREST_RANKING
        self.workshop.capacity = 1
        self.workshop.save()

        # Create a second workshop
        self.workshop2 = Workshop.objects.create(
            title='Pottery 101',
            description='Pottery workshop.',
            event=self.event,
            date=timezone.now() + timedelta(days=31),
            status=WorkshopStatus.OPEN,
            capacity=1,
            allocation_mode=AllocationMode.INTEREST_RANKING,
        )

    def test_interest_ranking_allocation_places_attendees(self):
        # Attendee 1: prefers workshop1 first
        sub1 = WorkshopInterestSubmission.objects.create(
            event=self.event, attendee=self.attendee, is_finalised=True,
        )
        WorkshopInterestRank.objects.create(submission=sub1, workshop=self.workshop, rank=1)
        WorkshopInterestRank.objects.create(submission=sub1, workshop=self.workshop2, rank=2)

        # Attendee 2: also prefers workshop1 first (submitted later)
        sub2 = WorkshopInterestSubmission.objects.create(
            event=self.event, attendee=self.attendee2, is_finalised=True,
        )
        WorkshopInterestRank.objects.create(submission=sub2, workshop=self.workshop, rank=1)
        WorkshopInterestRank.objects.create(submission=sub2, workshop=self.workshop2, rank=2)

        self.auth_admin()
        response = self.client.post(f'{ws_detail(self.workshop.pk)}run-allocation/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('placed', response.data)

        # One attendee should be confirmed in workshop1, the other in workshop2
        regs = WorkshopRegistration.objects.filter(
            workshop__in=[self.workshop, self.workshop2],
            status=WorkshopRegistrationStatus.CONFIRMED,
        )
        self.assertEqual(regs.count(), 2)


# ---------------------------------------------------------------------------
# Module-level helpers (used by some test methods)
# ---------------------------------------------------------------------------

def make_user_helper(username):
    return User.objects.create_user(
        username=username,
        email=f'{username}@test.com',
        password='testpass123',
    )


def make_event_helper(created_by, suffix='X'):
    et, _ = EventType.objects.get_or_create(
        code=f'WSAPI{suffix}',
        defaults={'title': f'Type {suffix}', 'created_by': created_by},
    )
    org, _ = Organisation.objects.get_or_create(
        title=f'Org API {suffix}',
        defaults={'created_by': created_by},
    )
    return Event.objects.create(
        title=f'API Test Event {suffix}',
        display_code=f'WSAPI{suffix}',
        created_by=created_by,
        event_type=et,
        start_datetime=timezone.now() + timedelta(days=30),
        end_datetime=timezone.now() + timedelta(days=32),
        status=EventStatusChoices.OPEN,
        organisation=org,
    )
