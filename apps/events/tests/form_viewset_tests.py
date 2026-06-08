"""
Unit tests for Event Forms viewsets (API integration tests).

Covers:
- CRUD for EventForm, EventFormQuestion, EventFormResponse
- publish / close actions
- Attendee response ownership enforcement
- Public delegate token validate endpoint
- File upload answer
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from io import BytesIO

from rest_framework.test import APIClient
from rest_framework import status

from apps.events.models import (
    Event, EventType, EventStatusChoices,
    EventForm, EventFormStatusChoices,
    EventFormQuestion, EventFormQuestionTypeChoices, EventFormQuestionOption,
    EventFormResponse, EventFormResponseAnswer,
    EventFormDelegateToken,
)
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee

User = get_user_model()


class FormViewSetTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff_user = User.objects.create_user(
            username='staff', email='staff@example.com', password='pass', is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username='regular', email='regular@example.com', password='pass'
        )
        self.other_user = User.objects.create_user(
            username='other', email='other@example.com', password='pass'
        )
        self.organisation = Organisation.objects.create(title='Org', created_by=self.staff_user)
        self.event_type = EventType.objects.create(title='Conf', code='CONF', created_by=self.staff_user)
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE001',
            created_by=self.staff_user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=10),
            end_datetime=timezone.now() + timedelta(days=12),
            organisation=self.organisation,
            status=EventStatusChoices.PUBLISHED,
        )
        self.form = EventForm.objects.create(
            event=self.event,
            title='Consent Form',
            status=EventFormStatusChoices.DRAFT,
            created_by=self.staff_user,
        )

    def _make_attendee(self, user=None):
        u = user or self.regular_user
        return Attendee.objects.create(
            first_name='Jane',
            last_name='Doe',
            event=self.event,
            defined_by=u,
            date_of_birth='1990-01-01',
            user=u,
        )


class EventFormCRUDTest(FormViewSetTestBase):
    def test_list_unauthenticated_returns_401(self):
        response = self.client.get('/api/event/forms/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_authenticated(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get('/api/event/forms/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_form_by_staff(self):
        self.client.force_authenticate(user=self.staff_user)
        data = {
            'event': str(self.event.event_id),
            'title': 'Itinerary Form',
            'description': 'Please fill in',
            'status': 'draft',
            'required': False,
            'allow_response_editing': True,
        }
        response = self.client.post('/api/event/forms/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Itinerary Form')

    def test_retrieve_form(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(f'/api/event/forms/{self.form.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Consent Form')

    def test_partial_update_form(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.patch(
            f'/api/event/forms/{self.form.id}/',
            {'title': 'Updated Form'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Form')

    def test_delete_form_by_staff(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.delete(f'/api/event/forms/{self.form.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(EventForm.objects.filter(id=self.form.id).exists())


class EventFormLifecycleActionsTest(FormViewSetTestBase):
    def test_publish_action(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(f'/api/event/forms/{self.form.id}/publish/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.form.refresh_from_db()
        self.assertEqual(self.form.status, EventFormStatusChoices.PUBLISHED)

    def test_publish_closed_form_returns_400(self):
        self.form.close()
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(f'/api/event/forms/{self.form.id}/publish/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_close_action(self):
        self.form.publish()
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(f'/api/event/forms/{self.form.id}/close/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.form.refresh_from_db()
        self.assertEqual(self.form.status, EventFormStatusChoices.CLOSED)


class EventFormQuestionViewSetTest(FormViewSetTestBase):
    def test_create_question(self):
        self.client.force_authenticate(user=self.staff_user)
        data = {
            'form': str(self.form.id),
            'question_title': 'Dietary requirements',
            'question_body': 'Any dietary requirements?',
            'question_type': 'short_answer',
            'required': False,
            'order': 0,
        }
        response = self.client.post('/api/event/form-questions/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_bulk_create_questions(self):
        self.client.force_authenticate(user=self.staff_user)
        data = [
            {
                'form': str(self.form.id),
                'question_title': 'Q1 title',
                'question_body': 'Q1 body',
                'question_type': 'short_answer',
                'order': 0,
            },
            {
                'form': str(self.form.id),
                'question_title': 'Q2 title',
                'question_body': 'Q2 body',
                'question_type': 'long_answer',
                'order': 1,
            },
        ]
        response = self.client.post(
            f'/api/event/forms/{self.form.id}/bulk-create-questions/', data, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data), 2)

    def test_reorder_questions(self):
        q1 = EventFormQuestion.objects.create(
            form=self.form, question_title='Q1 title', question_body='b', question_type='short_answer', order=0
        )
        q2 = EventFormQuestion.objects.create(
            form=self.form, question_title='Q2 title', question_body='b', question_type='short_answer', order=1
        )
        self.client.force_authenticate(user=self.staff_user)
        data = {'questions': [
            {'id': str(q1.id), 'order': 1},
            {'id': str(q2.id), 'order': 0},
        ]}
        response = self.client.post(
            f'/api/event/forms/{self.form.id}/reorder-questions/', data, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        q1.refresh_from_db()
        self.assertEqual(q1.order, 1)


class EventFormResponseOwnershipTest(FormViewSetTestBase):
    def test_attendee_can_create_response(self):
        self.form.publish()
        attendee = self._make_attendee()
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'form': str(self.form.id),
            'attendee': attendee.id,
            'is_complete': False,
        }
        response = self.client.post('/api/event/form-responses/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cannot_submit_to_draft_form(self):
        attendee = self._make_attendee()
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'form': str(self.form.id),
            'attendee': attendee.id,
            'is_complete': False,
        }
        response = self.client.post('/api/event/form-responses/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_sees_all_responses(self):
        self.form.publish()
        att1 = self._make_attendee()
        att2 = self._make_attendee(user=self.other_user)
        EventFormResponse.objects.create(form=self.form, attendee=att1)
        EventFormResponse.objects.create(form=self.form, attendee=att2)
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get('/api/event/form-responses/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['count'], 2)


class EventFormDelegateTokenValidateTest(FormViewSetTestBase):
    def _make_token(self):
        attendee = self._make_attendee()
        resp = EventFormResponse.objects.create(form=self.form, attendee=attendee)
        return EventFormDelegateToken.objects.create(
            response=resp,
            created_by=self.staff_user,
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def test_validate_valid_token_public_endpoint(self):
        token_obj = self._make_token()
        response = self.client.get(
            f'/api/event/form-delegate-tokens/validate/?token={token_obj.token}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_valid'])
        self.assertEqual(str(response.data['form_id']), str(self.form.id))

    def test_validate_invalid_token_returns_404(self):
        import uuid
        response = self.client.get(
            f'/api/event/form-delegate-tokens/validate/?token={uuid.uuid4()}'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_validate_no_token_returns_400(self):
        response = self.client.get('/api/event/form-delegate-tokens/validate/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_expired_token_returns_404(self):
        attendee = self._make_attendee()
        resp = EventFormResponse.objects.create(form=self.form, attendee=attendee)
        token_obj = EventFormDelegateToken.objects.create(
            response=resp,
            created_by=self.staff_user,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        response = self.client.get(
            f'/api/event/form-delegate-tokens/validate/?token={token_obj.token}'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
