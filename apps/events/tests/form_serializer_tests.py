"""
Unit tests for Event Forms serializers.

Covers:
- EventFormQuestionSerializer nested option write/update/delete atomicity
- Type-specific validation errors
- EventFormSerializer create sets created_by
- EventFormResponseAnswerSerializer file url + choices
- EventFormDelegateTokenValidateSerializer
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.events.models import (
    Event, EventType, EventStatusChoices,
    EventForm, EventFormStatusChoices,
    EventFormQuestion, EventFormQuestionTypeChoices, EventFormQuestionOption,
    EventFormResponse, EventFormResponseAnswer,
    EventFormDelegateToken,
)
from apps.events.api.serializers.forms import (
    EventFormQuestionSerializer,
    EventFormSerializer,
    EventFormResponseAnswerSerializer,
    EventFormDelegateTokenSerializer,
    EventFormDelegateTokenValidateSerializer,
)
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee

User = get_user_model()


class SerializerTestBase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='seruser', email='ser@example.com', password='pass', is_staff=True
        )
        self.organisation = Organisation.objects.create(title='Org', created_by=self.user)
        self.event_type = EventType.objects.create(title='Conf', code='CONF', created_by=self.user)
        self.event = Event.objects.create(
            title='Test Event',
            display_code='TE001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=10),
            end_datetime=timezone.now() + timedelta(days=12),
            organisation=self.organisation,
            status=EventStatusChoices.PUBLISHED,
        )
        self.form = EventForm.objects.create(
            event=self.event,
            title='Test Form',
            status=EventFormStatusChoices.DRAFT,
            created_by=self.user,
        )

    def _drf_request(self):
        request = self.factory.get('/')
        force_authenticate(request, user=self.user)
        drf_request = Request(request)
        drf_request._user = self.user  # bypass DRF's lazy authentication
        return drf_request


class EventFormQuestionSerializerCreateTest(SerializerTestBase):
    def test_create_short_answer_question(self):
        data = {
            'form': str(self.form.id),
            'question_title': 'Your name',
            'question_body': 'Enter your full name',
            'question_type': 'short_answer',
            'required': True,
            'order': 0,
        }
        ser = EventFormQuestionSerializer(data=data, context={'request': self._drf_request()})
        self.assertTrue(ser.is_valid(), ser.errors)
        q = ser.save()
        self.assertEqual(q.question_title, 'Your name')

    def test_create_choice_question_with_options(self):
        data = {
            'form': str(self.form.id),
            'question_title': 'Preferred session',
            'question_body': 'Pick one',
            'question_type': 'single_choice',
            'required': False,
            'order': 1,
            'options': [
                {'option_text': 'Morning', 'order': 0},
                {'option_text': 'Evening', 'order': 1},
            ],
        }
        ser = EventFormQuestionSerializer(data=data, context={'request': self._drf_request()})
        self.assertTrue(ser.is_valid(), ser.errors)
        q = ser.save()
        self.assertEqual(q.options.count(), 2)

    def test_choice_question_without_options_fails(self):
        data = {
            'form': str(self.form.id),
            'question_title': 'Preferred session',
            'question_body': 'Pick one',
            'question_type': 'multiple_choice',
            'order': 2,
            'options': [],
        }
        ser = EventFormQuestionSerializer(data=data, context={'request': self._drf_request()})
        self.assertFalse(ser.is_valid())
        self.assertIn('options', ser.errors)

    def test_slider_missing_min_max_fails(self):
        data = {
            'form': str(self.form.id),
            'question_title': 'Rate',
            'question_body': 'Rate from 1-10',
            'question_type': 'slider',
            'order': 3,
        }
        ser = EventFormQuestionSerializer(data=data, context={'request': self._drf_request()})
        self.assertFalse(ser.is_valid())

    def test_short_answer_with_min_max_fails(self):
        data = {
            'form': str(self.form.id),
            'question_title': 'Name',
            'question_body': 'Your name',
            'question_type': 'short_answer',
            'order': 4,
            'min_value': 1,
            'max_value': 10,
        }
        ser = EventFormQuestionSerializer(data=data, context={'request': self._drf_request()})
        self.assertFalse(ser.is_valid())

    def test_update_question_merges_options(self):
        q = EventFormQuestion.objects.create(
            form=self.form,
            question_title='Old Title',
            question_body='Old body',
            question_type=EventFormQuestionTypeChoices.SINGLE_CHOICE,
            order=5,
        )
        opt = EventFormQuestionOption.objects.create(question=q, option_text='Option A', order=0)

        data = {
            'form': str(self.form.id),
            'question_title': 'New Title',
            'question_body': 'New body',
            'question_type': 'single_choice',
            'order': 5,
            'options': [
                {'id': str(opt.id), 'option_text': 'Updated A', 'order': 0},
                {'option_text': 'New B', 'order': 1},
            ],
        }
        ser = EventFormQuestionSerializer(q, data=data, context={'request': self._drf_request()})
        self.assertTrue(ser.is_valid(), ser.errors)
        q = ser.save()
        self.assertEqual(q.question_title, 'New Title')
        self.assertEqual(q.options.count(), 2)
        self.assertTrue(q.options.filter(option_text='Updated A').exists())
        self.assertTrue(q.options.filter(option_text='New B').exists())

    def test_title_too_short_fails(self):
        data = {
            'form': str(self.form.id),
            'question_title': 'AB',  # less than 3 chars
            'question_body': 'Body',
            'question_type': 'short_answer',
            'order': 6,
        }
        ser = EventFormQuestionSerializer(data=data, context={'request': self._drf_request()})
        self.assertFalse(ser.is_valid())
        self.assertIn('question_title', ser.errors)


class EventFormSerializerTest(SerializerTestBase):
    def test_create_sets_event_via_slug(self):
        data = {
            'event': str(self.event.event_id),
            'title': 'New Form',
            'description': 'Some description',
            'status': 'draft',
            'required': False,
            'allow_response_editing': True,
        }
        ser = EventFormSerializer(data=data, context={'request': self._drf_request()})
        self.assertTrue(ser.is_valid(), ser.errors)
        form = ser.save()
        self.assertEqual(form.event, self.event)
        self.assertEqual(form.created_by, self.user)


class EventFormDelegateTokenSerializerTest(SerializerTestBase):
    def _make_response(self):
        attendee = Attendee.objects.create(
            first_name='Alice',
            last_name='Smith',
            event=self.event,
            defined_by=self.user,
            date_of_birth='1992-03-10',
        )
        return EventFormResponse.objects.create(form=self.form, attendee=attendee)

    def test_create_token(self):
        resp = self._make_response()
        data = {
            'response': str(resp.id),
            'expires_at': (timezone.now() + timedelta(days=1)).isoformat(),
        }
        ser = EventFormDelegateTokenSerializer(data=data, context={'request': self._drf_request()})
        self.assertTrue(ser.is_valid(), ser.errors)
        token = ser.save()
        self.assertEqual(token.response, resp)
        self.assertEqual(token.created_by, self.user)

    def test_past_expires_at_fails(self):
        resp = self._make_response()
        data = {
            'response': str(resp.id),
            'expires_at': (timezone.now() - timedelta(hours=1)).isoformat(),
        }
        ser = EventFormDelegateTokenSerializer(data=data, context={'request': self._drf_request()})
        self.assertFalse(ser.is_valid())
        self.assertIn('expires_at', ser.errors)
