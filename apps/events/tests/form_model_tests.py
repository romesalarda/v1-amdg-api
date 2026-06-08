"""
Unit tests for Event Forms models.

Covers:
- EventForm lifecycle (publish/close)
- EventFormQuestion.clean() per question type
- Unique constraints
- EventFormDelegateToken.is_valid property
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import IntegrityError
from datetime import timedelta

from apps.events.models import (
    Event, EventType, EventStatusChoices,
    EventForm, EventFormStatusChoices,
    EventFormQuestion, EventFormQuestionTypeChoices, EventFormQuestionOption,
    EventFormResponse, EventFormResponseAnswer, EventFormResponseAnswerChoice,
    EventFormDelegateToken,
)
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee

User = get_user_model()


class EventFormModelTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='formuser', email='form@example.com', password='pass'
        )
        self.organisation = Organisation.objects.create(
            title='Test Org', created_by=self.user
        )
        self.event_type = EventType.objects.create(
            title='Conference', code='CONF', created_by=self.user
        )
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
            title='Consent Form',
            status=EventFormStatusChoices.DRAFT,
            created_by=self.user,
        )


class EventFormLifecycleTest(EventFormModelTestBase):
    def test_default_status_is_draft(self):
        self.assertEqual(self.form.status, EventFormStatusChoices.DRAFT)

    def test_publish_transitions_to_published(self):
        self.form.publish()
        self.form.refresh_from_db()
        self.assertEqual(self.form.status, EventFormStatusChoices.PUBLISHED)

    def test_close_transitions_to_closed(self):
        self.form.publish()
        self.form.close()
        self.form.refresh_from_db()
        self.assertEqual(self.form.status, EventFormStatusChoices.CLOSED)

    def test_str_representation(self):
        self.assertIn('Consent Form', str(self.form))

    def test_repr_representation(self):
        self.assertIn('EventForm', repr(self.form))


class EventFormQuestionCleanTest(EventFormModelTestBase):
    def test_slider_requires_min_and_max(self):
        q = EventFormQuestion(
            form=self.form,
            question_title='Slider Q',
            question_body='Rate it',
            question_type=EventFormQuestionTypeChoices.SLIDER,
        )
        with self.assertRaises(ValidationError):
            q.clean()

    def test_slider_min_less_than_max(self):
        q = EventFormQuestion(
            form=self.form,
            question_title='Slider Q',
            question_body='Rate it',
            question_type=EventFormQuestionTypeChoices.SLIDER,
            min_value=10,
            max_value=5,
        )
        with self.assertRaises(ValidationError):
            q.clean()

    def test_slider_valid_passes_clean(self):
        q = EventFormQuestion(
            form=self.form,
            question_title='Slider Q',
            question_body='Rate it',
            question_type=EventFormQuestionTypeChoices.SLIDER,
            min_value=1,
            max_value=10,
        )
        q.clean()  # should not raise

    def test_rating_requires_min_and_max(self):
        q = EventFormQuestion(
            form=self.form,
            question_title='Rating Q',
            question_body='Rate',
            question_type=EventFormQuestionTypeChoices.RATING,
        )
        with self.assertRaises(ValidationError):
            q.clean()

    def test_short_answer_rejects_min_max(self):
        q = EventFormQuestion(
            form=self.form,
            question_title='Short Q',
            question_body='Body',
            question_type=EventFormQuestionTypeChoices.SHORT_ANSWER,
            min_value=1,
        )
        with self.assertRaises(ValidationError):
            q.clean()

    def test_date_question_clean_passes(self):
        q = EventFormQuestion(
            form=self.form,
            question_title='Date Q',
            question_body='When?',
            question_type=EventFormQuestionTypeChoices.DATE,
        )
        q.clean()  # should not raise


class EventFormQuestionOrderConstraintTest(TransactionTestCase):
    """
    Uses TransactionTestCase so each save actually commits, allowing the
    DEFERRED unique constraint on (form, order) to fire at commit time.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='construser', email='constr@example.com', password='pass'
        )
        self.organisation = Organisation.objects.create(title='Constr Org', created_by=self.user)
        self.event_type = EventType.objects.create(title='Conf', code='CSTR', created_by=self.user)
        self.event = Event.objects.create(
            title='Constr Event',
            display_code='CSTR1',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=10),
            end_datetime=timezone.now() + timedelta(days=12),
            organisation=self.organisation,
            status=EventStatusChoices.PUBLISHED,
        )
        self.form = EventForm.objects.create(
            event=self.event,
            title='Constr Form',
            status=EventFormStatusChoices.DRAFT,
            created_by=self.user,
        )

    def test_duplicate_order_raises_integrity_error(self):
        from django.db import transaction
        EventFormQuestion.objects.create(
            form=self.form,
            question_title='Q1',
            question_body='Body 1',
            question_type=EventFormQuestionTypeChoices.SHORT_ANSWER,
            order=0,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EventFormQuestion.objects.create(
                    form=self.form,
                    question_title='Q2',
                    question_body='Body 2',
                    question_type=EventFormQuestionTypeChoices.SHORT_ANSWER,
                    order=0,
                )


class EventFormResponseUniqueTest(TransactionTestCase):
    """
    Uses TransactionTestCase so the unique constraint on (form, attendee)
    fires at commit time rather than being deferred inside a test transaction.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='respuser', email='resp@example.com', password='pass'
        )
        self.organisation = Organisation.objects.create(title='Resp Org', created_by=self.user)
        self.event_type = EventType.objects.create(title='Conf', code='RESP', created_by=self.user)
        self.event = Event.objects.create(
            title='Resp Event',
            display_code='RESP1',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=10),
            end_datetime=timezone.now() + timedelta(days=12),
            organisation=self.organisation,
            status=EventStatusChoices.PUBLISHED,
        )
        self.form = EventForm.objects.create(
            event=self.event,
            title='Resp Form',
            status=EventFormStatusChoices.DRAFT,
            created_by=self.user,
        )

    def _make_attendee(self):
        return Attendee.objects.create(
            first_name='Jane',
            last_name='Doe',
            event=self.event,
            defined_by=self.user,
            date_of_birth='1990-01-01',
        )

    def test_one_response_per_attendee_per_form(self):
        from django.db import transaction
        attendee = self._make_attendee()
        EventFormResponse.objects.create(form=self.form, attendee=attendee)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EventFormResponse.objects.create(form=self.form, attendee=attendee)


class EventFormDelegateTokenIsValidTest(EventFormModelTestBase):
    def _make_response(self):
        attendee = Attendee.objects.create(
            first_name='Tom',
            last_name='Jones',
            event=self.event,
            defined_by=self.user,
            date_of_birth='1985-06-15',
        )
        return EventFormResponse.objects.create(form=self.form, attendee=attendee)

    def test_fresh_token_is_valid(self):
        resp = self._make_response()
        token = EventFormDelegateToken.objects.create(
            response=resp,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.assertTrue(token.is_valid)

    def test_expired_token_is_invalid(self):
        resp = self._make_response()
        token = EventFormDelegateToken.objects.create(
            response=resp,
            created_by=self.user,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(token.is_valid)

    def test_used_token_is_invalid(self):
        resp = self._make_response()
        token = EventFormDelegateToken.objects.create(
            response=resp,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(hours=24),
            is_used=True,
        )
        self.assertFalse(token.is_valid)
